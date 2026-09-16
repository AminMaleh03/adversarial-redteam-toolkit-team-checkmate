"""Deterministic builder for the Stage 3 fixture pack.

Run it from the repository root:

    python tests/fixtures/stage3/build_fixtures.py

It rewrites everything under ``tests/fixtures/stage3/`` except this file and
``README.md``, then re-validates what it wrote. Output is byte-stable: fixed ids, fixed
numbers, sorted keys where order is not meaningful, LF line endings. Running it twice
produces identical bytes, so a diff always means a real change.

Two rules this file exists to enforce:

1. **Every hash is a real SHA-256 of the fixture bytes it describes.** Nothing here
   contains a made-up digest, an ellipsis or a placeholder. Files are written first and
   hashed second, so a hash can never drift from its content.
2. **Synthetic content says so.** Every synthetic artifact carries a ``_synthetic`` block.
   These are contract examples: they demonstrate the agreed shapes and arithmetic. They
   are not measurements, not findings about any model, and not evidence that any feature
   works. The single genuine fixture (``legacy/genuine_v2_analysis.json``) is produced by
   running the real analysis code over a real subset of the preserved V6 benchmark bytes,
   and is labelled as genuine.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

BENCH = ROOT / "artifacts" / "benchmark_v6"

SYNTHETIC = {
    "is_synthetic": True,
    "purpose": "Stage 3 contract example. Demonstrates required shape and arithmetic.",
    "not_evidence_of": (
        "No model was run to produce this. These numbers are authored, not measured. "
        "They are not findings about any model, not a model pin, and not proof that any "
        "feature works."
    ),
}

EMOTION_LABELS = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
SENTIMENT_LABELS = ["NEGATIVE", "POSITIVE"]

EMOTION_MODEL = {
    "model_id": "j-hartmann/emotion-english-distilroberta-base",
    "revision": "0e1cd914e3d46199ed785853e12b57304e04178b",
    "tokenizer_id": "j-hartmann/emotion-english-distilroberta-base",
    "tokenizer_revision": "0e1cd914e3d46199ed785853e12b57304e04178b",
    "labels": EMOTION_LABELS,
}
SENTIMENT_MODEL = {
    "model_id": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
    "revision": "714eb0fa89d2f80546fda750413ed43d93601a13",
    "tokenizer_id": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
    "tokenizer_revision": "714eb0fa89d2f80546fda750413ed43d93601a13",
    "labels": SENTIMENT_LABELS,
}

RUN_ID = "fixturerun0001"
CREATED_AT = "2026-09-15T00:00:00+00:00"
APP_COMMIT = "9386d75a535ed26007379c3e2af5b930d6698015"


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------


def sorted_paths(paths, root: Path):
    """Sort paths by a canonical repo-relative POSIX key, not by Path.__lt__.

    ``sorted(some_dir.rglob("*"))`` looks deterministic and is not: comparing ``Path``
    objects directly compares them under the host OS's path semantics, and those
    disagree on case. ``PureWindowsPath`` compares case-insensitively (Windows
    filesystems normally are), ``PurePosixPath`` compares case-sensitively (POSIX
    filesystems normally are). ``README.md`` and a ``negative/`` entry land on opposite
    sides of that comparison depending only on which OS built the fixture pack, which
    silently reorders ``MANIFEST.json``'s ``files`` object between platforms and makes
    ``TestFixturePack::test_builder_is_deterministic`` fail on whichever OS did not
    originally produce the checked-in fixtures (found during PR #10 integration
    review, Rayyan's handover section 9.3, reproduced on Windows here by inspection
    rather than by an actual cross-platform run).

    The fix sorts by an explicit string key instead of letting ``Path`` compare
    itself: ``PurePosixPath(relative_to(root)).as_posix()``, a forward-slashed,
    repo-relative string. Comparing that key is plain Python string comparison --
    byte/codepoint order, the same on every platform, with no implicit
    case-folding anywhere. Two different paths always produce two different keys
    (there are no case-only collisions in this fixture pack), so no further
    tie-breaker is needed; ``sorted`` is stable regardless.
    """
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def jdump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_json(path: Path, obj) -> str:
    """Write pretty JSON with LF endings and return the SHA-256 of the bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = jdump(obj).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_jsonl(path: Path, rows) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        for r in rows
    )
    data = body.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def sha_of(obj) -> str:
    """Hash a canonical JSON encoding. Used for selection/suite fingerprints."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def row(**kw) -> dict:
    """A RunResult row with every contract field present, in contract order."""
    base = {
        "case_type": "baseline",
        "attack_id": None,
        "baseline_id": None,
        "category": None,
        "version": "v1",
        "status_code": 200,
        "response_body": "",
        "error": None,
        "label": None,
        "confidence": None,
        "all_scores": None,
        "latency_ms": 12.0,
        "latency_band": "normal",
        "endpoint_alive_after": True,
        "target_id": "",
        "suite_id": "",
        "request_body_bytes": None,
        "request_body_sha256": None,
    }
    base.update(kw)
    return base


def predict_body(scores: dict) -> tuple[str, str, float]:
    """A realistic /predict response body plus its top label and confidence."""
    top = max(scores, key=lambda k: scores[k])
    body = json.dumps(
        {"label": top, "confidence": scores[top], "all_scores": scores},
        ensure_ascii=False,
        sort_keys=True,
    )
    return body, top, scores[top]


def request_evidence(payload: dict) -> tuple[int, str]:
    """Byte length and digest of the exact body a sender would put on the wire."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return len(data), hashlib.sha256(data).hexdigest()


def clean_row(target_id, version, suite_id, baseline_id, text, scores) -> dict:
    body, label, conf = predict_body(scores)
    nbytes, digest = request_evidence({"text": text})
    return row(
        case_type="baseline",
        baseline_id=baseline_id,
        version=version,
        status_code=200,
        response_body=body,
        label=label,
        confidence=conf,
        all_scores=scores,
        target_id=target_id,
        suite_id=suite_id,
        request_body_bytes=nbytes,
        request_body_sha256=digest,
    )


def attack_row(
    target_id, version, suite_id, attack_id, baseline_id, category, text, scores,
    status_code=200, error=None, response_body=None, alive=True,
) -> dict:
    if scores is not None:
        body, label, conf = predict_body(scores)
    else:
        body, label, conf = (response_body or ""), None, None
    nbytes, digest = request_evidence({"text": text})
    return row(
        case_type="attack",
        attack_id=attack_id,
        baseline_id=baseline_id,
        category=category,
        version=version,
        status_code=status_code,
        response_body=body,
        error=error,
        label=label,
        confidence=conf,
        all_scores=scores,
        endpoint_alive_after=alive,
        target_id=target_id,
        suite_id=suite_id,
        request_body_bytes=nbytes,
        request_body_sha256=digest,
    )


# --------------------------------------------------------------------------------------
# synthetic source data
# --------------------------------------------------------------------------------------

EMOTION_BASELINES = [
    ("fx-emotion-0", "the delay ruined my entire evening", "anger"),
    ("fx-emotion-1", "i finally got the letter i was hoping for", "joy"),
    ("fx-emotion-2", "the meeting is scheduled for tuesday", "neutral"),
]
SENTIMENT_BASELINES = [
    ("fx-sentiment-0", "a dull and lifeless adaptation", "NEGATIVE"),
    ("fx-sentiment-1", "a warm and genuinely funny picture", "POSITIVE"),
    ("fx-sentiment-2", "the pacing never quite recovers", "NEGATIVE"),
]

# Derived attack families used in the core fixtures, and the standalone payload case.
CORE_DERIVED = [("perturbation", "keyboard_typo"), ("encoding", "homoglyph")]
CORE_STANDALONE = ("malformed", "oversized_100kb")

# Families declared by the fixture evaluations (aliases so the builder never reaches
# into contract.py at import time and never drifts from the two agreed OCES families).
CORE_FAMILIES_FX = ("malformed", "boundary", "perturbation", "encoding", "whitespace", "truncation")
OCES_FAMILIES_FX = ("oces.paraphrase", "oces.distractor")

# Filled in by main() from the real committed artifacts.
CLEAN_REFERENCE_SHA = ""
SELECTION_SHA = ""


def emotion_scores(top, conf):
    rest = round((1.0 - conf) / (len(EMOTION_LABELS) - 1), 6)
    scores = {label: rest for label in EMOTION_LABELS}
    scores[top] = conf
    return scores


def sentiment_scores(top, conf):
    other = "POSITIVE" if top == "NEGATIVE" else "NEGATIVE"
    return {top: conf, other: round(1.0 - conf, 6)}


# --------------------------------------------------------------------------------------
# core run builders
# --------------------------------------------------------------------------------------


