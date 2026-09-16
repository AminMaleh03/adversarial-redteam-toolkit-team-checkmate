"""Finding-specific remediation: observed -> significance -> fix -> verification.

Rules are selected by what was actually observed -- the failure mode, the family and the
subfamily -- never by a finding's sequence number. Each rule carries an id, a version and
the hash of the rule file it came from, so a reader can tell which rule produced a piece
of advice and whether the rules have changed since.

The observations are generated from the recorded rows of the finding's own evidence, so
two findings sharing a rule still carry different numbers, case ids and status
distributions.

Claims this module will not make
--------------------------------
A generic 500 does not establish an internal model crash, process death or a leak: the
hardened wrapper's own handler returns 500 too, so the honest phrase is "observed
server-error response". A token limit does not protect against oversized HTTP bodies,
because tokenization happens after the body is read and parsed. Anything the rows do not
establish is marked ``suspected`` or listed under ``unavailable_evidence`` rather than
filled in.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

RULES_PATH = Path(__file__).parent / "remediation_rules.json"

FALLBACK_RULE_ID = "RM-FALLBACK"


def load_rules(path=None) -> dict:
    """Load the rule file and hash the exact bytes that were parsed."""
    path = Path(path) if path is not None else RULES_PATH
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    return {
        "version": document["rules_version"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "rules": document["rules"],
    }


def select_rule(rules: dict, *, failure_mode: str, family: str, subfamily: str) -> dict:
    """Most specific matching rule wins; the fallback is used only if nothing matches.

    Specificity order: an exact subfamily match, then a subfamily prefix, then a family
    list, then failure mode alone.
    """
    candidates = []
    for rule in rules["rules"]:
        applies = rule.get("applies_to", {})
        if not applies:
            continue
        if applies.get("failure_mode") and applies["failure_mode"] != failure_mode:
            continue
        score = 1
        if "subfamilies" in applies:
            if subfamily not in applies["subfamilies"]:
                continue
            score = 4
        elif "subfamily_prefix" in applies:
            if not subfamily.startswith(applies["subfamily_prefix"]):
                continue
            score = 3
        elif "families" in applies:
            if family not in applies["families"]:
                continue
            score = 2
        candidates.append((score, rule))
    if not candidates:
        return next(r for r in rules["rules"] if r.get("rule_id") == FALLBACK_RULE_ID)
    return max(candidates, key=lambda pair: pair[0])[1]


def observe(rows: list, evidence_ids: list) -> dict:
    """Facts drawn from the finding's own recorded rows. No inference here."""
    by_id = {r.attack_id: r for r in rows if r.case_type == "attack"}
    cited = [by_id[a] for a in evidence_ids if a in by_id]
    statuses = Counter(
        ("no response" if r.status_code is None else str(r.status_code)) for r in cited
    )
    bands = Counter(r.latency_band for r in cited)
    confidences = [r.confidence for r in cited if r.confidence is not None]
    body_bytes = [r.request_body_bytes for r in cited if r.request_body_bytes is not None]
    health_failures = [r.attack_id for r in cited if not r.endpoint_alive_after]

    observed = {
        "affected_case_count": len(evidence_ids),
        "rows_available": len(cited),
        "status_distribution": dict(sorted(statuses.items())),
        "latency_bands": dict(sorted(bands.items())),
        "example_case_ids": sorted(evidence_ids)[:5],
        "health_check_failures_after_request": health_failures,
    }
    if confidences:
        observed["confidence_range"] = {
            "min": round(min(confidences), 6),
            "max": round(max(confidences), 6),
            "count": len(confidences),
        }
    if body_bytes:
        observed["request_body_bytes"] = {
            "min": min(body_bytes), "max": max(body_bytes), "count": len(body_bytes),
        }
    return observed


def unavailable_evidence(rows: list, evidence_ids: list) -> list:
    """State what is missing rather than filling it in."""
    by_id = {r.attack_id: r for r in rows if r.case_type == "attack"}
    cited = [by_id[a] for a in evidence_ids if a in by_id]
    missing = []
    if cited and all(r.request_body_bytes is None for r in cited):
        missing.append(
            "Sent request-body byte lengths were not recorded for these rows. Historical "
            "rows are always null here and cannot be reconstructed; any size quoted "
            "elsewhere would be a guess."
        )
    if cited and all(not r.response_body for r in cited):
        missing.append(
            "No response body was captured for these rows, so body-derived claims "
            "(leak signatures, error shape) cannot be made from this evidence."
        )
    absent = [a for a in evidence_ids if a not in by_id]
    if absent:
        missing.append(f"{len(absent)} cited case id(s) have no row in this results file.")
    return missing


def build_verification(
    *, target_id: str, case_set_file: str, evidence_ids: list, expected: str,
    includes_baselines: bool = True,
) -> dict:
    """A runnable verification route naming the target that must actually change.

    The target here is the affected or patched one. A sentiment finding is never verified
    by re-running emotion_v2, and running a request collector is not passing a gate.
    """
    return {
        "target_id": target_id,
        "case_set_file": case_set_file,
        "includes_baselines": includes_baselines,
        "command": (
            f"python -m runner.run --target-id {target_id} --case-set {case_set_file} "
            f"--out results/verify_{target_id}"
        ),
        "expected": expected,
        "inspect": (
            f"results/verify_{target_id}/results_{target_id}.jsonl -- check the rows whose "
            f"attack_id is one of: {', '.join(sorted(evidence_ids)[:3])}"
            + (" (and the rest of the cited ids)" if len(evidence_ids) > 3 else "")
        ),
    }


def build_remediation_detail(
    *,
    finding,
    failure_mode: str,
    subfamily: str,
    rows: list,
    target_id: str,
    case_set_file: str,
    rules: dict | None = None,
) -> dict:
    """The ``remediation_detail`` sibling of a finding object."""
    rules = rules or load_rules()
    rule = select_rule(rules, failure_mode=failure_mode, family=finding.category,
                       subfamily=subfamily)
    observed = observe(rows, finding.evidence)
    detail = {
        "rule_id": rule["rule_id"],
        "rule_version": rules["version"],
        "rule_sha256": rules["sha256"],
        "is_fallback": bool(rule.get("is_fallback")),
        "observed": observed,
        "significance": rule["significance"],
        "diagnosis_confidence": rule["diagnosis_confidence"],
        "fix": rule["fix"],
        "verification": build_verification(
            target_id=target_id,
            case_set_file=case_set_file,
            evidence_ids=finding.evidence,
            expected=rule["verification_expected"],
        ),
        "unavailable_evidence": unavailable_evidence(rows, finding.evidence),
    }
    if rule.get("model_level"):
        detail["limitation"] = (
            "This is a model-level weakness. No endpoint control fixes it, and inventing "
            "one would misrepresent the finding; the fix above is an evaluation and "
            "retraining procedure instead."
        )
    return detail


def build_finding_remediation_string(detail: dict, finding) -> str:
    """A concise, evidence-specific string for legacy ``Finding.remediation`` consumers.

    New findings only. Historical strings are left exactly as they were written.
    """
    observed = detail["observed"]
    statuses = ", ".join(f"{k}x{v}" for k, v in observed["status_distribution"].items())
    return (
        f"{len(finding.evidence)} case(s)"
        + (f" observed as {statuses}" if statuses else "")
        + f". {detail['fix']}"
    )
