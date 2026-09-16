"""Live Red-Team Lab: "Try Your Own Input" (System V5.4).

A judge types their own sentence; this module derives a small curated set of adversarial
variants from it using the *existing* attack library (never a new attack implementation),
runs them against V1 (unhardened) and V2 (hardened) -- the same underlying model, only the
application-layer hardening differs -- and reports label flips, confidence change, and a
total-variation-distance measure of how much the full probability distribution moved, plus a
deterministic, rule-based diagnosis (never an LLM).

Everything here is ephemeral by construction: a lab run never writes to ``results/`` or
``artifacts/verified_full_report/`` -- ``send_case`` talks to the endpoint directly (no
``ResultWriter``, no disk I/O) and the only file a run touches is a ``tempfile`` directory
holding the two uvicorn boot logs ``run_all.start_endpoint`` already writes, removed as soon
as each endpoint stops (see ``_cleanup_temp_dir`` for why that's a bounded retry rather than a
single attempt).

Concurrency: ``JOB_LOCK`` is the *one* shared mutex for "start any experiment" -- imported by
``web/app.py`` and used in place of its own ``threading.Lock()`` -- because a Live Demo job and
a Lab job both need the fixed V1/V2 ports (8000/8001) from ``run_all.ENDPOINT_SPECS`` and can
never run at the same time. Only one Lab job can be active at once; its ``job_id`` is an
unpredictable token (``secrets.token_urlsafe``), and ``GET /api/lab/status/{job_id}`` (wired up
in ``web/app.py``) only ever returns data for the job whose id matches exactly -- a wrong or
stale id gets a generic "not found", never another visitor's text or result.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import run_all  # noqa: E402
from attacks import library as attack_library  # noqa: E402
from attacks import metadata as attack_metadata  # noqa: E402
from contract import AttackCase, BaselineCase, RunResult  # noqa: E402
from runner import run as runner_run  # noqa: E402
from web import progress as progress_module  # noqa: E402

logger = logging.getLogger("team_checkmate.web.lab")

# ----------------------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------------------

# Server-side enforced limit (within the brief's 500-1000 char range); echoed to the client so
# the live counter and the server's own rejection never drift apart.
MAX_INPUT_CHARS = 800

# v6.1 Phase 3: paired (emotion) vs single-target (sentiment) get distinct descriptors -- the
# single-target flow genuinely runs one target, with its own real "clean reference" step
# (run_custom_lab's sentiment branch calls send_case for the clean reference and then, in a
# separate call, for the variants -- these are two real events here, unlike the Live Demo's
# combined suite send), so it earns its own distinct stage list rather than reusing the paired
# one or hiding cards with CSS.
PAIRED_LAB_STAGE_ORDER = (
    "preparing", "starting_v1", "clean_v1", "attacking_v1",
    "starting_v2", "clean_v2", "attacking_v2", "analyzing", "complete",
)
PAIRED_LAB_STAGE_LABELS = {
    "preparing": "Preparing custom test",
    "starting_v1": "Starting V1",
    "clean_v1": "Running clean V1 reference",
    "attacking_v1": "Testing V1 adversarial variants",
    "starting_v2": "Starting V2",
    "clean_v2": "Running clean V2 reference",
    "attacking_v2": "Testing V2 adversarial variants",
    "analyzing": "Analyzing differences",
    "complete": "Complete",
}
PAIRED_LAB_STAGE_PERCENT = dict(zip(PAIRED_LAB_STAGE_ORDER, (5, 15, 30, 45, 55, 70, 85, 95, 100)))

SINGLE_LAB_STAGE_ORDER = (
    "preparing", "starting_target", "clean_reference", "adversarial_variants",
    "analyzing", "complete",
)
SINGLE_LAB_STAGE_LABELS = {
    "preparing": "Preparing custom test",
    "starting_target": "Starting sentiment target",
    "clean_reference": "Running clean reference",
    "adversarial_variants": "Testing sentiment adversarial variants",
    "analyzing": "Analyzing observations",
    "complete": "Complete",
}
SINGLE_LAB_STAGE_PERCENT = dict(zip(SINGLE_LAB_STAGE_ORDER, (5, 20, 40, 60, 85, 100)))

# Backward-compatible aliases (paired flow only) -- kept because several call sites below still
# read these under their original names.
LAB_STAGE_ORDER = PAIRED_LAB_STAGE_ORDER
LAB_STAGE_LABELS = PAIRED_LAB_STAGE_LABELS
LAB_STAGE_PERCENT = PAIRED_LAB_STAGE_PERCENT


def _lab_descriptor(evaluation_id: str, target_ids: Optional[list] = None) -> dict:
    if evaluation_id == "sentiment.core":
        target_id = (target_ids or ["sentiment_v1"])[0]
        return progress_module.descriptor(
            evaluation_id=evaluation_id, kind="single", target_ids=target_ids or ["sentiment_v1"],
            same_model_note=None,
            footer_note="Single-target sentiment evaluation; no V1/V2 comparison is implied.",
            cards=[progress_module.card(
                "target", "Sentiment — Configured Target",
                f"{target_id} · single-target evaluation; no V1/V2 comparison is implied.",
                start_stage="starting_target", end_stage="adversarial_variants",
            )],
            stage_order=list(SINGLE_LAB_STAGE_ORDER), stage_percent=SINGLE_LAB_STAGE_PERCENT,
            stages=[progress_module.stage(s, SINGLE_LAB_STAGE_LABELS[s])
                    for s in SINGLE_LAB_STAGE_ORDER],
        )
    return progress_module.descriptor(
        evaluation_id=evaluation_id, kind="paired",
        target_ids=target_ids or ["emotion_v1", "emotion_v2"],
        same_model_note="Two endpoint configurations",
        footer_note="Same underlying AI model in both cases — only endpoint hardening differs.",
        cards=[
            progress_module.card(
                "v1", "V1 — Unhardened Endpoint", "No application-layer hardening.",
                start_stage="starting_v1", end_stage="attacking_v1",
            ),
            progress_module.card(
                "v2", "V2 — Hardened Endpoint",
                "Input validation, length controls, exception handling and normalization.",
                start_stage="starting_v2", end_stage="attacking_v2",
            ),
        ],
        stage_order=list(PAIRED_LAB_STAGE_ORDER), stage_percent=PAIRED_LAB_STAGE_PERCENT,
        stages=[progress_module.stage(s, PAIRED_LAB_STAGE_LABELS[s]) for s in PAIRED_LAB_STAGE_ORDER],
    )


def all_lab_descriptors() -> dict:
    return {
        "emotion.core": _lab_descriptor("emotion.core"),
        "sentiment.core": _lab_descriptor("sentiment.core"),
    }

# One authoritative, documented curated selection (brief section 13) -- matched against real
# attacks.metadata fields after attacks.library.build_derived(baseline), never guessed from the
# attack_id string. Every entry is genuinely derived from arbitrary input text, fast, and safe
# for a live judge demo: no is_raw payload, no oversized/filler-padded case, no hardcoded body.
# (family, subfamily, dose, position, friendly_label, description)
CUSTOM_LAB_ATTACKS: tuple[tuple[str, str, Optional[int], Optional[str], str, str], ...] = (
    ("encoding", "homoglyph", 3, "middle", "Cyrillic homoglyph substitution",
     "Visually identical Latin letters replaced with confusable Cyrillic characters."),
    ("encoding", "homoglyph_greek", 3, "middle", "Greek homoglyph substitution",
     "Visually identical Latin letters replaced with confusable Greek characters."),
    ("encoding", "invisible_zero_width", None, "middle", "Invisible Unicode insertion",
     "Zero-width characters inserted; invisible to a reader, present in the byte stream."),
    ("perturbation", "keyboard_typo", None, None, "Keyboard-adjacent typo",
     "One letter replaced by its QWERTY neighbour, as a natural typing mistake would."),
    ("perturbation", "word_split", None, None, "Word-split perturbation",
     "A space inserted inside a word."),
    ("perturbation", "swap_adjacent", None, None, "Adjacent-letter swap",
     "Two interior letters transposed."),
    ("whitespace", "interior_runs", None, None, "Whitespace distortion",
     "Single spaces between words expanded into runs of several spaces."),
    ("whitespace", "unicode_spaces", None, None, "Unicode space substitution",
     "Normal spaces replaced with visually similar Unicode space characters."),
    ("truncation", "signal_head_only", None, None, "Sentence truncation (head only)",
     "Only the first half of the sentence is sent, cut at a word boundary."),
)

DIAGNOSIS_LABELS = {
    "MITIGATED_BY_V2": "Mitigated by V2",
    "PERSISTS_AFTER_HARDENING": "Persists after hardening",
    "LABEL_CHANGED": "Label changed",
    "STABLE_LABEL_DISTRIBUTION_SHIFT": "Label stable; distribution shift observed",
    "NO_OBSERVED_CHANGE": "No observed prediction change",
    "V2_REGRESSION": "V2 regression / investigate",
    "INCONCLUSIVE": "Inconclusive",
    "DIAGNOSTIC_OBSERVATION": "Diagnostic observation (no fixed oracle)",
}

# Deterministic mapping only -- never generated by an LLM (brief section 19).
REMEDIATION = {
    "MITIGATED_BY_V2": (
        "Keep the V2 validation/normalization control and include this case in regression "
        "testing."
    ),
    "PERSISTS_AFTER_HARDENING": (
        "This behavior persists through application-layer hardening. Consider model-level "
        "robustness measures such as adversarial training, augmented data, or targeted "
        "evaluation of this perturbation class."
    ),
    "V2_REGRESSION": (
        "Investigate the V2 preprocessing/validation path before treating the hardened "
        "endpoint as improved for this case."
    ),
    "LABEL_CHANGED": (
        "This is a single-target exploratory result showing a label change. Reproduce it "
        "against the same pinned target before drawing conclusions about model or endpoint "
        "controls."
    ),
    "STABLE_LABEL_DISTRIBUTION_SHIFT": (
        "The top label did not change, but the full probability distribution moved materially "
        "on at least one endpoint. This is not a flip, but the shift is worth tracking -- do "
        "not report it as 'no effect'."
    ),
    "NO_OBSERVED_CHANGE": (
        "No action needed -- this variant produced no recorded change in the top label or the "
        "probability distribution on the endpoint(s) tested."
    ),
    "INCONCLUSIVE": (
        "Required evidence is missing for this comparison; re-run the test or inspect the "
        "endpoint response before drawing a conclusion."
    ),
    "DIAGNOSTIC_OBSERVATION": (
        "This transformation can remove the sentence content that carried the original label "
        "(see attacks.metadata's diagnostic/no-fixed-oracle classification for this case), so "
        "any label change here reflects lost meaning rather than a meaning-preserving model "
        "vulnerability. Treat it as a diagnostic observation, not a scored finding, and do not "
        "infer a hardening or model-remediation requirement from it alone."
    ),
}


class LabValidationError(ValueError):
    """Raised for input that fails server-side validation -- caught by web/app.py as a 422."""


# ----------------------------------------------------------------------------------------
# Attack selection
# ----------------------------------------------------------------------------------------


def build_lab_baseline(text: str, job_id: str) -> BaselineCase:
    # A fresh baseline_id per job is required, not cosmetic: attacks.metadata.register()
    # raises if the same attack_id is ever reused for different content, and attack_ids are
    # derived from baseline_id, so reusing one across two different judge inputs would collide.
    return BaselineCase(baseline_id=f"lab.{job_id}", text=text, label="unknown",
                        source="interactive_lab")


def select_lab_variants(baseline: BaselineCase) -> list[tuple[AttackCase, str, str, bool]]:
    """Curated, deterministic subset of attacks.library.build_derived(baseline).

    Returns ``(case, label, description, is_diagnostic)`` tuples. ``is_diagnostic`` is read
    straight from the attack's own pre-registered metadata (``attacks.metadata.ORACLE_DIAGNOSTIC``
    -- see attacks/truncation.py) -- never re-derived or guessed here -- and marks a case such as
    signal-truncating truncation that has no fixed label oracle, so callers must not auto-score it
    as a vulnerability (v6.1 Phase 7).

    A catalogue entry is only included if its matched attack case actually changes the text
    (``case.attacked_text != case.original_text``); an entry whose one dose/position match is a
    no-op for this particular input is genuinely not applicable here and is silently omitted
    (logged at debug level for diagnostics), never sent to the endpoint or counted as "tested"
    (v6.1 Phase 8). This is the same applicability rule for every evaluation -- emotion and
    sentiment both call this one function on the same catalogue, so neither can see an
    evaluation-specific variant count; only the input text can make a transformation inapplicable.

    Wrapped in a save/restore of attacks.metadata's process-global registry (see
    _isolated_attack_registry below) -- this is the fix for a real cross-contamination bug
    found and reproduced this session: attacks.metadata._MANIFEST/_FINGERPRINTS are plain
    module-level dicts that persist for the life of the (long-running, uvicorn) web process,
    and analysis/validation.py's validate_run() asserts an EXACT set-equality between a demo/
    full run's planned attack ids and the manifest's current keys (analysis/validation.py:124,
    `planned_attacks != set(manifest)`). Before this fix, a Lab job's unique-per-job attack ids
    (derived from its own baseline_id, `lab.<job_id>.*`) were registered permanently into that
    same global dict and never removed, so ANY Live Demo/Full run started afterward in the same
    process -- even much later -- would fail at its analysis stage with "planned attack IDs
    disagree with manifest", regardless of V1/V2 process/port state (which was never the actual
    problem). Restoring the registry to its pre-call snapshot makes a Lab job's registration as
    ephemeral as everything else about it, and is fully safe under the existing JOB_LOCK: only
    one experiment (Lab or Demo) is ever actually in progress process-wide, so there is no
    concurrent registration this could race with.
    """
    with _isolated_attack_registry():
        derived = attack_library.build_derived(baseline)
        selected: list[tuple[AttackCase, str, str, bool]] = []
        for family, subfamily, dose, position, label, desc in CUSTOM_LAB_ATTACKS:
            match = None
            for case in derived:
                meta = attack_metadata.metadata_for(case.attack_id)
                if meta is None or meta.family != family or meta.subfamily != subfamily:
                    continue
                if dose is not None and meta.dose != dose:
                    continue
                if position is not None and meta.position != position:
                    continue
                match = (case, meta)
                break
            if match is None:
                logger.debug("Lab variant %r not applicable: no matching derived case", label)
                continue
            case, meta = match
            if case.attacked_text == case.original_text:
                logger.debug("Lab variant %r omitted: transformation produced no change", label)
                continue
            is_diagnostic = meta.oracle == attack_metadata.ORACLE_DIAGNOSTIC
            selected.append((case, label, desc, is_diagnostic))
    return selected


@contextlib.contextmanager
def _isolated_attack_registry():
    """Snapshot attacks.metadata's global manifest/fingerprint registry and restore it
    afterward, so anything registered inside the `with` block (Lab's own, uniquely-id'd
    attack cases) leaves no trace in the process-wide state that Demo/Full runs' manifest
    validation depends on. Does not edit attacks/metadata.py -- attacks/ is Lamei's folder;
    this only reads and temporarily mutates its already-module-level dicts from the caller's
    side, then puts them back exactly as found.
    """
    manifest_snapshot = dict(attack_metadata._MANIFEST)
    fingerprints_snapshot = dict(attack_metadata._FINGERPRINTS)
    try:
        yield
    finally:
        attack_metadata._MANIFEST.clear()
        attack_metadata._MANIFEST.update(manifest_snapshot)
        attack_metadata._FINGERPRINTS.clear()
        attack_metadata._FINGERPRINTS.update(fingerprints_snapshot)


# ----------------------------------------------------------------------------------------
# Sending a single case -- no ResultWriter, no disk I/O
# ----------------------------------------------------------------------------------------


def send_case(base_url: str, version: str, text: Optional[str], case: Optional[AttackCase],
             baseline_id: Optional[str], *, target_id: str = "", suite_id: str = "") -> RunResult:
    runner_obj = runner_run.Runner(
        target=base_url, version=version, writer=None,
        target_id=target_id, suite_id=suite_id,
    )
    try:
        outcome = runner_obj.send(case, text)
        label, confidence, scores = runner_run.parse_prediction(outcome["response_body"])
        alive = runner_obj.health_ok()
    finally:
        runner_obj.close()
    return RunResult(
        case_type="baseline" if case is None else "attack",
        attack_id=None if case is None else case.attack_id,
        baseline_id=baseline_id,
        category=None if case is None else case.category,
        version=version,
        status_code=outcome["status_code"],
        response_body=outcome["response_body"],
        error=outcome["error"],
        label=label,
        confidence=confidence,
        all_scores=scores,
        latency_ms=outcome["latency_ms"],
        latency_band=outcome["latency_band"],
        endpoint_alive_after=alive,
        target_id=target_id,
        suite_id=suite_id,
    )


def _cleanup_temp_dir(tmp_dir: Path) -> None:
    """Best-effort removal of the ephemeral endpoint-log temp dir.

    This directory only ever holds the two uvicorn boot logs start_endpoint writes -- no user
    text -- so a delayed or occasionally-failed cleanup is a tidiness concern, never a privacy
    one. On Windows, something outside this process (observed directly during this feature's
    own local testing, most likely real-time antivirus scanning of the just-written log file
    under load) can hold a lock on it well after the subprocess has fully exited and
    EndpointHandle.stop() has returned, and how long varies with system load -- from under a
    second to tens of seconds. A few quick inline attempts cover the common (no lock) case
    without adding latency; if it's still locked, the remaining retries continue in a
    background daemon thread instead of blocking the judge-facing job on an OS-level lock of
    unpredictable duration.
    """
    if _try_rmtree(tmp_dir, attempts=3, delay=0.3):
        return
    threading.Thread(target=_cleanup_temp_dir_background, args=(tmp_dir,), daemon=True).start()


def _try_rmtree(tmp_dir: Path, *, attempts: int, delay: float) -> bool:
    for _attempt in range(attempts):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if not tmp_dir.exists():
            return True
        time.sleep(delay)
    return not tmp_dir.exists()


def _cleanup_temp_dir_background(tmp_dir: Path) -> None:
    if _try_rmtree(tmp_dir, attempts=12, delay=3.0):
        return
    logger.warning("Could not remove Lab temp directory %s after extended retries", tmp_dir)


def _describe_outcome(result: RunResult) -> str:
    status = result.status_code
    if status is not None and 500 <= status < 600:
        return "Unhandled server error"
    if status is not None and 400 <= status < 500:
        return "Rejected safely"
    if status is not None and 200 <= status < 300:
        return "Accepted"
    if result.latency_band == "timeout":
        return "No response (request timeout)"
    if status is None:
        return "No response (connection/transport failure)"
    return f"HTTP {status}"


def _result_dict(result: RunResult) -> dict:
    return {
        "status_code": result.status_code,
        "outcome": _describe_outcome(result),
        "error": result.error,
        "label": result.label,
        "confidence": result.confidence,
        "all_scores": result.all_scores,
        "latency_ms": result.latency_ms,
        "latency_band": result.latency_band,
        "endpoint_alive_after": result.endpoint_alive_after,
    }


# ----------------------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------------------


def total_variation_distance(p: Optional[dict], q: Optional[dict]) -> Optional[float]:
    """TV(P,Q) = 0.5 * sum_i |P_i - Q_i|. Range 0..1; 0 means identical distributions."""
    if not p or not q:
        return None
    keys = set(p) | set(q)
    return round(0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys), 6)


def label_flipped(clean: RunResult, attacked: RunResult) -> Optional[bool]:
    """Exact top-label change -- no confidence gate (this is the exploratory Lab, not the
    verified benchmark's threshold; brief sections 17-18 are explicit that flip here means
    exactly this and nothing more)."""
    if clean.label is None or attacked.label is None:
        return None
    return clean.label != attacked.label


def confidence_change(clean: RunResult, attacked: RunResult) -> Optional[dict]:
    if clean.confidence is None or attacked.confidence is None:
        return None
    return {
        "clean": clean.confidence,
        "attacked": attacked.confidence,
        "delta": round(attacked.confidence - clean.confidence, 4),
    }


# ----------------------------------------------------------------------------------------
# Diagnosis -- deterministic, rule-based, never an LLM (brief section 17)
# ----------------------------------------------------------------------------------------


def _adverse(clean: RunResult, attacked: RunResult) -> Optional[bool]:
    """True if this endpoint's own attacked outcome looks worse than its own clean
    reference; None if there isn't enough evidence to say either way."""
    if clean.status_code != 200 or clean.label is None:
        return None
    if attacked.status_code is None:
        return True  # connection/transport failure or timeout
    if attacked.status_code >= 500:
        return True
    flip = label_flipped(clean, attacked)
    if flip is None:
        return None
    return flip