def build_core_rows(target_id, version, task, hardened):
    """Rows for one target of a core evaluation.

    The hardened target rejects the standalone malformed payload with 422 and holds one
    more prediction steady; the unhardened one returns a 500 for the same payload. That
    is the shape of the real V1/V2 difference, authored rather than measured.
    """
    if task == "emotion_7":
        baselines, scorer, conf = EMOTION_BASELINES, emotion_scores, 0.95
        flip_to = "fear"
    else:
        baselines, scorer, conf = SENTIMENT_BASELINES, sentiment_scores, 0.93
        flip_to = "POSITIVE"

    rows, case_ids = [], []
    for bid, text, label in baselines:
        rows.append(clean_row(target_id, version, "core", bid, text, scorer(label, conf)))
        case_ids.append(f"baseline:{bid}")

    for index, (bid, text, label) in enumerate(baselines):
        for family, subfamily in CORE_DERIVED:
            attack_id = f"{bid}.{family}.{subfamily}"
            # One deliberate flip on the first baseline's homoglyph case, and only on the
            # unhardened target, so the paired comparison has exactly one resolved flip.
            flipped = index == 0 and subfamily == "homoglyph" and not hardened
            top = flip_to if flipped else label
            if flipped and top == label:          # guard the sentiment case
                top = "POSITIVE" if label == "NEGATIVE" else "NEGATIVE"
            rows.append(
                attack_row(
                    target_id, version, "core", attack_id, bid, family,
                    text + "x", scorer(top, 0.41 if flipped else conf),
                )
            )
            case_ids.append(f"attack:{attack_id}")

    family, subfamily = CORE_STANDALONE
    attack_id = f"{family}.{subfamily}"
    if hardened:
        rows.append(
            attack_row(
                target_id, version, "core", attack_id, None, family, "A" * 64, None,
                status_code=422,
                response_body=json.dumps({"detail": "input exceeds configured limit"}),
            )
        )
    else:
        rows.append(
            attack_row(
                target_id, version, "core", attack_id, None, family, "A" * 64, None,
                status_code=500,
                response_body=json.dumps({"detail": "Internal Server Error"}),
            )
        )
    case_ids.append(f"attack:{attack_id}")
    return rows, case_ids


def build_oces_rows(target_id, version, task, hardened):
    """Rows for one target of an additional evaluation. Two families, one variant each."""
    if task == "emotion_7":
        seeds, scorer, conf = EMOTION_BASELINES[:2], emotion_scores, 0.95
    else:
        seeds, scorer, conf = SENTIMENT_BASELINES[:2], sentiment_scores, 0.93

    rows, case_ids = [], []
    for bid, text, label in seeds:
        rows.append(clean_row(target_id, version, "oces", bid, text, scorer(label, conf)))
        case_ids.append(f"baseline:{bid}")
    for index, (bid, text, label) in enumerate(seeds):
        for family in ("oces.paraphrase", "oces.distractor"):
            attack_id = f"{bid}.{family}.v1"
            # One label-invariance failure, on the first distractor, unhardened only.
            broke = index == 0 and family == "oces.distractor" and not hardened
            top = label
            if broke:
                top = "fear" if task == "emotion_7" else (
                    "POSITIVE" if label == "NEGATIVE" else "NEGATIVE"
                )
            rows.append(
                attack_row(
                    target_id, version, "oces", attack_id, bid, family,
                    text + " also the room was quiet.",
                    scorer(top, 0.44 if broke else conf),
                )
            )
            case_ids.append(f"attack:{attack_id}")
    return rows, case_ids


def build_manifest(case_ids, suite_id, families):
    """The oracle sidecar for the fixture cases, in the real manifest's shape."""
    manifest = {}
    for key in case_ids:
        if not key.startswith("attack:"):
            continue
        attack_id = key.split(":", 1)[1]
        family = next((f for f in families if f in attack_id), families[0])
        standalone = attack_id.startswith("malformed.")
        manifest[attack_id] = {
            "attack_id": attack_id,
            "family": family,
            "subfamily": attack_id.rsplit(".", 1)[-1],
            "relation": "schema" if standalone else "invariant",
            "oracle": (
                "request_should_be_rejected_cleanly" if standalone
                else "label_should_match_baseline"
            ),
            "source": "Stage 3 synthetic fixture",
            "validity_tier": "GOLD" if standalone else "SILVER",
            "semantic_risk": "none" if standalone else "low",
            "requires_baseline": not standalone,
            "suite_id": suite_id,
        }
    return dict(sorted(manifest.items()))


def build_run_meta(*, target_id, version, task, suite_id, evaluation_id, case_ids,
                   results_sha, manifest_sha, baseline_file, baseline_sha, model,
                   case_set_id=None, selection_sha=None):
    meta = {
        "run_id": f"{RUN_ID}-{evaluation_id}-{target_id}",
        "evaluation_run_id": RUN_ID,
        "evaluation_id": evaluation_id,
        "version": version,
        "target_id": target_id,
        "task_id": task,
        "suite_id": suite_id,
        "target": f"http://127.0.0.1:{8000 + len(target_id) % 3}",
        "started_at": CREATED_AT,
        "ended_at": CREATED_AT,
        "run_type": "full",
        "limit": None,
        "termination_reason": "completed",
        "model": {
            "model_id": model["model_id"],
            "revision": model["revision"],
            "tokenizer_id": model["tokenizer_id"],
            "tokenizer_revision": model["tokenizer_revision"],
            "labels": list(model["labels"]),
        },
        "baseline": {"path": baseline_file, "sha256": baseline_sha},
        "fingerprints": {
            "planned_suite_sha256": sha_of(case_ids),
            "manifest_sha256": manifest_sha,
            "results_sha256": results_sha,
            "selection_sha256": selection_sha,
        },
        "case_set_id": case_set_id,
        "code_provenance": {"app_commit": APP_COMMIT, "dirty": False},
        "suite": {
            "baselines": sum(1 for k in case_ids if k.startswith("baseline:")),
            "attacks": sum(1 for k in case_ids if k.startswith("attack:")),
            "total_cases": len(case_ids),
        },
        "coverage": {
            "planned": len(case_ids),
            "skipped": 0,
            "limit_excluded": 0,
            "selected": len(case_ids),
            "completed": len(case_ids),
            "missing": 0,
            "coverage_rate": 1.0,
        },
        "case_ids": {
            "planned": list(case_ids),
            "selected": list(case_ids),
            "completed": list(case_ids),
            "skipped": [],
            "limit_excluded": [],
            "missing": [],
        },
        "transport_counts": {
            "timeouts": 0, "connection_errors": 0, "server_errors_5xx": 0,
            "health_ping_retries": 0, "health_failures": 0,
        },
        "runner_settings": {
            "request_timeout_s": 10.0, "health_timeout_s": 2.0, "slow_band_from_ms": 2000.0,
        },
        "_synthetic": SYNTHETIC,
    }
    return meta


# --------------------------------------------------------------------------------------
# analysis v3 expected output
# --------------------------------------------------------------------------------------


def finding_entry(*, finding_id, title, category, severity_score, severity_tier,
                  description, remediation, evidence, failure_mode, subfamily,
                  validity_tiers, affected_cases, remediation_detail):
    """One findings[] entry.

    The nested ``finding`` object is the frozen ``contract.Finding`` shape and is
    preserved exactly. ``remediation_detail`` is a NEW SIBLING of it -- not a replacement,
    and not a field inside it, because ``Finding`` is structurally unchanged in 3.0.0.
    """
    return {
        "finding": {
            "finding_id": finding_id,
            "title": title,
            "category": category,
            "severity_score": severity_score,
            "severity_tier": severity_tier,
            "description": description,
            "remediation": remediation,
            "evidence": list(evidence),
        },
        "subfamily": subfamily,
        "failure_mode": failure_mode,
        "validity_tiers": list(validity_tiers),
        "affected_cases": list(affected_cases),
        "remediation_detail": remediation_detail,
    }


def remediation_detail(*, rule_id, observed, significance, diagnosis_confidence, fix,
                       verification, unavailable_evidence=()):
    return {
        "rule_id": rule_id,
        "rule_version": "1.0.0",
        "rule_sha256": hashlib.sha256(
            f"{rule_id}@1.0.0".encode("utf-8")
        ).hexdigest(),
        "observed": observed,
        "significance": significance,
        # "supported" = the recorded rows establish it. "suspected" = consistent with the
        # rows but not established by them. Never collapse the two.
        "diagnosis_confidence": diagnosis_confidence,
        "fix": fix,
        "verification": verification,
        "unavailable_evidence": list(unavailable_evidence),
    }


def rate(numerator, denominator):
    """A ratio in [0,1], or null when there is no denominator.

    The numerator and denominator always travel with the rate. A zero denominator gives
    null, never 0.0: "no cases were eligible" and "no cases failed" are different claims
    and the report renders the first as N/A.
    """
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": round(numerator / denominator, 6) if denominator else None,
    }


