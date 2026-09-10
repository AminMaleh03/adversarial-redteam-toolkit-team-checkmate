"""Root orchestration entry point for Team Checkmate.

    python run_all.py --mode full   [--run-name NAME]
    python run_all.py --mode demo   [--run-name NAME]

Wires together the already-implemented components -- baseline/attack generation,
the V1/V2 endpoints, the runner, analysis and report -- into one command. It owns
process lifecycle (starting/stopping uvicorn) and step sequencing only. It does
not reimplement attack generation, request sending, scoring, or rendering; those
stay in their owning modules (see AGENTS.md).

``run_experiment()`` is the reusable entry point: callable from Python, no
interactive prompts, project-relative paths only, returns a structured result.
A future deployment UI can call it directly instead of shelling out to this CLI.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import shutil
import subprocess
import sys
import time
import unicodedata
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from analysis import analyze as analysis_mod  # noqa: E402
from attacks import library as attack_library  # noqa: E402
from baseline.load import load_baseline  # noqa: E402
from contract import AttackCase, RunResult  # noqa: E402
from report import generate as report_mod  # noqa: E402
from runner import run as runner_mod  # noqa: E402

RESULTS_ROOT = ROOT / "results"
# Stable, project-relative location for the canonical verified full-benchmark report bundle
# (provenance recorded in HANDOFF.md). Demo reports link to a copy of this, never to a
# transient results/<run>/ path or an absolute filesystem path.
VERIFIED_FULL_REPORT_DIR = ROOT / "artifacts" / "verified_full_report"

ENDPOINT_SPECS = {
    "v1": {"app": "endpoint.v1:app", "port": 8000},
    "v2": {"app": "endpoint.v2:app", "port": 8001},
}

def _emit_progress(callback, stage: str, message: str) -> None:
    """Report a real orchestration transition to an optional caller-supplied callback.

    Never used to manufacture progress that hasn't actually happened yet -- see the call
    sites in run_experiment()/run_analysis_and_report() for what stage means what.
    """
    if callback:
        callback(stage, message)


READY_TIMEOUT_S = 180.0
READY_POLL_S = 1.0
HEALTH_CHECK_TIMEOUT_S = 2.0

# Demo mode sends every standalone attack plus every derived attack for this many
# baselines. Computed from the real suite at run time (see compute_demo_attack_limit),
# never a hardcoded case count, so it tracks whatever attacks/ actually builds.
DEMO_BASELINE_COVERAGE = 2

# Excluded from DEMO MODE ONLY (--skip, not a suite change): this case sits right at the
# 10-second request deadline and has been observed to land as either a slow-but-completed
# response or a genuine timeout depending on machine load, which can make a live demo look
# like it found a new V2 regression purely from timing noise. The attack itself, its
# definition, its scoring, and its presence in the full suite are all untouched -- it is
# still built, still registered in the manifest, and still sent in --mode full.
DEMO_EXCLUDED_ATTACK_IDS = ("malformed.oversized_10mb",)

FAILURE_MODE_PRIORITY = (
    "service_unavailable", "unhandled_5xx", "timeout", "connection_failure",
)
PREVIEW_CHARS = 160


# --------------------------------------------------------------------------------------
# endpoint lifecycle
# --------------------------------------------------------------------------------------


@dataclass
class EndpointHandle:
    version: str
    port: int
    process: subprocess.Popen
    log_path: Path
    _log_handle: object

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=20)
        try:
            self._log_handle.close()
        except OSError:
            pass


def _wait_ready(handle: EndpointHandle, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        if handle.process.poll() is not None:
            tail = ""
            try:
                tail = handle.log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            except OSError:
                pass
            raise RuntimeError(
                f"{handle.version} endpoint process exited before becoming ready "
                f"(exit code {handle.process.returncode}). Log tail:\n{tail}"
            )
        try:
            resp = httpx.get(handle.url + "/health", timeout=HEALTH_CHECK_TIMEOUT_S)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(READY_POLL_S)
    raise RuntimeError(
        f"{handle.version} endpoint did not answer /health within {timeout}s ({last_error})"
    )


def start_endpoint(version: str, out_dir: Path) -> EndpointHandle:
    """Start one uvicorn endpoint (no --reload) and block until /health answers."""
    spec = ENDPOINT_SPECS[version]
    log_path = out_dir / f"{version}_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", spec["app"],
         "--host", "127.0.0.1", "--port", str(spec["port"])],
        cwd=str(ROOT), stdout=log_handle, stderr=subprocess.STDOUT,
    )
    handle = EndpointHandle(version=version, port=spec["port"], process=process,
                            log_path=log_path, _log_handle=log_handle)
    try:
        _wait_ready(handle, READY_TIMEOUT_S)
    except Exception:
        handle.stop()
        raise
    return handle


# --------------------------------------------------------------------------------------
# suite construction (shared with the runner's own logic -- read-only reuse for demo
# sizing and for recovering attack text that RunResult does not persist)
# --------------------------------------------------------------------------------------


def build_full_suite(baselines) -> list[AttackCase]:
    from endpoint.model import MAX_SEQUENCE_LENGTH, tokenizer

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    return attack_library.build_suite(
        list(baselines), token_counter=count_tokens, max_tokens=int(MAX_SEQUENCE_LENGTH)
    )


def compute_demo_attack_limit(baselines, attacks: list[AttackCase]) -> int:
    """Every standalone attack plus every derived attack for the first N baselines.

    Computed from the actual built suite (send order: standalone first, then derived
    per baseline in baseline order -- see attacks/library.py), so the curated demo set
    always covers the categories most likely to show a real failure and a real flip
    without hardcoding a case count that could drift out of sync with attacks/.
    """
    covered_ids = {b.baseline_id for b in baselines[:DEMO_BASELINE_COVERAGE]}
    limit = 0
    for case in attacks:
        if case.baseline_id is None or case.baseline_id in covered_ids:
            limit += 1
    return limit


# --------------------------------------------------------------------------------------
# running the suite against one endpoint (delegates to runner.run; no logic duplicated)
# --------------------------------------------------------------------------------------


def run_suite(version: str, target: str, out_dir: Path, *,
             attack_limit: Optional[int], skip: Sequence[str] = ()) -> int:
    argv = ["--target", target, "--version", version, "--out", str(out_dir)]
    if attack_limit is not None:
        argv += ["--limit", str(attack_limit)]
    for attack_id in skip:
        argv += ["--skip", attack_id]
    exit_code = runner_mod.main(argv)
    if exit_code == 2:
        # Preflight failure: no cases were sent and no new artifacts were written.
        raise RuntimeError(
            f"{version} endpoint failed its preflight health check; no requests were sent. "
            f"See {out_dir} for any preserved prior artifacts."
        )
    if exit_code not in (0, 1):
        raise RuntimeError(f"runner for {version} exited unexpectedly with code {exit_code}")
    return exit_code  # 0 completed; 1 = endpoint died mid-suite, preserved as recorded


# --------------------------------------------------------------------------------------
# demo evidence: featured failure + featured prediction flip, built only from real data
# --------------------------------------------------------------------------------------


def _run_outcome(result: Optional[RunResult]) -> Optional[dict]:
    if result is None:
        return None
    status = result.status_code
    if status is not None and 500 <= status < 600:
        outcome = "Unhandled server error"
    elif status is not None and 400 <= status < 500:
        outcome = "Rejected safely"
    elif status is not None and 200 <= status < 300:
        outcome = "Accepted"
    elif result.latency_band == "timeout":
        outcome = "No response (request timeout)"
    elif status is None:
        outcome = "No response (connection/transport failure)"
    else:
        outcome = f"HTTP {status}"
    return {
        "status_code": status,
        "outcome": outcome,
        "error": result.error,
        "latency_ms": result.latency_ms,
        "latency_band": result.latency_band,
        "endpoint_alive_after": result.endpoint_alive_after,
    }


def _payload_preview(case: Optional[AttackCase]) -> tuple[str, Optional[int]]:
    if case is None:
        return "", None
    if case.is_raw:
        body = case.raw_body if case.raw_body is not None else b""
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        size = len(raw)
        text = raw.decode("utf-8", errors="replace")
    else:
        text = case.attacked_text if case.attacked_text is not None else (case.original_text or "")
        size = len(text.encode("utf-8"))
    preview = text[:PREVIEW_CHARS]
    if len(text) > PREVIEW_CHARS:
        preview += f"... [truncated, {size:,} bytes total]"
    return preview, size


def describe_modification(original: Optional[str], attacked: Optional[str]) -> str:
    """Human-readable description of what changed, with Unicode names for single-char swaps."""
    if original is None or attacked is None:
        return "text modified (original not available for comparison)"
    if original == attacked:
        return "no visible character difference detected"
    matcher = difflib.SequenceMatcher(a=original, b=attacked, autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        orig_seg, new_seg = original[i1:i2], attacked[j1:j2]
        if tag == "replace" and len(orig_seg) == 1 and len(new_seg) == 1:
            oc, nc = orig_seg, new_seg
            parts.append(
                f"position {i1}: '{oc}' (U+{ord(oc):04X} {unicodedata.name(oc, 'UNKNOWN')}) "
                f"-> '{nc}' (U+{ord(nc):04X} {unicodedata.name(nc, 'UNKNOWN')})"
            )
        elif tag == "replace":
            parts.append(f"position {i1}: {orig_seg!r} -> {new_seg!r}")
        elif tag == "insert":
            parts.append(f"position {i1}: inserted {new_seg!r}")
        elif tag == "delete":
            parts.append(f"position {i1}: deleted {orig_seg!r}")
    if not parts:
        return "no visible character difference detected"
    shown = parts[:3]
    suffix = f" (+{len(parts) - 3} more)" if len(parts) > 3 else ""
    return "; ".join(shown) + suffix


def highlight_diff_html(original: Optional[str], attacked: Optional[str]) -> tuple[str, str]:
    """Pre-escaped HTML for both strings, with the differing spans wrapped in <mark>.

    Escaping happens once, here, in Python -- callers embed the two returned strings as
    trusted HTML (the report template via Jinja's `safe` filter; web/lab.py's Live Red-Team
    Lab embeds them directly into its JSON response under clearly-named fields), so this
    function is what makes that safe. `html.escape` is unconditionally safe for arbitrary
    input, so this is fine both for our own generated attack text (deterministic
    transformations of committed baseline sentences) and for text derived from live,
    judge-supplied Lab input (System V5.4) -- the function makes no assumption about
    provenance either way.
    """
    if original is None or attacked is None:
        return html.escape(original or ""), html.escape(attacked or "")
    if original == attacked:
        escaped = html.escape(original)
        return escaped, escaped
    matcher = difflib.SequenceMatcher(a=original, b=attacked, autojunk=False)
    orig_parts: list[str] = []
    attacked_parts: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        orig_seg, new_seg = original[i1:i2], attacked[j1:j2]
        if tag == "equal":
            orig_parts.append(html.escape(orig_seg))
            attacked_parts.append(html.escape(new_seg))
            continue
        if orig_seg:
            orig_parts.append(f'<mark class="demo-mark">{html.escape(orig_seg)}</mark>')
        if new_seg:
            attacked_parts.append(f'<mark class="demo-mark">{html.escape(new_seg)}</mark>')
    return "".join(orig_parts), "".join(attacked_parts)


def _select_featured_failure(analysis: dict):
    """Strongest legitimate V1 failure, ranked unavailability > 5xx > timeout > connection.

    Returns (failure_mode, finding_entry, attack_id) or (None, None, None). Never picks
    service_unavailable unless a finding group with that failure_mode actually exists --
    that only happens when a post-request health check actually failed.
    """
    findings = analysis["summary_v1"]["findings"]
    for mode in FAILURE_MODE_PRIORITY:
        candidates = [e for e in findings if e["failure_mode"] == mode]
        if not candidates:
            continue

        def sort_key(entry):
            oversized = any("oversized" in aid for aid in entry["finding"]["evidence"])
            return (oversized, entry["finding"]["severity_score"])

        candidates.sort(key=sort_key, reverse=True)
        chosen = candidates[0]
        evidence = chosen["finding"]["evidence"]
        oversized_ids = sorted(aid for aid in evidence if "oversized" in aid)
        attack_id = oversized_ids[0] if oversized_ids else sorted(evidence)[0]
        return mode, chosen, attack_id
    return None, None, None


def build_featured_failure(mode, chosen, attack_id, attack_index, v1_attacks, v2_attacks):
    if attack_id is None:
        return None
    case = attack_index.get(attack_id)
    v1_result = v1_attacks.get(attack_id)
    v2_result = v2_attacks.get(attack_id)
    preview, size_bytes = _payload_preview(case)
    category = chosen["finding"]["category"]
    subfamily = chosen["subfamily"]

    if mode == "unhandled_5xx" and any("oversized" in e for e in chosen["finding"]["evidence"]):
        remediation = (
            "Reject requests above a defined body/input size limit before expensive model "
            "inference or downstream processing begins."
        )
    else:
        remediation = analysis_mod.REMEDIATIONS.get(mode, chosen["finding"]["remediation"])

    if mode == "service_unavailable":
        interpretation = (
            "The post-request health check failed: this is observed service unavailability, "
            "the strongest evidence of unavailability recorded in this run. It is not, by "
            "itself, confirmation that the underlying process terminated."
        )
    elif mode == "unhandled_5xx":
        alive = bool(v1_result and v1_result.endpoint_alive_after)
        alive_note = "the service remained available afterward" if alive else \
            "availability afterward was not confirmed by this evidence"
        interpretation = (
            f"The endpoint returned an unhandled 5xx response, and {alive_note}. This is an "
            "unhandled server error, not a process crash."
        )
    elif mode == "timeout":
        interpretation = (
            "No response was returned within the 10 second request deadline. The recorded "
            "error is client-side and does not identify which server-side stage was reached."
        )
    else:
        interpretation = analysis_mod.FAILURE_MODE_DETAIL.get(mode, "")

    return {
        "attack_id": attack_id,
        "category": category,
        "subfamily": subfamily,
        "failure_mode": mode,
        "failure_label": analysis_mod.FAILURE_MODE_TITLES.get(mode, mode),
        "input_description": f"{category}/{subfamily}",
        "payload_bytes": size_bytes,
        "preview": preview,
        "v1": _run_outcome(v1_result),
        "v2": _run_outcome(v2_result),
        "technical_interpretation": interpretation,
        "remediation": remediation,
    }


def _select_featured_flip(analysis: dict):
    """Prefer a visually subtle homoglyph flip; else the largest confidence swing."""
    entries = [e for e in analysis["summary_v1"]["findings"] if e["failure_mode"] == "prediction_flip"]
    if not entries:
        return None
    per_flip = {e["attack_id"]: e for e in analysis["summary_v1"]["drift"]["confidence_change"]["per_flip"]}

    def entry_priority(entry):
        is_homoglyph = entry["subfamily"].startswith("homoglyph")
        deltas = [abs(per_flip[aid]["delta"]) for aid in entry["finding"]["evidence"] if aid in per_flip]
        return (is_homoglyph, max(deltas) if deltas else 0.0)

    entries.sort(key=entry_priority, reverse=True)
    chosen_group = entries[0]
    candidate_ids = [aid for aid in chosen_group["finding"]["evidence"] if aid in per_flip]
    if not candidate_ids:
        return None
    attack_id = max(candidate_ids, key=lambda aid: abs(per_flip[aid]["delta"]))
    return attack_id, chosen_group, per_flip[attack_id]


def build_featured_flip(selection, attack_index, v1_attacks, v2_attacks, v1_baselines):
    if selection is None:
        return None
    attack_id, chosen_group, flip_entry = selection
    case = attack_index.get(attack_id)
    if case is None:
        return None
    v1_result = v1_attacks.get(attack_id)
    v2_result = v2_attacks.get(attack_id)
    baseline_result = v1_baselines.get(case.baseline_id) if case.baseline_id else None
    original_html, attacked_html = highlight_diff_html(case.original_text, case.attacked_text)
    return {
        "attack_id": attack_id,
        "baseline_id": case.baseline_id,
        "category": chosen_group["finding"]["category"],
        "subfamily": chosen_group["subfamily"],
        "validity_tiers": chosen_group["validity_tiers"],
        "original_text": case.original_text,
        "attacked_text": case.attacked_text,
        "original_html": original_html,
        "attacked_html": attacked_html,
        "modification": describe_modification(case.original_text, case.attacked_text),
        "original_label": baseline_result.label if baseline_result else None,
        "original_confidence": flip_entry["clean_confidence"],
        "attacked_label": v1_result.label if v1_result else None,
        "attacked_confidence": flip_entry["attacked_confidence"],
        "confidence_change": flip_entry["delta"],
        "v1": _run_outcome(v1_result),
        "v2": _run_outcome(v2_result),
        "v2_still_flipped": bool(
            v2_result and baseline_result and v2_result.label != baseline_result.label
        ),
        "remediation": (
            "This is a model-level robustness gap, not an endpoint defect. V2's application-layer "
            "defenses (length limit, strict types, exception handling, Unicode normalization) do not "
            "reach it -- NFKC normalization does not fold cross-script homoglyphs or fix typo "
            "sensitivity. Closing it needs adversarial/perturbation-aware evaluation, training-data "
            "augmentation with this perturbation family, or robustness fine-tuning, not endpoint-level "
            "exception handling."
        ),
    }


def build_demo_evidence(run_dir: Path, analysis: dict, attack_index: dict) -> dict:
    v1_results = analysis_mod.load_results(run_dir / "v1" / "results_v1.jsonl")
    v2_results = analysis_mod.load_results(run_dir / "v2" / "results_v2.jsonl")
    v1_attacks = {r.attack_id: r for r in v1_results if r.case_type == "attack"}
    v2_attacks = {r.attack_id: r for r in v2_results if r.case_type == "attack"}
    v1_baselines = {r.baseline_id: r for r in v1_results if r.case_type == "baseline"}

    mode, chosen, attack_id = _select_featured_failure(analysis)
    literal_crash_available = mode == "service_unavailable"
    failure = build_featured_failure(mode, chosen, attack_id, attack_index, v1_attacks, v2_attacks)

    flip_selection = _select_featured_flip(analysis)
    flip = build_featured_flip(flip_selection, attack_index, v1_attacks, v2_attacks, v1_baselines)

    # Kept separate from `notes`: this is an expected, calm statement of fact every run
    # (not a problem to warn about), so the template renders it as a small caption near the
    # featured failure card rather than a prominent warning box. `notes` stays reserved for
    # genuine anomalies (no example found) that should stay visually prominent.
    crash_status_note = None
    if not literal_crash_available:
        crash_status_note = (
            "No request in this run caused observed service unavailability (a failed post-request "
            "health check). The featured failure below is the strongest legitimate example found in "
            "this run's data and is reported accurately as an unhandled server error, not a process "
            "crash."
        )

    notes = []
    if failure is None:
        notes.append(
            "No unhandled server error, timeout, connection failure, or service-unavailability "
            "finding was found in this run."
        )
    if flip is None:
        notes.append(
            "No qualifying prediction flip (clean confidence >= 0.6, top label changed) was found "
            "in this run."
        )

    return {
        "literal_crash_case_available": literal_crash_available,
        "featured_failure": failure,
        "featured_prediction_flip": flip,
        "crash_status_note": crash_status_note,
        "notes": notes,
    }


# --------------------------------------------------------------------------------------
# analysis + report
# --------------------------------------------------------------------------------------


def run_analysis_and_report(run_dir: Path, attack_index: dict, *, html_only: bool, mode: str,
                            progress_callback=None) -> dict:
    _emit_progress(progress_callback, "analyzing", "Comparing V1 and V2 results")
    analysis = analysis_mod.run_analysis_from_dir(str(run_dir))
    demo_evidence = build_demo_evidence(run_dir, analysis, attack_index)

    report_payload = {
        "schema_version": analysis["schema_version"],
        "summary_v1": analysis["summary_v1"],
        "summary_v2": analysis["summary_v2"],
        "comparison": analysis["comparison"],
        "demo_evidence": demo_evidence,
    }
    # Demo mode links "View Detailed Report" to a copy of the stable verified full-benchmark
    # artifact (see VERIFIED_FULL_REPORT_DIR), never to a transient/absolute path. Only the
    # href needs to be known before rendering; the actual copy happens after generate_report
    # creates report_dir (which must not already exist -- see report.generate.generate_report).
    detailed_available = False
    if mode == "demo":
        detailed_available = (VERIFIED_FULL_REPORT_DIR / "report.html").exists()
        report_payload["detailed_report"] = {
            "available": detailed_available,
            "relative_href": "detailed/report.html" if detailed_available else "",
        }

    (run_dir / "demo_evidence.json").write_text(
        json.dumps(demo_evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    raw = json.dumps(report_payload, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")

    # Full mode gets the complete technical/audit report; demo mode gets a short,
    # single-page judge-facing report (see report/demo_template.html). Both read the
    # same analysis JSON -- only presentation differs, per report.generate.render_html.
    _emit_progress(progress_callback, "generating_results", "Generating the report")
    report_dir = run_dir / "report"
    pdf_ok = True
    try:
        report_mod.generate_report(raw, report_dir, html_only=html_only, mode=mode)
    except RuntimeError as exc:
        if html_only:
            raise
        # PDF renderer unavailable on this machine (missing GTK, etc. -- see AGENTS.md).
        # Fall back to HTML-only rather than failing the whole run over presentation.
        pdf_ok = False
        report_mod.generate_report(raw, report_dir, html_only=True, mode=mode)
        print(f"(PDF rendering unavailable, wrote HTML-only report: {exc})", file=sys.stderr)

    if detailed_available:
        shutil.copytree(VERIFIED_FULL_REPORT_DIR, report_dir / "detailed")

    return {"analysis": analysis, "demo_evidence": demo_evidence, "report_dir": report_dir, "pdf_ok": pdf_ok}


# --------------------------------------------------------------------------------------
# summaries
# --------------------------------------------------------------------------------------


def _finding_group_counts(comparison: dict) -> dict:
    if "comparison_withheld_reason" in comparison:
        return {"resolved": None, "remaining": None, "new": None,
                "withheld_reason": comparison["comparison_withheld_reason"]}
    return {
        "resolved": len(comparison["findings_resolved"]),
        "remaining": len(comparison["findings_remaining"]),
        "new": len(comparison["findings_newly_appearing"]),
        "withheld_reason": None,
    }


def print_full_summary(run_name: str, analysis: dict, report_dir: Path, status: str) -> None:
    cov1 = analysis["summary_v1"]["coverage"]
    cov2 = analysis["summary_v2"]["coverage"]
    counts = _finding_group_counts(analysis["comparison"])
    print()
    print("TEAM CHECKMATE -- RUN COMPLETE")
    print()
    print(f"Run: {run_name}")
    print()
    print(f"V1 coverage: {cov1['completed']} / {cov1['planned']}")
    print(f"V2 coverage: {cov2['completed']} / {cov2['planned']}")
    print()
    if counts["withheld_reason"]:
        print(f"Comparison withheld: {counts['withheld_reason']}")
    else:
        print(f"Resolved finding groups: {counts['resolved']}")
        print(f"Remaining finding groups: {counts['remaining']}")
        print(f"Newly demonstrated groups: {counts['new']}")
    print()
    print("Report:")
    print(f"  {report_dir / 'report.html'}")
    if (report_dir / "report.pdf").exists():
        print(f"  {report_dir / 'report.pdf'}")
    print()
    print(f"Status: {status}")


def print_demo_summary(run_name: str, demo_evidence: dict, report_dir: Path) -> None:
    print()
    print("TEAM CHECKMATE -- DEMO COMPLETE")
    print()
    failure = demo_evidence.get("featured_failure")
    print("Featured failure:")
    if failure:
        print(f"  {failure['category']} / {failure['subfamily']}")
        v1 = failure.get("v1") or {}
        v2 = failure.get("v2") or {}
        print(f"  V1: {'HTTP ' + str(v1.get('status_code')) if v1.get('status_code') else 'no response'} "
              f"{v1.get('outcome', '')}")
        if v2:
            print(f"  V2: {'HTTP ' + str(v2.get('status_code')) if v2.get('status_code') else 'no response'} "
                  f"{v2.get('outcome', '')}")
    else:
        print("  none found in this run")
    print()
    flip = demo_evidence.get("featured_prediction_flip")
    print("Featured prediction flip:")
    if flip:
        print(f"  {flip['original_label']} ({flip['original_confidence']:.3f}) -> "
              f"{flip['attacked_label']} ({flip['attacked_confidence']:.3f})")
        print(f"  Attack: {flip['subfamily']}")
    else:
        print("  none found in this run")
    print()
    print(f"Literal crash/unavailability demonstrated: "
          f"{'YES' if demo_evidence.get('literal_crash_case_available') else 'NO'}")
    print()
    print("Report:")
    print(f"  {report_dir / 'report.html'}")
    if (report_dir / "report.pdf").exists():
        print(f"  {report_dir / 'report.pdf'}")


# --------------------------------------------------------------------------------------
# reusable orchestration entry point
# --------------------------------------------------------------------------------------


def run_experiment(mode: str, run_name: Optional[str] = None,
                   results_root: Optional[Path] = None,
                   progress_callback=None) -> dict:
    """Run one full experiment. Callable from Python; no interactive prompts.

    Returns a structured dict describing what happened -- never raises for a
    endpoint-under-test failure (those are preserved data, per AGENTS.md), only for
    orchestration-level problems (endpoint never came up, preflight failed, etc).

    ``progress_callback``, if given, is called as ``callback(stage, message)`` at real
    orchestration transitions (see _emit_progress call sites here and in
    run_analysis_and_report()) -- initializing, starting_v1, attacking_v1, starting_v2,
    attacking_v2, analyzing, generating_results, complete. Optional and additive: every
    existing caller that omits it keeps the exact V3 behavior.
    """
    if mode not in ("full", "demo"):
        raise ValueError(f"unknown mode {mode!r}; expected 'full' or 'demo'")

    results_root = Path(results_root) if results_root is not None else RESULTS_ROOT
    if run_name is None:
        prefix = "demo" if mode == "demo" else "full"
        run_name = f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = results_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    _emit_progress(progress_callback, "initializing", "Loading baselines and building the attack suite")
    baselines = sorted(load_baseline(), key=lambda b: b.baseline_id)
    attacks = build_full_suite(baselines)
    attack_index = {case.attack_id: case for case in attacks}

    attack_limit = compute_demo_attack_limit(baselines, attacks) if mode == "demo" else None
    # Demo-only, selection-level exclusion -- see DEMO_EXCLUDED_ATTACK_IDS. Full mode always
    # gets an empty skip list, so this never touches the full suite or its scoring.
    skip_ids = DEMO_EXCLUDED_ATTACK_IDS if mode == "demo" else ()

    terminations = {}
    for version in ("v1", "v2"):
        out_dir = run_dir / version
        _emit_progress(progress_callback, f"starting_{version}", f"Starting {version.upper()} endpoint")
        handle = start_endpoint(version, run_dir)
        try:
            label = "unhardened" if version == "v1" else "hardened"
            _emit_progress(progress_callback, f"attacking_{version}", f"Attacking the {label} endpoint")
            exit_code = run_suite(version, handle.url, out_dir, attack_limit=attack_limit, skip=skip_ids)
            terminations[version] = exit_code
        finally:
            handle.stop()

    report_result = run_analysis_and_report(run_dir, attack_index, html_only=False, mode=mode,
                                            progress_callback=progress_callback)
    analysis = report_result["analysis"]

    status = "COMPLETE" if all(code == 0 for code in terminations.values()) else "PARTIAL"

    result = {
        "mode": mode,
        "run_name": run_name,
        "run_dir": run_dir,
        "terminations": terminations,
        "status": status,
        "analysis": analysis,
        "demo_evidence": report_result["demo_evidence"],
        "report_dir": report_result["report_dir"],
        "report_html": report_result["report_dir"] / "report.html",
        "report_pdf": (report_result["report_dir"] / "report.pdf"
                       if report_result["pdf_ok"] else None),
        "pdf_generated": report_result["pdf_ok"],
    }

    if mode == "demo":
        print_demo_summary(run_name, report_result["demo_evidence"], report_result["report_dir"])
    else:
        print_full_summary(run_name, analysis, report_result["report_dir"], status)

    _emit_progress(progress_callback, "complete", "Experiment complete")
    return result


# --------------------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_all", description="Run the full Team Checkmate experiment end to end."
    )
    parser.add_argument("--mode", required=True, choices=("full", "demo"))
    parser.add_argument("--run-name", default=None,
                        help="output subdirectory under results/; default is a timestamped name")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the generated report in the default browser "
                             "(CI/Docker/servers/automated tests)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_experiment(mode=args.mode, run_name=args.run_name)
    except RuntimeError as exc:
        print(f"\nrun_all failed: {exc}", file=sys.stderr)
        return 1

    # Browser opening is CLI presentation only -- run_experiment() never does this, so
    # a future Hugging Face app calling run_experiment() directly cannot trigger it.
    if not args.no_open:
        report_html = result["report_html"]
        try:
            opened = webbrowser.open(report_html.resolve().as_uri())
            if not opened:
                print(f"(could not open a browser automatically; report is at {report_html})")
        except webbrowser.Error as exc:
            print(f"(could not open a browser automatically ({exc}); report is at {report_html})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