def _distribution_shifted(clean: RunResult, attacked: RunResult) -> bool:
    """True if the recorded probability distribution moved at all (v6.1 Phase 6) -- a label
    can stay stable while the full distribution still shifts materially, and that is a
    genuinely different, honestly-reported outcome from "no effect". Missing scores (no
    evidence either way) are treated as no recorded shift, never fabricated as one."""
    tv = total_variation_distance(clean.all_scores, attacked.all_scores)
    return bool(tv)


def diagnose(v1_clean: RunResult, v1_attacked: RunResult,
            v2_clean: RunResult, v2_attacked: RunResult) -> tuple[str, str]:
    v1_adverse = _adverse(v1_clean, v1_attacked)
    v2_adverse = _adverse(v2_clean, v2_attacked)
    if v1_adverse is None or v2_adverse is None:
        code = "INCONCLUSIVE"
    elif v1_adverse and not v2_adverse:
        code = "MITIGATED_BY_V2"
    elif v1_adverse and v2_adverse:
        code = "PERSISTS_AFTER_HARDENING"
    elif not v1_adverse and v2_adverse:
        code = "V2_REGRESSION"
    elif _distribution_shifted(v1_clean, v1_attacked) or _distribution_shifted(v2_clean, v2_attacked):
        # Neither endpoint's top label flipped, but v6.1 Phase 6: "no flip" must never be
        # reported as "no effect" when the recorded distribution moved.
        code = "STABLE_LABEL_DISTRIBUTION_SHIFT"
    else:
        code = "NO_OBSERVED_CHANGE"
    return code, REMEDIATION[code]