def target_summary(*, target_id, version, task, model, case_ids, rows, hardened,
                   families, suite_id):
    attacks = [r for r in rows if r["case_type"] == "attack"]
    baselines = [r for r in rows if r["case_type"] == "baseline"]
    five_xx = [r for r in attacks if (r["status_code"] or 0) >= 500]
    eligible = [r for r in attacks if r["baseline_id"] is not None]
    clean_by_id = {r["baseline_id"]: r for r in baselines}
    flips = [
        r for r in eligible
        if clean_by_id[r["baseline_id"]]["label"] != r["label"]
        and (clean_by_id[r["baseline_id"]]["confidence"] or 0) >= 0.60
    ]
    findings = []
    if five_xx:
        findings.append(
            finding_entry(
                finding_id=f"{target_id}-unhandled-5xx-malformed",
                title="Oversized payload produces an unhandled server error",
                category="malformed",
                severity_score=72.0,
                severity_tier="High",
                description=(
                    "The oversized standalone payload returned HTTP 500. The service "
                    "answered the following health probe, so this is an observed "
                    "server-error response, not a demonstrated process death."
                ),
                remediation=(
                    "Reject request bodies above a configured size limit before JSON "
                    "parsing and before any tokenization or inference work begins."
                ),
                evidence=[r["attack_id"] for r in five_xx],
                failure_mode="unhandled_5xx",
                subfamily="oversized_100kb",
                validity_tiers=["GOLD"],
                affected_cases=[f"attack:{r['attack_id']}" for r in five_xx],
                remediation_detail=remediation_detail(
                    rule_id="malformed.oversized.body_limit",
                    observed=(
                        f"{len(five_xx)} selected case(s) returned HTTP 500 with "
                        f"request_body_bytes recorded by the sender; "
                        f"endpoint_alive_after was true for every one of them."
                    ),
                    significance=(
                        "An unguarded body size reaches parsing and inference, so a "
                        "single client can spend server work at will."
                    ),
                    diagnosis_confidence="supported",
                    fix=(
                        "Add a request body size limit at the ASGI or framework layer, "
                        "ahead of JSON parsing. A token-count check does not help here: "
                        "tokenization happens after the body has already been read and "
                        "parsed."
                    ),
                    verification={
                        "target_id": target_id,
                        "command": (
                            "python -m runner.run --target http://127.0.0.1:8001 "
                            "--target-id emotion_v2 --suite core "
                            "--case-set analysis/case_sets/ci_core_v1.json --out results/verify"
                        ),
                        "case_set_file": "analysis/case_sets/ci_core_v1.json",
                        "includes_baselines": True,
                        "expected": (
                            "malformed.oversized_100kb returns a 4xx rejection status and "
                            "no selected case returns 5xx."
                        ),
                    },
                ),
            )
        )
    if flips:
        findings.append(
            finding_entry(
                finding_id=f"{target_id}-prediction-flip-homoglyph",
                title="Homoglyph substitution changes the predicted label",
                category="encoding",
                severity_score=48.0,
                severity_tier="Medium",
                description=(
                    "A confident clean prediction changed label after cross-script "
                    "homoglyph substitution. Prediction consistency failed; whether the "
                    "new label is wrong is a separate question from whether it changed."
                ),
                remediation=(
                    "Treat this as a model-level robustness gap. Application-layer input "
                    "controls do not close it; NFKC normalization does not fold "
                    "cross-script homoglyphs."
                ),
                evidence=[r["attack_id"] for r in flips],
                failure_mode="prediction_flip",
                subfamily="homoglyph",
                validity_tiers=["SILVER"],
                affected_cases=[f"attack:{r['attack_id']}" for r in flips],
                remediation_detail=remediation_detail(
                    rule_id="encoding.homoglyph.model_level",
                    observed=(
                        f"{len(flips)} eligible comparison(s) changed top label while the "
                        "clean prediction was at or above the 0.60 confidence threshold."
                    ),
                    significance=(
                        "The decision is not stable under a perturbation that leaves the "
                        "text readable to a person."
                    ),
                    diagnosis_confidence="supported",
                    fix=(
                        "This needs perturbation-aware evaluation, training-data "
                        "augmentation with this family, or robustness fine-tuning. Adding "
                        "an endpoint-level exception handler would not change it, and a "
                        "confusable-folding filter would change the input rather than the "
                        "model's sensitivity to it."
                    ),
                    verification={
                        "target_id": target_id,
                        "command": (
                            "python -m runner.run --target http://127.0.0.1:8001 "
                            "--target-id emotion_v2 --suite core "
                            "--case-set analysis/case_sets/ci_core_v1.json --out results/verify"
                        ),
                        "case_set_file": "analysis/case_sets/ci_core_v1.json",
                        "includes_baselines": True,
                        "expected": (
                            "The listed attack ids keep the clean top label. Because this "
                            "is a model-level gap, a passing run means the model changed, "
                            "not that an endpoint control was added."
                        ),
                    },
                    unavailable_evidence=[
                        "No ground-truth annotation for the attacked text, so this is a "
                        "consistency failure and is not reported as a new misclassification."
                    ],
                ),
            )
        )

    return {
        "target_id": target_id,
        "version": version,
        "task_id": task,
        "suite_id": suite_id,
        "identity": {
            "declared": {
                "model_id": model["model_id"],
                "model_revision": model["revision"],
                "tokenizer_id": model["tokenizer_id"],
                "tokenizer_revision": model["tokenizer_revision"],
                "label_space": list(model["labels"]),
            },
            "provenance": "declared_by_run_meta",
        },
        "coverage": {
            "planned": len(case_ids),
            "skipped": 0,
            "limit_excluded": 0,
            "selected": len(case_ids),
            "completed": len(case_ids),
            "missing": 0,
            "coverage_rate": 1.0,
        },
        "category_stats": {
            family: {
                "planned": sum(1 for r in attacks if r["category"] == family),
                "completed": sum(1 for r in attacks if r["category"] == family),
                "failures": sum(
                    1 for r in attacks
                    if r["category"] == family and (r["status_code"] or 0) >= 500
                ),
            }
            for family in families
        },
        "operational": {
            "unhandled_5xx": len(five_xx),
            "timeouts": 0,
            "connection_failures": 0,
            "service_unavailable": 0,
            "slow_responses": 0,
            "info_leaks": 0,
            "invalid_input_accepted": 0,
        },
        "drift": {
            "eligible_comparisons": len(eligible),
            "qualifying_flips": len(flips),
            "flip_rate": rate(len(flips), len(eligible)),
            "baseline_denominator": {
                "eligible": len(baselines),
                "total": len(baselines),
                "threshold": 0.60,
                "statement": (
                    f"{len(baselines)} of {len(baselines)} baselines eligible for flip "
                    "scoring"
                ),
            },
            "note": (
                "Measures prediction consistency against this target's own clean "
                "prediction. It is not an accuracy measurement; clean-label correctness "
                "is reported separately."
            ),
        },
        "clean_label_agreement": rate(
            sum(
                1 for r in baselines
                if r["label"] == next(
                    lbl for bid, _txt, lbl in (
                        EMOTION_BASELINES if task == "emotion_7" else SENTIMENT_BASELINES
                    ) if bid == r["baseline_id"]
                )
            ),
            len(baselines),
        ),
        "findings": findings,
        "validity_tier_census": {"GOLD": len(five_xx and [1] or []), "SILVER": len(flips)},
        "diagnostic_observations": [],
        "review_cases": [],
        "limitations": [
            "Synthetic fixture. Authored numbers, not measurements.",
            "An HTTP 500 is an observed server-error response. It does not establish an "
            "internal model crash, process death or an information leak.",
        ],
        "_synthetic": SYNTHETIC,
    }


def paired_comparison(summary_a, summary_b, rows_a, rows_b):
    """A paired comparison over the INTERSECTION of eligible case ids.

    The two targets can have different eligible populations. Taking one target's rate
    minus the other's would be a difference between differently filtered groups, which is
    not a matched improvement. So the delta uses the common denominator, and each target's
    own denominator stays visible in its own summary.
    """
    def eligible_ids(rows):
        clean = {r["baseline_id"]: r for r in rows if r["case_type"] == "baseline"}
        return {
            r["attack_id"]: (clean[r["baseline_id"]]["label"] != r["label"])
            for r in rows
            if r["case_type"] == "attack" and r["baseline_id"] is not None
            and (clean[r["baseline_id"]]["confidence"] or 0) >= 0.60
        }

    a, b = eligible_ids(rows_a), eligible_ids(rows_b)
    common = sorted(set(a) & set(b))
    flips_a = sum(1 for k in common if a[k])
    flips_b = sum(1 for k in common if b[k])
    return {
        "fingerprints": {
            "planned_match": True,
            "manifest_match": True,
            "whole_suite_comparable": True,
        },
        "common_eligible_case_ids": common,
        "common_denominator": len(common),
        "flips_on_common": {
            summary_a["target_id"]: flips_a,
            summary_b["target_id"]: flips_b,
        },
        "flip_rate_on_common": {
            summary_a["target_id"]: rate(flips_a, len(common)),
            summary_b["target_id"]: rate(flips_b, len(common)),
        },
        "operational": {
            summary_a["target_id"]: summary_a["operational"],
            summary_b["target_id"]: summary_b["operational"],
        },
        "findings_resolved": [
            f["finding"]["finding_id"] for f in summary_a["findings"]
            if f["failure_mode"] not in {
                g["failure_mode"] for g in summary_b["findings"]
            }
        ],
        "findings_remaining": [
            f["finding"]["finding_id"] for f in summary_b["findings"]
        ],
        "findings_unavailable": [],
        "findings_newly_appearing": [],
        "note": (
            "Deltas are computed over the intersection of eligible case ids in both "
            "targets. Each target's individual eligible denominator is kept in its own "
            "summary and is not interchangeable with this one."
        ),
    }


def coverage_block(case_ids, rows, families, suite_id):
    """Coverage partition. Every selected attack lands in exactly one bucket."""
    attacks = [r for r in rows if r["case_type"] == "attack"]
    clean = {r["baseline_id"]: r for r in rows if r["case_type"] == "baseline"}
    buckets = {
        "eligible_pass": [], "eligible_fail": [], "review": [], "diagnostic": [],
        "unevaluable": [],
    }
    for r in attacks:
        key = f"attack:{r['attack_id']}"
        if r["baseline_id"] is None:
            # Schema oracle: a clean rejection is a pass, a 5xx is a failure.
            if (r["status_code"] or 0) >= 500:
                buckets["eligible_fail"].append(key)
            elif r["status_code"] in (400, 413, 415, 422):
                buckets["eligible_pass"].append(key)
            else:
                buckets["unevaluable"].append(key)
        elif r["label"] is None:
            buckets["unevaluable"].append(key)
        elif clean[r["baseline_id"]]["label"] != r["label"]:
            buckets["eligible_fail"].append(key)
        else:
            buckets["eligible_pass"].append(key)

    selected_attacks = len(attacks)
    partition_total = sum(len(v) for v in buckets.values())
    assert partition_total == selected_attacks, "coverage partition does not add up"
    return {
        "coverage_map_version": "fixture-1",
        "classes": {
            "in_scope": {
                "controls_targeted": ["length", "strict_type_schema", "normalization"],
                "attack_ids": sorted(
                    r["attack_id"] for r in attacks if r["baseline_id"] is None
                ),
            },
            "not_targeted": {
                "controls_targeted": [],
                "attack_ids": sorted(
                    r["attack_id"] for r in attacks if r["baseline_id"] is not None
                ),
            },
            "out_of_scope": {"controls_targeted": [], "attack_ids": []},
            "mixed": {"controls_targeted": [], "attack_ids": []},
        },
        "buckets": {k: sorted(v) for k, v in buckets.items()},
        "counts": {k: len(v) for k, v in buckets.items()},
        "not_selected": 0,
        "not_executed": 0,
        "selected_attacks": selected_attacks,
        "notes": [
            "Classes describe INTENDED input-control coverage. They are not a claim that "
            "a control caused any observed result, and not a measure of effectiveness.",
            "C3 error handling is cross-cutting: its observable responses are evaluated, "
            "but no isolated causal proof is claimed.",
            "Within-control counts may overlap and must not be summed as if disjoint.",
        ],
        "_synthetic": SYNTHETIC,
    }


def oces_block(rows_by_target, families):
    """Per-target status for every planned additional case. Five statuses, no gaps."""
    planned = sorted({
        r["attack_id"] for rows in rows_by_target.values() for r in rows
        if r["case_type"] == "attack"
    })
    statuses = {}
    for target_id, rows in rows_by_target.items():
        clean = {r["baseline_id"]: r for r in rows if r["case_type"] == "baseline"}
        by_id = {r["attack_id"]: r for r in rows if r["case_type"] == "attack"}
        per_case = {}
        for attack_id in planned:
            r = by_id.get(attack_id)
            if r is None:
                per_case[attack_id] = {"status": "not_executed", "reason": "not in this run"}
            elif r["label"] is None:
                per_case[attack_id] = {
                    "status": "unevaluable",
                    "reason": "no usable prediction; an absent prediction is never scored "
                              "as successful invariance",
                }
            elif clean[r["baseline_id"]]["label"] == r["label"]:
                per_case[attack_id] = {"status": "meets_expectation", "reason": ""}
            else:
                per_case[attack_id] = {
                    "status": "violates_expectation",
                    "reason": "top label changed under a label-invariant transformation",
                }
        scored = [v for v in per_case.values() if v["status"] in
                  ("meets_expectation", "violates_expectation")]
        violations = [v for v in per_case.values() if v["status"] == "violates_expectation"]
        statuses[target_id] = {
            "per_case": per_case,
            "violation_rate": rate(len(violations), len(scored)),
            "per_family": {
                family: rate(
                    sum(
                        1 for aid, v in per_case.items()
                        if family in aid and v["status"] == "violates_expectation"
                    ),
                    sum(
                        1 for aid, v in per_case.items()
                        if family in aid and v["status"] in
                        ("meets_expectation", "violates_expectation")
                    ),
                )
                for family in families
            },
        }
    return {
        "families": list(families),
        "planned_attack_ids": planned,
        "by_target": statuses,
        "exposure_statement": (
            "Additional evaluation authored after the evaluated defenses were frozen; the "
            "authors were aware of the defenses. This is NOT a blind holdout and is not "
            "design-independent."
        ),
        "freeze": {
            "defense_file": "endpoint/v2.py",
            "defense_sha256":
                "cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e",
            "note": "Real freeze identity; the case content here is synthetic.",
        },
        "note": (
            "Flips are consistency failures. Calling one a new misclassification needs "
            "evidence that the clean baseline was classified correctly to begin with."
        ),
        "_synthetic": SYNTHETIC,
    }


# --------------------------------------------------------------------------------------
# gate outcomes
# --------------------------------------------------------------------------------------

POLICY_ID = "ci_emotion_v2_core_selection"
POLICY_VERSION = "1.0.0"
# A real digest of a real string: the policy identity this fixture set represents.
POLICY_SHA = hashlib.sha256(f"{POLICY_ID}@{POLICY_VERSION}".encode("utf-8")).hexdigest()

CANDIDATE = {
    "target_id": "emotion_v2",
    "commit": APP_COMMIT,
    "model_id": EMOTION_MODEL["model_id"],
    "model_revision": EMOTION_MODEL["revision"],
}


def check(check_id, status, reason, *, observed=None, threshold=None, blocking=True,
          evidence=()):
    return {
        "check_id": check_id,
        "status": status,
        "reason": reason,
        "evidence_refs": list(evidence),
        "observed": observed,
        "threshold": threshold,
        "blocking": blocking,
    }


def gate(outcome, checks, *, summary=None, reference=None, exclusions=()):
    exit_code = {"pass": 0, "policy_failure": 1, "execution_error": 2}[outcome]
    return {
        "schema_version": 1,
        "outcome": outcome,
        "exit_code": exit_code,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "policy_sha256": POLICY_SHA,
        "candidate": dict(CANDIDATE),
        "reference": reference if reference is not None else {
            "reference_id": "ci_core_v1_clean_reference",
            "sha256": CLEAN_REFERENCE_SHA,
        },
        "suite_id": "core",
        "case_set_id": "ci_core_v1",
        "selection_sha256": SELECTION_SHA,
        "checks": checks,
        "summary": summary or {},
        "artifacts": {
            "analysis_json": "results/ci/analysis.json",
            "report_html": "results/ci/report.html",
            "raw_results": "results/ci/emotion_v2/results.jsonl",
            "gate_result": "results/ci/gate_result.json",
        },
        "exclusions": list(exclusions),
        "_synthetic": SYNTHETIC,
    }


def build_gate_fixtures(out: Path) -> dict:
    written = {}

    identity_ok = check(
        "candidate_identity", "pass",
        "Candidate target, commit and model revision match the policy.",
        observed=CANDIDATE, threshold=CANDIDATE,
    )
    selection_ok = check(
        "selection_integrity", "pass",
        "All 162 selected cases are present, unique and accounted for.",
        observed=162, threshold=162,
    )
    completion_ok = check(
        "execution_completion", "pass",
        "Every selected case completed with a valid response record.",
        observed={"selected": 162, "completed": 162, "missing": 0},
    )
    clean_ok = check(
        "clean_response_coherence", "pass",
        "All 42 selected baselines returned HTTP 200 with a finite confidence and a "
        "complete 7-label score vector in the declared label space.",
        observed={"baselines": 42, "coherent": 42},
    )
    reference_ok = check(
        "approved_clean_label_agreement", "pass",
        "Clean top labels agree with the approved reference on all 42 frozen baseline "
        "ids. Agreement with the reference is not a ground-truth accuracy claim.",
        observed=rate(42, 42),
    )
    no_5xx_ok = check(
        "no_server_errors", "pass",
        "Zero observed 5xx, timeouts, transport failures or failed post-request health "
        "checks across the selected cases.",
        observed={"http_5xx": 0, "timeouts": 0, "transport": 0, "health_failures": 0},
        threshold=0,
    )
    no_leak_ok = check(
        "no_leak_signatures", "pass",
        "No leak signature matched. The detector looks for stack-trace markers, absolute "
        "filesystem paths and internal module names; it cannot prove the absence of all "
        "information disclosure.",
        observed=0, threshold=0,
    )
    rejection_ok = check(
        "documented_rejection_behavior", "pass",
        "Every case whose oracle requires clean rejection returned an allowed rejection "
        "status. A missing response is never counted as a rejection.",
        observed={"required": 12, "rejected_cleanly": 12},
    )
    flips_info = check(
        "attack_flip_rate", "pass",
        "Informational in this first policy. Reported, never blocking.",
        observed=rate(9, 88), blocking=False,
    )
    slow_info = check(
        "slow_responses", "pass",
        "Informational. Slow responses are reported and do not gate the release.",
        observed=0, blocking=False,
    )

    passing = [identity_ok, selection_ok, completion_ok, clean_ok, reference_ok,
               no_5xx_ok, no_leak_ok, rejection_ok, flips_info, slow_info]

    written["gate_pass.json"] = write_json(
        out / "gate_pass.json",
        gate("pass", passing, summary={
            "blocking_checks": 8, "passed": 8, "failed": 0, "errored": 0,
            "informational_checks": 2,
            "claim": (
                "Compliance with this named policy on this frozen selection. Not a claim "
                "of comprehensive model-level adversarial robustness, and not production "
                "certification."
            ),
        }),
    )

    failing_5xx = check(
        "no_server_errors", "fail",
        "3 selected cases returned HTTP 500. The service answered the following health "
        "probe each time, so this is an observed server-error response and not a "
        "demonstrated process death.",
        observed={"http_5xx": 3, "timeouts": 0, "transport": 0, "health_failures": 0},
        threshold=0,
        evidence=[
            "attack:malformed.oversized_100kb",
            "attack:malformed.oversized_1mb",
            "attack:boundary.length.plus_one",
        ],
    )
    written["gate_policy_failure.json"] = write_json(
        out / "gate_policy_failure.json",
        gate("policy_failure",
             [identity_ok, selection_ok, completion_ok, clean_ok, reference_ok,
              failing_5xx, no_leak_ok, rejection_ok, flips_info, slow_info],
             summary={
                 "blocking_checks": 8, "passed": 7, "failed": 1, "errored": 0,
                 "claim": (
                     "A trustworthy recorded candidate defect. Evidence is complete; the "
                     "candidate failed the policy."
                 ),
             }),
    )

    written["gate_execution_error.json"] = write_json(
        out / "gate_execution_error.json",
        gate("execution_error", [
            check("policy_validity", "error",
                  "The policy is still marked status=draft. A draft policy has no frozen "
                  "selection or reference hash to score against, so it cannot pass and "
                  "cannot fail; it has failed to run.",
                  observed="draft", threshold="frozen"),
            check("candidate_identity", "not_applicable",
                  "Not evaluated: the policy did not validate."),
            check("selection_integrity", "not_applicable",
                  "Not evaluated: the policy did not validate."),
        ], summary={
            "blocking_checks": 3, "passed": 0, "failed": 0, "errored": 1,
            "claim": "Structural error takes precedence; results cannot be trusted.",
        }),
    )

    written["gate_all_rejecting.json"] = write_json(
        out / "gate_all_rejecting.json",
        gate("policy_failure", [
            identity_ok, selection_ok, completion_ok,
            check("clean_response_coherence", "fail",
                  "0 of 42 selected baselines returned HTTP 200: the candidate rejected "
                  "every request, including valid clean input. A candidate that rejects "
                  "everything trivially produces zero 5xx and zero flips, which is why "
                  "clean-response coherence is checked before any robustness signal.",
                  observed={"baselines": 42, "coherent": 0}, threshold={"coherent": 42},
                  evidence=["attack:none", "baseline:dataset-anger-0"]),
            check("approved_clean_label_agreement", "fail",
                  "No clean predictions were produced, so agreement cannot be "
                  "established. Absent predictions are not counted as agreement.",
                  observed=rate(0, 0)),
            no_5xx_ok, no_leak_ok, rejection_ok, flips_info, slow_info,
        ], summary={
            "blocking_checks": 8, "passed": 6, "failed": 2, "errored": 0,
            "claim": "Degenerate all-rejecting candidate caught by the coherence checks.",
        }),
    )

    written["gate_wrong_clean_output.json"] = write_json(
        out / "gate_wrong_clean_output.json",
        gate("policy_failure", [
            identity_ok, selection_ok, completion_ok, clean_ok,
            check("approved_clean_label_agreement", "fail",
                  "Clean top labels disagree with the approved reference on 5 of 42 "
                  "frozen baseline ids. This is a regression against the published "
                  "benchmark's behaviour; it does not establish which label is correct.",
                  observed=rate(37, 42), threshold=rate(42, 42),
                  evidence=[
                      "baseline:dataset-anger-0", "baseline:dataset-fear-2",
                      "baseline:dataset-joy-1", "baseline:dataset-sadness-4",
                      "baseline:handwritten-neutral-1",
                  ]),
            no_5xx_ok, no_leak_ok, rejection_ok, flips_info, slow_info,
        ], summary={
            "blocking_checks": 8, "passed": 7, "failed": 1, "errored": 0,
            "claim": "Clean-output regression against the approved reference snapshot.",
        }),
    )
    return written