# ----------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------


def run_custom_lab(job_id: str, text: str, progress_callback: Callable[[str, str], None],
                   *, evaluation_id: str = "emotion.core") -> dict:
    baseline = build_lab_baseline(text, job_id)
    variants = select_lab_variants(baseline)

    if evaluation_id == "sentiment.core":
        progress_callback("starting_target", "Starting sentiment target")
        tmp_dir = Path(tempfile.mkdtemp(prefix="redlab_lab_sentiment_v1_"))
        registry = run_all.target_registry.load_registry()
        handle = run_all.start_target("sentiment_v1", tmp_dir, registry)
        try:
            progress_callback("clean_reference", "Running clean sentiment reference")
            clean = send_case(
                handle.url, "v1", text, None, baseline.baseline_id,
                target_id="sentiment_v1", suite_id="core",
            )
            progress_callback("adversarial_variants", "Testing sentiment adversarial variants")
            attacked = [
                send_case(
                    handle.url, "v1", case.attacked_text, case, baseline.baseline_id,
                    target_id="sentiment_v1", suite_id="core",
                )
                for case, _label, _desc, _diag in variants
            ]
        finally:
            handle.stop()
            _cleanup_temp_dir(tmp_dir)
        progress_callback("analyzing", SINGLE_LAB_STAGE_LABELS["analyzing"])
        payload = _build_single_result_payload(text, variants, clean, attacked)
        progress_callback("complete", SINGLE_LAB_STAGE_LABELS["complete"])
        return payload
    if evaluation_id != "emotion.core":
        raise LabValidationError(f"Unsupported interactive evaluation {evaluation_id!r}.")

    per_version: dict[str, dict] = {}
    for version in ("v1", "v2"):
        progress_callback(f"starting_{version}", LAB_STAGE_LABELS[f"starting_{version}"])
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"redlab_lab_{version}_"))
        handle = run_all.start_endpoint(version, tmp_dir)
        try:
            progress_callback(f"clean_{version}", LAB_STAGE_LABELS[f"clean_{version}"])
            clean = send_case(handle.url, version, text, None, baseline.baseline_id)

            progress_callback(f"attacking_{version}", LAB_STAGE_LABELS[f"attacking_{version}"])
            variant_results = [
                send_case(handle.url, version, case.attacked_text, case, baseline.baseline_id)
                for case, _label, _desc, _diag in variants
            ]
            per_version[version] = {"clean": clean, "variants": variant_results}
        finally:
            handle.stop()
            # Documented ephemeral temp storage (brief section 7): only the two uvicorn boot
            # logs start_endpoint writes ever land here (no user text), removed immediately.
            _cleanup_temp_dir(tmp_dir)

    progress_callback("analyzing", LAB_STAGE_LABELS["analyzing"])
    payload = _build_result_payload(text, variants, per_version)
    progress_callback("complete", LAB_STAGE_LABELS["complete"])
    return payload


def _build_single_result_payload(text: str, variants, clean: RunResult,
                                 attacked_rows: list[RunResult]) -> dict:
    variants_payload = []
    flips = 0
    diagnostic_observations = 0
    diagnostic_label_changes = 0
    endpoint_errors = 0
    for (case, label, desc, is_diagnostic), attacked in zip(variants, attacked_rows):
        flip = label_flipped(clean, attacked)
        endpoint_errors += int(attacked.status_code is None or attacked.status_code >= 500)
        diff_original_html, diff_attacked_html = run_all.highlight_diff_html(
            case.original_text, case.attacked_text,
        )
        if is_diagnostic:
            # v6.1 Phase 7: this case has no fixed label oracle (attacks.metadata.
            # ORACLE_DIAGNOSTIC) -- report the observation but never auto-score it as a
            # meaning-preserving vulnerability, and count it separately from scored flips.
            diagnostic_observations += 1
            diag_code = "DIAGNOSTIC_OBSERVATION"
            if flip:
                diagnostic_label_changes += 1
        elif flip is None:
            diag_code = "INCONCLUSIVE"
        elif flip:
            flips += 1
            diag_code = "LABEL_CHANGED"
        elif _distribution_shifted(clean, attacked):
            diag_code = "STABLE_LABEL_DISTRIBUTION_SHIFT"
        else:
            diag_code = "NO_OBSERVED_CHANGE"
        variants_payload.append({
            "attack_id": case.attack_id, "label": label, "description": desc,
            "category": case.category, "attacked_text": case.attacked_text,
            "diff_original_html": diff_original_html,
            "diff_attacked_html": diff_attacked_html,
            "is_diagnostic": is_diagnostic,
            "target": {
                "result": _result_dict(attacked), "flip": flip,
                "tv_distance": total_variation_distance(clean.all_scores, attacked.all_scores),
                "confidence_change": confidence_change(clean, attacked),
            },
            "diagnosis": diag_code,
            "diagnosis_label": DIAGNOSIS_LABELS[diag_code],
            "remediation": REMEDIATION[diag_code],
        })
    return {
        "evaluation_id": "sentiment.core", "target_ids": ["sentiment_v1"],
        "single_target": True, "original_text": text, "clean": _result_dict(clean),
        "variants": variants_payload,
        "summary": {
            "variants_tested": len(variants_payload),
            # Automatically scored label flips are kept separate from diagnostic label changes
            # (v6.1 Phase 7) -- a diagnostic case's label change is never folded into "label_flips".
            "label_flips": flips,
            "diagnostic_observations": diagnostic_observations,
            "diagnostic_label_changes": diagnostic_label_changes,
            "safe_rejections": sum(
                1 for row in attacked_rows
                if row.status_code is not None and 400 <= row.status_code < 500
            ),
            "endpoint_errors": endpoint_errors,
        },
    }