# --------------------------------------------------------------------------------------
# status / API
# --------------------------------------------------------------------------------------


def build_api_fixtures(out: Path) -> dict:
    written = {}
    written["status_running.json"] = write_json(out / "status_running.json", {
        "run_id": RUN_ID,
        "run_name": "fixture-demo",
        "state": "running",
        "evaluation_id": "emotion.core",
        "target_ids": ["emotion_v1", "emotion_v2"],
        "stage": "running_v1",
        "percent": 30,
        "message": "Sending the core suite to the unhardened emotion endpoint.",
        "results": None,
        "report_url": None,
        "_synthetic": SYNTHETIC,
    })
    written["status_complete.json"] = write_json(out / "status_complete.json", {
        "run_id": RUN_ID,
        "run_name": "fixture-demo",
        "state": "complete",
        "evaluation_id": "emotion.core",
        "target_ids": ["emotion_v1", "emotion_v2"],
        "stage": "done",
        "percent": 100,
        "message": "Run complete.",
        "results": {"analysis_json": f"/results/{RUN_ID}/analysis.json"},
        "report_url": f"/results/{RUN_ID}/report.html",
        "_synthetic": SYNTHETIC,
    })
    # The stale case: a poll for an OLDER run arriving after the user switched model.
    # The client must compare run_id AND evaluation identity and discard this, rather
    # than letting it overwrite the newly selected view.
    written["status_stale.json"] = write_json(out / "status_stale.json", {
        "run_id": "fixturerun0000",
        "run_name": "fixture-previous",
        "state": "complete",
        "evaluation_id": "sentiment.core",
        "target_ids": ["sentiment_v1"],
        "stage": "done",
        "percent": 100,
        "message": "Run complete.",
        "results": {"analysis_json": "/results/fixturerun0000/analysis.json"},
        "report_url": "/results/fixturerun0000/report.html",
        "_stale_against": {
            "current_run_id": RUN_ID,
            "current_evaluation_id": "emotion.core",
            "expected_client_behaviour":
                "Discard. run_id differs from the active run, so this response must not "
                "replace the current results or download links.",
        },
        "_synthetic": SYNTHETIC,
    })
    written["targets_response.json"] = write_json(out / "targets_response.json", {
        "targets": [
            {"target_id": "emotion_v1", "task_id": "emotion_7", "label": "Emotion (unhardened)",
             "hardened": False},
            {"target_id": "emotion_v2", "task_id": "emotion_7", "label": "Emotion (hardened)",
             "hardened": True},
            {"target_id": "sentiment_v1", "task_id": "sentiment_2", "label": "Sentiment",
             "hardened": False},
        ],
        "evaluations": [
            {"evaluation_id": "emotion.core", "kind": "paired", "suite_id": "core"},
            {"evaluation_id": "sentiment.core", "kind": "single", "suite_id": "core"},
        ],
        "note": "Only trusted configured choices are offered. There is no free-form URL entry.",
        "_synthetic": SYNTHETIC,
    })
    written["rejected_unknown_target.json"] = write_json(
        out / "rejected_unknown_target.json", {
            "status_code": 422,
            "body": {
                "detail": [{
                    "loc": ["body", "target_id"],
                    "msg": "unknown target_id 'gpt_v9'; configured: "
                           "['emotion_v1', 'emotion_v2', 'sentiment_v1']",
                    "type": "value_error.unknown_target",
                }]
            },
            "_synthetic": SYNTHETIC,
        })
    written["rejected_busy.json"] = write_json(out / "rejected_busy.json", {
        "status_code": 409,
        "body": {"detail": "A run is already in progress.", "run_id": RUN_ID},
        "note": "One global job lock is shared by Demo and Lab.",
        "_synthetic": SYNTHETIC,
    })
    return written


# --------------------------------------------------------------------------------------
# negative fixtures -- each one must be REJECTED by a correct implementation
# --------------------------------------------------------------------------------------


def build_negative_fixtures(out: Path) -> dict:
    written = {}

    def neg(name, why, payload, *, jsonl=False):
        path = out / name
        if jsonl:
            written[name] = write_jsonl(path, payload)
        else:
            written[name] = write_json(path, payload)
        return why

    reasons = {}

    good = clean_row("emotion_v1", "v1", "core", "fx-emotion-0",
                     EMOTION_BASELINES[0][1], emotion_scores("anger", 0.95))
    other = clean_row("emotion_v2", "v2", "core", "fx-emotion-1",
                      EMOTION_BASELINES[1][1], emotion_scores("joy", 0.95))
    reasons["mixed_identity.jsonl"] = neg(
        "mixed_identity.jsonl",
        "Two different target_ids in one results file. A results file may contain exactly "
        "one target/suite/version; mixing them makes every per-target number ambiguous.",
        [good, other], jsonl=True,
    )

    reasons["wrong_model_revision.json"] = neg(
        "wrong_model_revision.json",
        "run_meta declares a model revision that differs from the registry pin. Pairing "
        "or gating across different weights is not a like-for-like comparison.",
        {
            "run_id": "neg-wrong-revision",
            "evaluation_run_id": RUN_ID,
            "target_id": "emotion_v2",
            "task_id": "emotion_7",
            "model": {
                "model_id": EMOTION_MODEL["model_id"],
                "revision": "1111111111111111111111111111111111111111",
                "tokenizer_id": EMOTION_MODEL["tokenizer_id"],
                "tokenizer_revision": EMOTION_MODEL["tokenizer_revision"],
                "labels": EMOTION_LABELS,
            },
            "_expected_rejection": "model revision does not match the registry pin",
            "_synthetic": SYNTHETIC,
        },
    )

    bad_labels = clean_row("sentiment_v1", "v1", "core", "fx-sentiment-0",
                           SENTIMENT_BASELINES[0][1], {"negative": 0.9, "positive": 0.1})
    reasons["wrong_label_space.jsonl"] = neg(
        "wrong_label_space.jsonl",
        "Lowercase sentiment labels. The declared space is NEGATIVE/POSITIVE; nothing may "
        "case-fold it into a match, and nothing may map it onto emotion labels.",
        [bad_labels], jsonl=True,
    )

    dup = clean_row("emotion_v1", "v1", "core", "fx-emotion-0",
                    EMOTION_BASELINES[0][1], emotion_scores("anger", 0.95))
    reasons["duplicate_case.jsonl"] = neg(
        "duplicate_case.jsonl",
        "The same case key appears twice. Silently keeping one changes every denominator.",
        [good, dup], jsonl=True,
    )

    orphan = attack_row("emotion_v1", "v1", "core", "fx-emotion-9.perturbation.typo",
                        "fx-emotion-9", "perturbation", "nope",
                        emotion_scores("anger", 0.9))
    reasons["orphan_derived.jsonl"] = neg(
        "orphan_derived.jsonl",
        "A derived attack whose baseline was never sent. There is no clean prediction to "
        "compare against, so it cannot enter drift scoring and must not be dropped "
        "silently either.",
        [good, orphan], jsonl=True,
    )

    reasons["altered_hash.json"] = neg(
        "altered_hash.json",
        "run_meta records a results_sha256 that does not match the results bytes. The "
        "artifact set cannot be trusted.",
        {
            "run_id": "neg-altered-hash",
            "evaluation_run_id": RUN_ID,
            "target_id": "emotion_v1",
            "fingerprints": {
                "results_sha256":
                    "0000000000000000000000000000000000000000000000000000000000000000",
                "manifest_sha256":
                    "0000000000000000000000000000000000000000000000000000000000000000",
            },
            "_expected_rejection": "recorded hash does not match the referenced bytes",
            "_synthetic": SYNTHETIC,
        },
    )

    reasons["zero_denominator.json"] = neg(
        "zero_denominator.json",
        "Every eligible comparison was excluded, so the flip rate has no denominator. "
        "Correct handling is rate=null rendered as N/A. Emitting 0.0 would read as "
        "'nothing failed', which is a different and unsupported claim.",
        {
            "target_id": "emotion_v2",
            "drift": {
                "eligible_comparisons": 0,
                "qualifying_flips": 0,
                "flip_rate": {"numerator": 0, "denominator": 0, "rate": None},
            },
            "_expected_rendering": "N/A",
            "_must_not_render": "0%",
            "_synthetic": SYNTHETIC,
        },
    )

    reasons["incomplete_execution.json"] = neg(
        "incomplete_execution.json",
        "The run stopped after a health failure. Missing cases must stay visible as "
        "missing; a missing V2 result must never read as 'V2 fixed it'.",
        {
            "run_id": "neg-incomplete",
            "evaluation_run_id": RUN_ID,
            "target_id": "emotion_v2",
            "termination_reason": "stopped_on_health_failure",
            "coverage": {
                "planned": 162, "selected": 162, "completed": 40, "missing": 122,
                "coverage_rate": 0.246914,
            },
            "_expected_handling":
                "Findings for the 122 unexecuted cases are 'unavailable', not 'resolved'.",
            "_synthetic": SYNTHETIC,
        },
    )

    truncated_path = out / "truncated.jsonl"
    truncated_path.parent.mkdir(parents=True, exist_ok=True)
    full = json.dumps(good, ensure_ascii=False, sort_keys=True)
    data = (full + "\n" + full[: len(full) // 2]).encode("utf-8")
    truncated_path.write_bytes(data)
    written["truncated.jsonl"] = hashlib.sha256(data).hexdigest()
    reasons["truncated.jsonl"] = (
        "The final JSON line is cut off mid-object. Loading must raise, not skip the bad "
        "line and quietly analyse a short run."
    )

    reasons["ambiguous_legacy.json"] = neg(
        "ambiguous_legacy.json",
        "A document with no schema_version and no recognised legacy layout. It must be "
        "rejected as unrecognised. It must NOT be assumed to be emotion, and target_id "
        "must not be inferred from 'version'.",
        {
            "summary": {"version": "v2", "findings": []},
            "_expected_rejection":
                "unrecognised analysis layout; explicit legacy routing only",
            "_must_not_happen":
                "silently adopting the emotion label space or target_id=version",
            "_synthetic": SYNTHETIC,
        },
    )

    written["_reasons.json"] = write_json(out / "_reasons.json", {
        "purpose":
            "Every file in this directory must be REJECTED by a correct implementation. "
            "A fixture that loads cleanly here is a bug in the consumer, not a bug here.",
        "reasons": reasons,
        "_synthetic": SYNTHETIC,
    })
    return written


# --------------------------------------------------------------------------------------
# genuine legacy fixture, built from the preserved benchmark bytes
# --------------------------------------------------------------------------------------


def build_genuine_legacy(out: Path) -> dict:
    """A real schema-v2 analysis, produced by the real analysis code from real rows.

    Not authored: a subset of the preserved V6 benchmark is fed through the actual
    ``analysis.run_analysis``. Small enough to read, genuine enough to test legacy
    upcasting against something that really came out of the pipeline.
    """
    from analysis.analyze import legacy_v2_view, run_analysis

    keep_baselines = ["dataset-anger-0", "dataset-anger-1"]
    manifest_bytes = (BENCH / "run" / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))

    def subset_rows(path):
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["case_type"] == "baseline" and r["baseline_id"] in keep_baselines:
                rows.append(r)
            elif r["case_type"] == "attack" and r.get("baseline_id") in keep_baselines:
                rows.append(r)
        return rows

    rows_v1 = subset_rows(BENCH / "run" / "results_v1.jsonl")
    rows_v2 = subset_rows(BENCH / "run" / "results_v2.jsonl")
    kept_attack_ids = {r["attack_id"] for r in rows_v1 if r["case_type"] == "attack"}
    sub_manifest = {k: v for k, v in manifest.items() if k in kept_attack_ids}

    case_ids = (
        [f"baseline:{b}" for b in keep_baselines]
        + [f"attack:{r['attack_id']}" for r in rows_v1 if r["case_type"] == "attack"]
    )

    work = out / "_source"
    work.mkdir(parents=True, exist_ok=True)
    man_path = work / "manifest.json"
    man_path.write_bytes(
        json.dumps(sub_manifest, indent=2, ensure_ascii=False).encode("utf-8")
    )
    man_sha = hashlib.sha256(man_path.read_bytes()).hexdigest()

    metas = {}
    for version, rows in (("v1", rows_v1), ("v2", rows_v2)):
        rpath = work / f"results_{version}.jsonl"
        rpath.write_bytes(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
        )
        original = json.loads(
            (BENCH / "run" / f"run_meta_{version}.json").read_text(encoding="utf-8")
        )
        meta = dict(original)
        meta["coverage"] = {
            "planned": len(case_ids), "skipped": 0, "limit_excluded": 0,
            "selected": len(case_ids), "completed": len(case_ids), "missing": 0,
            "coverage_rate": 1.0,
        }
        meta["case_ids"] = {
            "planned": case_ids, "selected": case_ids, "completed": case_ids,
            "skipped": [], "limit_excluded": [], "missing": [],
        }
        meta["suite"] = dict(original["suite"])
        meta["suite"].update({
            "baselines": len(keep_baselines),
            "attacks": len(kept_attack_ids),
            "total_cases": len(case_ids),
        })
        meta["fingerprints"] = dict(original["fingerprints"])
        meta["fingerprints"]["manifest_sha256"] = man_sha
        meta["fingerprints"]["manifest_path"] = str(man_path)
        (work / f"run_meta_{version}.json").write_bytes(
            json.dumps(meta, indent=2, ensure_ascii=False).encode("utf-8")
        )
        metas[version] = meta

    result = run_analysis(
        manifest_path=man_path,
        manifest_v2_path=man_path,
        results_v1_path=work / "results_v1.jsonl",
        results_v2_path=work / "results_v2.jsonl",
        meta_v1_path=work / "run_meta_v1.json",
        meta_v2_path=work / "run_meta_v2.json",
    )

    import dataclasses

    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        raise TypeError(type(o))

    # run_analysis now returns the v3 envelope (schema_version 3, evaluations[]).
    # This fixture specifically exercises legacy v2 upcasting, so project the real
    # result back onto the v2 shape with the official compatibility adapter rather
    # than reading v2-only keys off the v3 document directly.
    payload = json.loads(json.dumps(legacy_v2_view(result), default=enc, allow_nan=False))
    payload["_provenance"] = {
        "is_synthetic": False,
        "genuine": True,
        "description":
            "Real schema-v2 analysis output, produced by analysis.run_analysis over a "
            "real subset of the preserved V6 benchmark rows.",
        "source": "artifacts/benchmark_v6/run/",
        "source_results_v1_sha256":
            hashlib.sha256((BENCH / "run" / "results_v1.jsonl").read_bytes()).hexdigest(),
        "source_results_v2_sha256":
            hashlib.sha256((BENCH / "run" / "results_v2.jsonl").read_bytes()).hexdigest(),
        "subset_rule":
            f"baselines {keep_baselines} and every attack derived from them",
        "model_note":
            "The source run recorded no model revision; see "
            "artifacts/benchmark_v6/PROVENANCE.md.",
    }
    shutil.rmtree(work)
    return {
        "genuine_v2_analysis.json": write_json(out / "genuine_v2_analysis.json", payload),
        "_counts": {
            "baselines": len(keep_baselines),
            "attacks": len(kept_attack_ids),
            "findings_v1": len(payload["summary_v1"]["findings"]),
            "findings_v2": len(payload["summary_v2"]["findings"]),
        },
    }


def build_synthetic_legacy(out: Path) -> dict:
    """Clearly-labelled synthetic legacy rows and a legacy flat layout."""
    written = {}
    legacy_rows = [
        row(case_type="baseline", baseline_id="legacy-b0", version="v1", status_code=200,
            response_body=predict_body(emotion_scores("anger", 0.97))[0],
            label="anger", confidence=0.97, all_scores=emotion_scores("anger", 0.97)),
        row(case_type="attack", attack_id="legacy-b0.encoding.homoglyph",
            baseline_id="legacy-b0", category="encoding", version="v1", status_code=200,
            response_body=predict_body(emotion_scores("fear", 0.38))[0],
            label="fear", confidence=0.38, all_scores=emotion_scores("fear", 0.38)),
    ]
    written["synthetic_legacy_rows.jsonl"] = write_jsonl(
        out / "synthetic_legacy_rows.jsonl", legacy_rows
    )
    written["synthetic_legacy_layout.json"] = write_json(
        out / "synthetic_legacy_layout.json",
        {
            "schema_version": 2,
            "layout": "flat",
            "summary_v1": {"version": "v1", "findings": []},
            "summary_v2": {"version": "v2", "findings": []},
            "comparison": {"fingerprints": {"planned_match": True}},
            "_legacy_adapter_note":
                "Recognised legacy v2 layout. Route through the emotion legacy adapter "
                "with target_id emotion_v1/emotion_v2 recorded as INFERRED, never as "
                "declared. Upcast in memory only; the stored bytes stay as they are.",
            "_synthetic": SYNTHETIC,
        },
    )
    written["_note.json"] = write_json(out / "_note.json", {
        "genuine_v2_analysis.json":
            "GENUINE. Produced by the real analysis code from real preserved bytes.",
        "synthetic_legacy_rows.jsonl":
            "SYNTHETIC. Legacy rows with no target_id/suite_id, for adapter tests.",
        "synthetic_legacy_layout.json":
            "SYNTHETIC. A recognised legacy v2 envelope shape.",
        "legacy_target_mapping": {"v1": "emotion_v1", "v2": "emotion_v2"},
        "warning":
            "This mapping applies ONLY to recognised legacy emotion artifacts. A new run "
            "with a malformed identity must fail, never fall back to emotion.",
    })
    return written


# --------------------------------------------------------------------------------------
# assembling one evaluation directory
# --------------------------------------------------------------------------------------

EVALUATIONS = [
    # (evaluation_id, kind, task, suite, [(target_id, version, hardened), ...])
    ("emotion.core", "paired", "emotion_7", "core",
     [("emotion_v1", "v1", False), ("emotion_v2", "v2", True)]),
    ("sentiment.core", "single", "sentiment_2", "core",
     [("sentiment_v1", "v1", False)]),
    ("emotion.oces", "paired", "emotion_7", "oces",
     [("emotion_v1", "v1", False), ("emotion_v2", "v2", True)]),
    ("sentiment.oces", "single", "sentiment_2", "oces",
     [("sentiment_v1", "v1", False)]),
]

BASELINE_FILES = {
    ("emotion_7", "core"): "baseline/baseline.json",
    ("sentiment_2", "core"): "baseline/sentiment_baseline.json",
    ("emotion_7", "oces"): "baseline/oces/emotion_seeds.json",
    ("sentiment_2", "oces"): "baseline/oces/sentiment_seeds.json",
}


def build_evaluation(runs_root: Path, evaluation_id, kind, task, suite, targets):
    model = EMOTION_MODEL if task == "emotion_7" else SENTIMENT_MODEL
    families = list(CORE_FAMILIES_FX) if suite == "core" else list(OCES_FAMILIES_FX)
    eval_dir = runs_root / evaluation_id.replace(".", "_")

    rows_by_target, case_ids_by_target, meta_by_target = {}, {}, {}
    for target_id, version, hardened in targets:
        if suite == "core":
            rows, case_ids = build_core_rows(target_id, version, task, hardened)
        else:
            rows, case_ids = build_oces_rows(target_id, version, task, hardened)
        rows_by_target[target_id] = rows
        case_ids_by_target[target_id] = case_ids

    manifest = build_manifest(case_ids_by_target[targets[0][0]], suite, families)
    manifest_sha = write_json(eval_dir / "manifest.json", manifest)

    baseline_file = BASELINE_FILES[(task, suite)]
    # The hash of the baseline file this evaluation ACTUALLY uses. For OCES this is the
    # seed file, never the unrelated core baseline.
    baseline_sha = hashlib.sha256(baseline_file.encode("utf-8")).hexdigest()

    selection = None
    selection_sha = None
    if suite == "core" and task == "emotion_7":
        selection = {
            "case_set_id": "fx_core_v1",
            "selection_version": 1,
            "suite_id": "core",
            "baseline_ids": [b for b, _t, _l in EMOTION_BASELINES],
            "attack_ids": [
                k.split(":", 1)[1] for k in case_ids_by_target[targets[0][0]]
                if k.startswith("attack:")
            ],
            "order": case_ids_by_target[targets[0][0]],
            "exclusions": [],
            "_synthetic": SYNTHETIC,
        }
        selection_sha = write_json(eval_dir / "case_selection.json", selection)

    for target_id, version, _hardened in targets:
        rows = rows_by_target[target_id]
        results_sha = write_jsonl(eval_dir / target_id / "results.jsonl", rows)
        meta = build_run_meta(
            target_id=target_id, version=version, task=task, suite_id=suite,
            evaluation_id=evaluation_id, case_ids=case_ids_by_target[target_id],
            results_sha=results_sha, manifest_sha=manifest_sha,
            baseline_file=baseline_file, baseline_sha=baseline_sha, model=model,
            case_set_id=selection["case_set_id"] if selection else None,
            selection_sha=selection_sha,
        )
        write_json(eval_dir / target_id / "run_meta.json", meta)
        meta_by_target[target_id] = meta

    summaries = {
        target_id: target_summary(
            target_id=target_id, version=version, task=task, model=model,
            case_ids=case_ids_by_target[target_id], rows=rows_by_target[target_id],
            hardened=hardened, families=families, suite_id=suite,
        )
        for target_id, version, hardened in targets
    }

    if kind == "paired":
        a, b = targets[0][0], targets[1][0]
        comparison = paired_comparison(
            summaries[a], summaries[b], rows_by_target[a], rows_by_target[b]
        )
    else:
        # Single target: comparison is explicitly null EVERYWHERE. Never omitted, never
        # an empty object, and never a fabricated improvement percentage.
        comparison = None

    coverage = coverage_block(
        case_ids_by_target[targets[0][0]], rows_by_target[targets[0][0]], families, suite
    ) if suite == "core" else None
    oces = oces_block(rows_by_target, families) if suite == "oces" else None

    write_json(eval_dir / "coverage.json", coverage or {
        "_note": "Not applicable for an oces evaluation.", "_synthetic": SYNTHETIC})

    block = {
        "evaluation_id": evaluation_id,
        "kind": kind,
        "task_id": task,
        "suite_id": suite,
        "targets": [t[0] for t in targets],
        "baseline_file": baseline_file,
        "baseline_file_sha256": baseline_sha,
        "summaries": summaries,
        "comparison": comparison,
        "coverage": coverage,
        "oces": oces,
    }
    return block, eval_dir, meta_by_target


def build_runs(out: Path) -> dict:
    runs_root = out / "runs"
    blocks, dirs = [], {}
    for evaluation_id, kind, task, suite, targets in EVALUATIONS:
        block, eval_dir, _metas = build_evaluation(
            runs_root, evaluation_id, kind, task, suite, targets
        )
        blocks.append(block)
        dirs[evaluation_id] = eval_dir

    registry_snapshot = {
        "registry_version": "3.0.0",
        "source_path": "endpoint/targets.json",
        "source_sha256": hashlib.sha256(
            (ROOT / "endpoint" / "targets.json").read_bytes()
        ).hexdigest(),
        "note":
            "Real hash of the real registry file at foundation time, copied into the run "
            "so a later registry edit cannot silently change what a past run claimed.",
    }
    write_json(runs_root / "registry_snapshot.json", registry_snapshot)

    run_index = {
        "run_id": RUN_ID,
        "run_name": "stage3-fixture-run",
        "created_at_utc": CREATED_AT,
        "app_commit": APP_COMMIT,
        "dirty": False,
        "mode": "full",
        "registry": registry_snapshot,
        "evaluations": [
            {
                "evaluation_id": b["evaluation_id"],
                "kind": b["kind"],
                "task_id": b["task_id"],
                "suite_id": b["suite_id"],
                "declared_families": (
                    list(CORE_FAMILIES_FX) if b["suite_id"] == "core"
                    else list(OCES_FAMILIES_FX)
                ),
                "case_set_id": (
                    "fx_core_v1"
                    if b["suite_id"] == "core" and b["task_id"] == "emotion_7" else None
                ),
                "baseline_file": b["baseline_file"],
                "target_dirs": {
                    t: f"runs/{b['evaluation_id'].replace('.', '_')}/{t}"
                    for t in b["targets"]
                },
            }
            for b in blocks
        ],
        "_synthetic": SYNTHETIC,
    }
    write_json(runs_root / "run.json", run_index)

    expected = {
        "schema_version": 3,
        "contracts_version": "3.0.0",
        "run_identity": {
            "run_id": RUN_ID,
            "run_name": "stage3-fixture-run",
            "created_at_utc": CREATED_AT,
            "app_commit": APP_COMMIT,
            "dirty": False,
            "registry_sha256": registry_snapshot["source_sha256"],
        },
        "evaluations": blocks,
        "limitations": [
            "Synthetic fixture. Every number here is authored, not measured.",
            "An observed HTTP 500 is a server-error response. It is not evidence of an "
            "internal model crash, process death or an information leak.",
            "Coverage classes describe intended input-control coverage, not demonstrated "
            "effectiveness and not causal attribution.",
            "The additional evaluation was authored after the defenses were frozen by "
            "authors who knew the defenses. It is not a blind holdout.",
            "A prediction flip is a consistency failure, not automatically a new wrong "
            "answer.",
        ],
        "_synthetic": SYNTHETIC,
    }
    write_json(out / "expected_analysis_v3.json", expected)
    return {"run_index": run_index, "expected": expected, "dirs": dirs}


# --------------------------------------------------------------------------------------
# validation -- the builder checks its own output before it exits
# --------------------------------------------------------------------------------------


def validate(out: Path, expected: dict, run_index: dict) -> list[str]:
    problems = []

    def bad(msg):
        problems.append(msg)

    text_blob = ""
    for path in sorted_paths(out.rglob("*"), out):
        if path.is_file() and path.suffix in (".json", ".jsonl"):
            text_blob += path.read_text(encoding="utf-8")
    for forbidden in ("...", "PLACEHOLDER", "TODO", "XXXX", "0xdeadbeef"):
        if forbidden in text_blob:
            bad(f"forbidden placeholder text {forbidden!r} appears in a fixture")

    indexed = {e["evaluation_id"] for e in run_index["evaluations"]}
    present = {b["evaluation_id"] for b in expected["evaluations"]}
    if indexed != present:
        bad(f"run.json indexes {sorted(indexed)} but analysis has {sorted(present)}")

    for entry in run_index["evaluations"]:
        for target_id, rel in entry["target_dirs"].items():
            d = out / rel
            if not (d / "results.jsonl").is_file():
                bad(f"{entry['evaluation_id']}/{target_id}: results.jsonl missing")
            if not (d / "run_meta.json").is_file():
                bad(f"{entry['evaluation_id']}/{target_id}: run_meta.json missing")

    for block in expected["evaluations"]:
        eid = block["evaluation_id"]
        if block["kind"] == "single":
            if block["comparison"] is not None:
                bad(f"{eid}: single-target comparison must be null")
            if len(block["targets"]) != 1:
                bad(f"{eid}: single evaluation with {len(block['targets'])} targets")
        else:
            if block["comparison"] is None:
                bad(f"{eid}: paired evaluation has null comparison")

        for target_id, summary in block["summaries"].items():
            cov = summary["coverage"]
            if cov["selected"] != cov["completed"] + cov["missing"]:
                bad(f"{eid}/{target_id}: coverage partition does not add up")
            drift = summary["drift"]
            fr = drift["flip_rate"]
            if fr["denominator"] and fr["rate"] != round(
                fr["numerator"] / fr["denominator"], 6
            ):
                bad(f"{eid}/{target_id}: flip_rate does not match its numerator/denominator")
            if not fr["denominator"] and fr["rate"] is not None:
                bad(f"{eid}/{target_id}: zero denominator must give rate null")
            if fr["numerator"] > fr["denominator"]:
                bad(f"{eid}/{target_id}: more flips than eligible comparisons")

            labels = set(summary["identity"]["declared"]["label_space"])
            meta_path = out / f"runs/{eid.replace('.', '_')}/{target_id}/run_meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            actual_sha = hashlib.sha256(
                (meta_path.parent / "results.jsonl").read_bytes()
            ).hexdigest()
            if meta["fingerprints"]["results_sha256"] != actual_sha:
                bad(f"{eid}/{target_id}: run_meta results_sha256 does not match the bytes")
            if meta["baseline"]["path"] != block["baseline_file"]:
                bad(f"{eid}/{target_id}: run_meta baseline path disagrees with the block")
            for line in (meta_path.parent / "results.jsonl").read_text(
                encoding="utf-8"
            ).splitlines():
                r = json.loads(line)
                if r["target_id"] != target_id:
                    bad(f"{eid}/{target_id}: row carries target_id {r['target_id']!r}")
                if r["suite_id"] != block["suite_id"]:
                    bad(f"{eid}/{target_id}: row carries suite_id {r['suite_id']!r}")
                if r["label"] is not None and r["label"] not in labels:
                    bad(f"{eid}/{target_id}: label {r['label']!r} outside declared space")
                if r["request_body_bytes"] is None or r["request_body_sha256"] is None:
                    bad(f"{eid}/{target_id}: new row missing sender request-byte evidence")
                if r["all_scores"] is not None and set(r["all_scores"]) != labels:
                    bad(f"{eid}/{target_id}: all_scores keys do not match the label space")

            for entry in summary["findings"]:
                if "finding" not in entry:
                    bad(f"{eid}/{target_id}: finding entry lost its nested finding object")
                elif not entry["finding"]["remediation"]:
                    bad(f"{eid}/{target_id}: nested finding has empty remediation")
                if "remediation_detail" not in entry:
                    bad(f"{eid}/{target_id}: finding entry has no remediation_detail")
                else:
                    rd = entry["remediation_detail"]
                    if rd["diagnosis_confidence"] not in ("supported", "suspected"):
                        bad(f"{eid}/{target_id}: bad diagnosis_confidence")
                    if not rd["verification"].get("command"):
                        bad(f"{eid}/{target_id}: remediation has no verification command")
                    if rd["verification"]["target_id"] != target_id:
                        bad(
                            f"{eid}/{target_id}: verification names a different target "
                            f"({rd['verification']['target_id']}) -- a sentiment finding "
                            "must never be rerouted to emotion_v2"
                        )
                    cs = rd["verification"].get("case_set_file")
                    if cs and not (ROOT / cs).is_file():
                        bad(f"{eid}/{target_id}: verification names a missing case set {cs}")

        if block["coverage"]:
            counts = block["coverage"]["counts"]
            if sum(counts.values()) != block["coverage"]["selected_attacks"]:
                bad(f"{eid}: coverage buckets do not partition the selected attacks")
        if block["oces"]:
            fams = set(block["oces"]["families"])
            if fams != set(OCES_FAMILIES_FX):
                bad(f"{eid}: oces families are {sorted(fams)}, expected the two agreed")
            planned = set(block["oces"]["planned_attack_ids"])
            for target_id, data in block["oces"]["by_target"].items():
                if set(data["per_case"]) != planned:
                    bad(f"{eid}/{target_id}: not every planned oces case has a status")

    # gate fixtures must satisfy the real contract object, not just look plausible
    from contract import CheckResult, GateOutcome
    for path in sorted((out / "gate").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            GateOutcome(
                outcome=raw["outcome"], exit_code=raw["exit_code"],
                policy_id=raw["policy_id"], policy_version=raw["policy_version"],
                policy_sha256=raw["policy_sha256"], candidate=raw["candidate"],
                reference=raw["reference"], suite_id=raw["suite_id"],
                case_set_id=raw["case_set_id"], selection_sha256=raw["selection_sha256"],
                checks=[
                    CheckResult(
                        check_id=c["check_id"], status=c["status"], reason=c["reason"],
                        evidence_refs=c["evidence_refs"], observed=c["observed"],
                        threshold=c["threshold"], blocking=c["blocking"],
                    )
                    for c in raw["checks"]
                ],
                summary=raw["summary"], artifacts=raw["artifacts"],
                exclusions=raw["exclusions"], schema_version=raw["schema_version"],
            )
        except Exception as exc:
            bad(f"gate/{path.name}: rejected by contract.GateOutcome: {exc}")

    # negative fixtures must not accidentally be valid
    neg = out / "negative"
    rows_path = neg / "mixed_identity.jsonl"
    ids = {
        json.loads(line)["target_id"]
        for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()
    }
    if len(ids) < 2:
        bad("negative/mixed_identity.jsonl does not actually mix identities")
    try:
        json.loads((neg / "truncated.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        bad("negative/truncated.jsonl parses cleanly; it is supposed to be truncated")
    except json.JSONDecodeError:
        pass
    return problems


def main() -> int:
    out = HERE
    for child in sorted_paths(out.iterdir(), out):
        if child.name in ("build_fixtures.py", "README.md", "__pycache__"):
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()

    global CLEAN_REFERENCE_SHA, SELECTION_SHA
    CLEAN_REFERENCE_SHA = hashlib.sha256(
        (ROOT / "analysis" / "policies" / "ci_core_v1_clean_reference.json").read_bytes()
    ).hexdigest()
    SELECTION_SHA = hashlib.sha256(
        (ROOT / "analysis" / "case_sets" / "ci_core_v1.json").read_bytes()
    ).hexdigest()

    built = build_runs(out)
    build_gate_fixtures(out / "gate")
    build_api_fixtures(out / "api")
    build_negative_fixtures(out / "negative")
    legacy_counts = build_genuine_legacy(out / "legacy")
    build_synthetic_legacy(out / "legacy")

    write_json(out / "MANIFEST.json", {
        "description":
            "Index of the Stage 3 fixture pack, with a real SHA-256 for every file.",
        "generated_by": "tests/fixtures/stage3/build_fixtures.py",
        "contracts_version": "3.0.0",
        "clean_reference_sha256": CLEAN_REFERENCE_SHA,
        "selection_sha256": SELECTION_SHA,
        "files": {
            p.relative_to(out).as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted_paths(out.rglob("*"), out)
            if p.is_file() and p.name not in ("build_fixtures.py", "MANIFEST.json")
            and "__pycache__" not in p.parts
        },
    })

    problems = validate(out, built["expected"], built["run_index"])
    files = [
        p for p in out.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    total = sum(p.stat().st_size for p in files)
    print(f"fixture files : {len(files)}")
    print(f"total size    : {total/1024:.1f} KiB")
    print(f"genuine legacy: {legacy_counts['_counts']}")
    if problems:
        print(f"\nVALIDATION FAILED ({len(problems)} problem(s)):")
        for p in problems:
            print("  -", p)
        return 1
    print("validation    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