def _build_result_payload(text: str, variants: list[tuple[AttackCase, str, str, bool]],
                          per_version: dict) -> dict:
    v1_clean, v2_clean = per_version["v1"]["clean"], per_version["v2"]["clean"]
    variant_rows = []
    counters = {
        "v1_flips": 0, "v2_flips": 0, "safe_rejections": 0, "endpoint_errors": 0,
        "MITIGATED_BY_V2": 0, "PERSISTS_AFTER_HARDENING": 0,
        "STABLE_LABEL_DISTRIBUTION_SHIFT": 0, "NO_OBSERVED_CHANGE": 0,
        "V2_REGRESSION": 0, "INCONCLUSIVE": 0,
        "diagnostic_observations": 0, "diagnostic_label_changes": 0,
    }

    for i, (case, label, desc, is_diagnostic) in enumerate(variants):
        v1_attacked = per_version["v1"]["variants"][i]
        v2_attacked = per_version["v2"]["variants"][i]

        for attacked in (v1_attacked, v2_attacked):
            if attacked.status_code is not None and 400 <= attacked.status_code < 500:
                counters["safe_rejections"] += 1
            elif attacked.status_code is None or attacked.status_code >= 500:
                counters["endpoint_errors"] += 1

        v1_flip = label_flipped(v1_clean, v1_attacked)
        v2_flip = label_flipped(v2_clean, v2_attacked)

        if is_diagnostic:
            # v6.1 Phase 7: never auto-score a no-fixed-oracle case through the normal
            # mitigated/persists/shift/no-change ladder; a flip here reflects removed
            # meaning, not a scored finding, and is tracked separately from v1/v2_flips.
            diag_code = "DIAGNOSTIC_OBSERVATION"
            remediation = REMEDIATION[diag_code]
            counters["diagnostic_observations"] += 1
            if v1_flip or v2_flip:
                counters["diagnostic_label_changes"] += 1
        else:
            if v1_flip:
                counters["v1_flips"] += 1
            if v2_flip:
                counters["v2_flips"] += 1
            diag_code, remediation = diagnose(v1_clean, v1_attacked, v2_clean, v2_attacked)
            counters[diag_code] += 1

        diff_original_html, diff_attacked_html = run_all.highlight_diff_html(
            case.original_text, case.attacked_text,
        )

        variant_rows.append({
            "attack_id": case.attack_id,
            "label": label,
            "description": desc,
            "category": case.category,
            "attacked_text": case.attacked_text,
            "diff_original_html": diff_original_html,
            "diff_attacked_html": diff_attacked_html,
            "is_diagnostic": is_diagnostic,
            "v1": {
                "result": _result_dict(v1_attacked),
                "flip": v1_flip,
                "tv_distance": total_variation_distance(v1_clean.all_scores, v1_attacked.all_scores),
                "confidence_change": confidence_change(v1_clean, v1_attacked),
            },
            "v2": {
                "result": _result_dict(v2_attacked),
                "flip": v2_flip,
                "tv_distance": total_variation_distance(v2_clean.all_scores, v2_attacked.all_scores),
                "confidence_change": confidence_change(v2_clean, v2_attacked),
            },
            "diagnosis": diag_code,
            "diagnosis_label": DIAGNOSIS_LABELS[diag_code],
            "remediation": remediation,
        })

    summary = {
        "variants_tested": len(variants),
        # Automatically scored label flips are kept separate from diagnostic label changes
        # (v6.1 Phase 7).
        "v1_flips": counters["v1_flips"],
        "v2_flips": counters["v2_flips"],
        "diagnostic_observations": counters["diagnostic_observations"],
        "diagnostic_label_changes": counters["diagnostic_label_changes"],
        "mitigated_by_v2": counters["MITIGATED_BY_V2"],
        "persisting_after_hardening": counters["PERSISTS_AFTER_HARDENING"],
        "stable_label_distribution_shift": counters["STABLE_LABEL_DISTRIBUTION_SHIFT"],
        "no_observed_change": counters["NO_OBSERVED_CHANGE"],
        "v2_regression": counters["V2_REGRESSION"],
        "inconclusive": counters["INCONCLUSIVE"],
        "safe_rejections": counters["safe_rejections"],
        "endpoint_errors": counters["endpoint_errors"],
    }
    return {
        "original_text": text,
        "v1_clean": _result_dict(v1_clean),
        "v2_clean": _result_dict(v2_clean),
        "variants": variant_rows,
        "summary": summary,
    }


# ----------------------------------------------------------------------------------------
# Job state / security -- one shared lock with web/app.py's demo job (brief sections 8-10)
# ----------------------------------------------------------------------------------------

JOB_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _idle_lab_state() -> dict:
    return {
        "status": "idle", "job_id": None, "stage": None, "stage_index": -1, "percent": 0,
        "message": "", "evaluation_id": None, "target_ids": [],
        "started_at": None, "completed_at": None, "result": None, "error": None,
    }


_lab_state = _idle_lab_state()


def _reset_state_for_tests() -> None:
    """Test-only helper -- not exposed via any route. Restores a clean idle lab state."""
    global _lab_state
    with JOB_LOCK:
        _lab_state = _idle_lab_state()


def validate_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise LabValidationError("Enter at least one character.")
    if len(stripped) > MAX_INPUT_CHARS:
        raise LabValidationError(f"Limit is {MAX_INPUT_CHARS} characters.")
    return stripped


def start_lab_job(text: str, demo_is_running: Callable[[], bool],
                  *, evaluation_id: str = "emotion.core") -> dict:
    """Validate, then atomically check-and-start under the one shared JOB_LOCK.

    Returns either the new job's public snapshot (status "running") or {"status": "busy"} --
    the busy response never carries a job id, text, or any other visitor's data (brief
    section 27).
    """
    stripped = validate_text(text)
    if evaluation_id not in ("emotion.core", "sentiment.core"):
        raise LabValidationError(f"Unknown evaluation_id {evaluation_id!r}.")
    target_ids = ["sentiment_v1"] if evaluation_id == "sentiment.core" else ["emotion_v1", "emotion_v2"]
    with JOB_LOCK:
        if _lab_state["status"] == "running" or demo_is_running():
            return {"status": "busy"}
        job_id = secrets.token_urlsafe(24)  # cryptographically random, never sequential
        descriptor = _lab_descriptor(evaluation_id, target_ids)
        _lab_state.update(
            status="running", job_id=job_id, stage="preparing", stage_index=0,
            evaluation_id=evaluation_id, target_ids=target_ids,
            percent=descriptor["stage_percent"]["preparing"],
            message=descriptor["stages"][0]["label"],
            started_at=_now_iso(), completed_at=None, result=None, error=None,
        )
        snapshot = dict(_lab_state)
        thread = threading.Thread(
            target=_run_lab_job, args=(job_id, stripped, evaluation_id), daemon=True
        )
        thread.start()
    return snapshot


def is_running_unlocked() -> bool:
    """Read-only peek at Lab's own status, for a caller that already holds JOB_LOCK (e.g.
    web/app.py's demo start route, which aliases JOB_LOCK as its own _job_lock) -- never
    acquires the lock itself, so it's safe to call from inside an existing `with JOB_LOCK:`
    block without deadlocking a non-reentrant threading.Lock."""
    return _lab_state["status"] == "running"


def active_job_id_unlocked() -> Optional[str]:
    """Return the active opaque job id while the caller holds ``JOB_LOCK``."""
    return _lab_state.get("job_id") if _lab_state["status"] == "running" else None


def lab_status(job_id: str) -> Optional[dict]:
    with JOB_LOCK:
        if not job_id or _lab_state.get("job_id") != job_id:
            return None  # generic "not found" -- never reveals another job's existence/data
        return dict(_lab_state)


def _make_progress_callback(job_id: str, evaluation_id: str) -> Callable[[str, str], None]:
    descriptor = _lab_descriptor(evaluation_id)
    stage_order = descriptor["stage_order"]
    stage_percent = descriptor["stage_percent"]

    def callback(stage: str, message: str) -> None:
        with JOB_LOCK:
            # A stale callback from a superseded job must never clobber a newer one's state.
            if _lab_state.get("job_id") != job_id or _lab_state["status"] != "running":
                return
            _lab_state["stage"] = stage
            _lab_state["stage_index"] = stage_order.index(stage)
            _lab_state["percent"] = stage_percent[stage]
            _lab_state["message"] = message
    return callback


def _run_lab_job(job_id: str, text: str, evaluation_id: str = "emotion.core") -> None:
    callback = _make_progress_callback(job_id, evaluation_id)
    descriptor = _lab_descriptor(evaluation_id)
    try:
        if evaluation_id == "emotion.core":
            result = run_custom_lab(job_id, text, callback)
        else:
            result = run_custom_lab(job_id, text, callback, evaluation_id=evaluation_id)
        with JOB_LOCK:
            if _lab_state.get("job_id") != job_id:
                return
            _lab_state.update(
                status="complete", completed_at=_now_iso(), result=result,
                stage="complete", stage_index=len(descriptor["stage_order"]) - 1, percent=100,
                message=descriptor["stages"][-1]["label"],
            )
    except Exception:  # noqa: BLE001 -- orchestration failure; never let it kill the thread silently
        logger.exception("Live Red-Team Lab run failed for job_id=%s", job_id)
        with JOB_LOCK:
            if _lab_state.get("job_id") != job_id:
                return
            _lab_state.update(
                status="failed", completed_at=_now_iso(),
                error="The Red-Team Lab test failed. Please try again.",
            )
