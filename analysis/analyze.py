"""Entry point that loads run results and emits the final list of Finding objects.

Loads the manifest, both versions' results and run metadata; joins metadata onto results
by attack_id; scores each attack against its pre-registered oracle; groups repeated
failures into Finding objects; and emits both the deterministic Finding list and the
report-facing summary JSON described in the ClickUp brief. Imports nothing from
``attacks/`` -- the manifest JSON is the only channel for oracle data, per AGENTS.md.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from contract import Finding, RunResult

from analysis import compare, drift, severity
from analysis.validation import validate_manifest, validate_rows, validate_run
from analysis.compare import FindingGroupRef
from analysis.drift import (
    ORACLE_DIAGNOSTIC,
    ORACLE_GRACEFUL_OR_TRUNCATE,
    ORACLE_LABEL_MATCH_BASELINE,
    ORACLE_NO_INFO_LEAK,
    ORACLE_REQUEST_REJECTED,
    ORACLE_STAY_AVAILABLE,
    TIER_DIAGNOSTIC,
    TIER_REVIEW,
)

CATEGORIES = ("malformed", "boundary", "perturbation", "encoding", "whitespace", "truncation")

DEFAULT_MANIFEST_NAME = "manifest.json"

# Standing limitations the report must carry. These are method caveats, not findings, and
# they are emitted unconditionally so they cannot be quietly omitted from the write-up.
LIMITATION_NOTES = (
    "Drift is measured against each endpoint's own clean prediction, never the dataset "
    "label a baseline sentence was written to represent. Where a baseline does not predict "
    "its intended label the comparison remains valid, and no model-accuracy claim in this "
    "analysis rests on those baselines.",
    "V2's defenses are application-layer only; no retraining was done. V2 is therefore not "
    "expected to reduce model-level sensitivity to typos or other meaning-preserving "
    "perturbations. A perturbation finding that persists on V2 is an honest non-improvement, "
    "not a gap in the hardening.",
    "A failed health check records observed unavailability only. It is not evidence that the "
    "operating-system process died, and no process-death claim is made anywhere here.",
    "Validity tiers are preserved per finding. Most of the suite is SILVER -- mechanically "
    "justified but not hand-verified -- so findings resting on SILVER evidence carry weaker "
    "semantic assurance than GOLD ones.",
)

# --------------------------------------------------------------------------------------
# leak detection -- cross-cutting, runs on every response body regardless of the case's
# declared oracle. Ordinary FastAPI/Pydantic 422 fields (loc/msg/type) are not leakage.
# --------------------------------------------------------------------------------------

_STACK_TRACE_MARKERS = ("Traceback (most recent call last)", "File \"", '"file":')
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\")
_UNIX_PATH_RE = re.compile(r"(?<![\w.])/(?:home|usr|var|Users|etc|opt)/")
# Deliberately no bare "pydantic." marker: Pydantic v2's default 422 body includes a
# public docs link (".../errors.pydantic.dev/...") on every ordinary validation error,
# which would otherwise flag every type-confusion 422 as a leak. That is exactly the
# "ordinary FastAPI/Pydantic validation output is not leakage" case the brief calls out.
_INTERNAL_NAME_MARKERS = (
    "site-packages", "<module ", " at 0x", "object at 0x",
    "starlette.", "uvicorn.", "fastapi.exceptions",
)


def detect_leak(body: Optional[str], status_code: Optional[int] = None) -> Optional[str]:
    if not body:
        return None
    # FastAPI 422 validation reflects user values (including nested objects) in input,
    # and user field names in loc. Inspect server diagnostics, not these reflections.
    # Restrict filtering to the actual validation shape, never arbitrary "input" keys.
    if status_code == 422:
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("detail"), list):
            details = parsed["detail"]
            if all(isinstance(item, dict) and isinstance(item.get("type"), str)
                   and isinstance(item.get("msg"), str) and isinstance(item.get("loc"), list)
                   for item in details):
                parsed["detail"] = [{k: v for k, v in item.items() if k not in ("input", "loc")}
                                    for item in details]
                body = json.dumps(parsed, ensure_ascii=False)
    if any(marker in body for marker in _STACK_TRACE_MARKERS):
        return "stack_or_path"
    if _WIN_PATH_RE.search(body) or _UNIX_PATH_RE.search(body):
        return "stack_or_path"
    if any(marker in body for marker in _INTERNAL_NAME_MARKERS):
        return "internal_names"
    return None


# --------------------------------------------------------------------------------------
# per-case oracle evaluation
# --------------------------------------------------------------------------------------


@dataclass
class Instance:
    """One failure signal fired by one attack result."""

    failure_mode: str
    attack_id: str
    category: str
    subfamily: str
    validity_tier: str
    context: dict = field(default_factory=dict)


@dataclass
class CaseEvaluation:
    attack_id: str
    category: str
    subfamily: str
    validity_tier: str
    # "pass", "fail", "review", "diagnostic", or "unevaluable".
    bucket: str
    instances: list[Instance] = field(default_factory=list)
    is_connection_failure: bool = False


def _oracle_label_match_baseline(result, drift_record) -> list[tuple[str, dict]]:
    if (
        drift_record is not None
        and drift_record.status == "eligible"
        and drift_record.qualifying_flip
    ):
        return [(severity.FINDING_PREDICTION_FLIP, {"clean_confidence": drift_record.clean_confidence})]
    return []


def _oracle_request_rejected(result, drift_record) -> list[tuple[str, dict]]:
    if result.status_code is not None and result.status_code < 300:
        return [(severity.FINDING_INVALID_INPUT_ACCEPTED, {"accepted_confidence": result.confidence})]
    return []


def _oracle_no_extra_instances(result, drift_record) -> list[tuple[str, dict]]:
    # graceful_or_truncate, stay_available, no_info_leak, and diagnostic all resolve
    # entirely through the cross-cutting checks (availability/5xx/timeout/leak) already
    # run on every case; none of them contribute a failure mode of their own.
    return []


# The explicit lookup the brief calls for: one entry per oracle value, not ad-hoc
# branching. Each handler returns the extra (failure_mode, context) pairs that oracle
# contributes on top of the cross-cutting checks every case already gets.
ORACLE_HANDLERS = {
    ORACLE_LABEL_MATCH_BASELINE: _oracle_label_match_baseline,
    ORACLE_REQUEST_REJECTED: _oracle_request_rejected,
    ORACLE_GRACEFUL_OR_TRUNCATE: _oracle_no_extra_instances,
    ORACLE_STAY_AVAILABLE: _oracle_no_extra_instances,
    ORACLE_NO_INFO_LEAK: _oracle_no_extra_instances,
    ORACLE_DIAGNOSTIC: _oracle_no_extra_instances,
}


def evaluate_case(
    result: RunResult, meta: dict, drift_record: Optional[drift.DriftRecord]
) -> CaseEvaluation:
    """Judge one attack result against every applicable check.

    Cross-cutting checks (service availability, unhandled 5xx, timeout, leakage, slow
    response) run regardless of the case's declared oracle -- a 500 is a 500 whatever the
    case was probing. ``ORACLE_HANDLERS`` then adds whatever that specific oracle
    contributes on top. DIAGNOSTIC and REVIEW-tier cases are never auto-scored, on either
    axis.
    """
    category = meta.get("family", result.category)
    subfamily = meta.get("subfamily", "unknown")
    tier = meta.get("validity_tier")
    attack_id = result.attack_id

    if tier == TIER_DIAGNOSTIC or meta.get("oracle") == ORACLE_DIAGNOSTIC:
        return CaseEvaluation(attack_id, category, subfamily, tier, "diagnostic")
    if tier == TIER_REVIEW:
        return CaseEvaluation(attack_id, category, subfamily, tier, "review")
    if tier not in (drift.TIER_GOLD, drift.TIER_SILVER) or meta.get("oracle") not in ORACLE_HANDLERS:
        raise ValueError(f"{attack_id}: unknown oracle or validity tier")

    instances: list[Instance] = []

    def add(failure_mode: str, **context) -> None:
        instances.append(Instance(failure_mode, attack_id, category, subfamily, tier, context))

    service_unavailable = not result.endpoint_alive_after
    is_5xx = result.status_code is not None and result.status_code >= 500
    is_timeout = result.latency_band == "timeout"
    # Structural, not string-matched: no HTTP response came back for a reason other than
    # hitting the timeout. This covers both of the runner's non-timeout no-response error
    # kinds (connection_error and transport_error) without depending on its exact error
    # message prefix, which is a private implementation detail of runner/run.py.
    is_connfail = result.status_code is None and not is_timeout
    is_slow = result.status_code is not None and result.latency_band == "slow"
    leak_kind = detect_leak(result.response_body, result.status_code)

    if service_unavailable:
        add(severity.FINDING_SERVICE_UNAVAILABLE)
    if is_5xx:
        add(severity.FINDING_UNHANDLED_5XX, subfamily=subfamily)
    if is_connfail:
        add(severity.FINDING_CONNECTION_FAILURE)
    if is_timeout:
        add(severity.FINDING_TIMEOUT, subfamily=subfamily)
    if leak_kind:
        add(severity.FINDING_INFO_LEAK, leak_kind=leak_kind)
    if is_slow:
        add(severity.FINDING_SLOW_RESPONSE, seconds=result.latency_ms / 1000.0)

    handler = ORACLE_HANDLERS.get(meta.get("oracle"))
    if handler is not None:
        for failure_mode, context in handler(result, drift_record):
            add(failure_mode, **context)

    if instances:
        bucket = "fail"
    else:
        bucket = "pass"

    return CaseEvaluation(
        attack_id, category, subfamily, tier, bucket, instances, is_connection_failure=is_connfail
    )


# --------------------------------------------------------------------------------------
# category statistics
# --------------------------------------------------------------------------------------


def _empty_category_bucket() -> dict:
    return {"eligible": 0, "failed": 0, "review": 0, "diagnostic": 0, "unevaluable": 0}


def compute_category_stats(evaluations: list[CaseEvaluation]) -> dict[str, dict]:
    """Per-category rate with an explicit denominator. Zero eligible cases -> None (N/A).

    Diagnostic and unresolved REVIEW cases never enter eligible/failed. A case counts at
    most once in the numerator even if it fired several distinct failure modes.
    """
    stats = {cat: _empty_category_bucket() for cat in CATEGORIES}
    for evaluation in evaluations:
        bucket = stats.setdefault(evaluation.category, _empty_category_bucket())
        if evaluation.bucket == "diagnostic":
            bucket["diagnostic"] += 1
        elif evaluation.bucket == "review":
            bucket["review"] += 1
        elif evaluation.bucket == "unevaluable":
            bucket["unevaluable"] += 1
        elif evaluation.bucket == "fail":
            bucket["eligible"] += 1
            bucket["failed"] += 1
        elif evaluation.bucket == "pass":
            bucket["eligible"] += 1
    for bucket in stats.values():
        bucket["failure_rate"] = (bucket["failed"] / bucket["eligible"]) if bucket["eligible"] else None
    return stats


def compute_operational_stats(evaluations: list[CaseEvaluation]) -> dict:
    """Headline counts. Kept as four separate numbers, per the settled crash-finding rules:
    unhandled 5xx, timeouts, connection failures, and service unavailability never merge.
    """
    stats = {
        "unhandled_5xx": 0,
        "timeouts": 0,
        "connection_failures": 0,
        "service_unavailable": 0,
        "slow_responses": 0,
        "info_leaks": 0,
        # "error-handling gap": the endpoint answered a request its own oracle says it
        # should have rejected. Tracked here so the comparison can report it directly.
        "invalid_input_accepted": 0,
    }
    counted_kind = {
        severity.FINDING_UNHANDLED_5XX: "unhandled_5xx",
        severity.FINDING_TIMEOUT: "timeouts",
        severity.FINDING_SERVICE_UNAVAILABLE: "service_unavailable",
        severity.FINDING_SLOW_RESPONSE: "slow_responses",
        severity.FINDING_INFO_LEAK: "info_leaks",
        severity.FINDING_INVALID_INPUT_ACCEPTED: "invalid_input_accepted",
    }
    for evaluation in evaluations:
        for instance in evaluation.instances:
            key = counted_kind.get(instance.failure_mode)
            if key:
                stats[key] += 1
        if evaluation.is_connection_failure:
            stats["connection_failures"] += 1
    return stats


# --------------------------------------------------------------------------------------
# grouping into Finding objects
# --------------------------------------------------------------------------------------

FAILURE_MODE_TITLES = {
    severity.FINDING_CONNECTION_FAILURE: "request connection failure",
    severity.FINDING_SERVICE_UNAVAILABLE: "observed service unavailability",
    severity.FINDING_UNHANDLED_5XX: "unhandled server error",
    severity.FINDING_INFO_LEAK: "error response leaked internal details",
    severity.FINDING_TIMEOUT: "hit the request timeout",
    severity.FINDING_PREDICTION_FLIP: "prediction flip",
    severity.FINDING_INVALID_INPUT_ACCEPTED: "invalid input accepted",
    severity.FINDING_SLOW_RESPONSE: "slow response",
}

# Precise wording per failure mode. The availability line in particular is deliberate:
# a failed health check proves observed unavailability, never process death.
FAILURE_MODE_DETAIL = {
    severity.FINDING_CONNECTION_FAILURE: (
        "the request failed without an HTTP response for a reason other than timeout; "
        "this alone does not establish service unavailability or process death"
    ),
    severity.FINDING_SERVICE_UNAVAILABLE: (
        "the health check after the request did not answer, which is observed "
        "unavailability and is not evidence of process death"
    ),
    severity.FINDING_UNHANDLED_5XX: (
        "the endpoint returned an unhandled 5xx; where health still answered afterwards "
        "the request failed but the service survived, which is not unavailability"
    ),
    severity.FINDING_INFO_LEAK: (
        "the response body exposed a stack trace, an absolute filesystem path, or internal "
        "module/function names (ordinary FastAPI/Pydantic validation fields are not counted)"
    ),
    severity.FINDING_TIMEOUT: (
        "no response was produced within the 10 second deadline; the recorded error is "
        "client-side and carries no server-stage information, so no cause is attributed"
    ),
    severity.FINDING_PREDICTION_FLIP: (
        "the top label changed under a meaning-preserving transformation while the clean "
        "prediction was confident (at or above 0.6)"
    ),
    severity.FINDING_INVALID_INPUT_ACCEPTED: (
        "the manifest oracle says this request should have been rejected, but the endpoint "
        "accepted it and answered"
    ),
    severity.FINDING_SLOW_RESPONSE: (
        "the response landed in the slow band (2 seconds up to the timeout)"
    ),
}

REMEDIATIONS = {
    severity.FINDING_CONNECTION_FAILURE: (
        "Investigate the recorded transport error and handle request failures cleanly; "
        "check connection handling and resource limits without inferring process death."
    ),
    severity.FINDING_SERVICE_UNAVAILABLE: (
        "Add resource limits and process supervision so a single request cannot take the "
        "service down; alert on health-check failure."
    ),
    severity.FINDING_UNHANDLED_5XX: (
        "Add a scoped exception handler for this failure mode that returns a typed error "
        "response instead of an unhandled traceback."
    ),
    severity.FINDING_INFO_LEAK: (
        "Strip stack traces, file paths, and internal module/function names from error "
        "responses; return only the standard validation fields."
    ),
    severity.FINDING_TIMEOUT: (
        "Reject or bound oversized/slow requests before they can consume the full request "
        "deadline."
    ),
    severity.FINDING_PREDICTION_FLIP: (
        "Model robustness gap rather than an endpoint defect; consider augmenting training "
        "data with this perturbation family."
    ),
    severity.FINDING_INVALID_INPUT_ACCEPTED: (
        "Reject the malformed or out-of-schema input with a 4xx response instead of "
        "processing it."
    ),
    severity.FINDING_SLOW_RESPONSE: (
        "Profile and bound the slow code path so typical requests stay under the "
        "2-second latency band."
    ),
}


def build_findings(
    evaluations: list[CaseEvaluation], version: str
) -> tuple[list[Finding], dict[str, dict], list[FindingGroupRef]]:
    """Group by (category, subfamily, failure_mode) and score once per group.

    Sorted by key before numbering, so the same input always produces the same finding_ids
    regardless of incidental row order in the source files.
    """
    groups: dict[tuple[str, str, str], dict] = {}
    for evaluation in evaluations:
        for instance in evaluation.instances:
            key = (instance.category, instance.subfamily, instance.failure_mode)
            group = groups.setdefault(key, {"instances": [], "evidence": set(), "validity_tiers": set()})
            group["instances"].append(instance)
            group["evidence"].add(instance.attack_id)
            group["validity_tiers"].add(instance.validity_tier)

    findings: list[Finding] = []
    finding_meta: dict[str, dict] = {}
    finding_groups: list[FindingGroupRef] = []

    for index, key in enumerate(sorted(groups.keys()), start=1):
        category, subfamily, failure_mode = key
        group = groups[key]
        instance_scores = [
            severity.compute_severity(failure_mode, **instance.context)[0]
            for instance in group["instances"]
        ]
        score, tier = severity.score_group(instance_scores)
        evidence = sorted(group["evidence"])
        finding_id = f"F-{version}-{index:03d}"
        title = f"{category}/{subfamily}: {FAILURE_MODE_TITLES[failure_mode]}"
        # Reproduction count is stated as reproducibility information only. It never
        # raises the score: severity is the highest single qualifying instance.
        description = (
            f"{len(evidence)} case(s) in {category}/{subfamily} produced "
            f"{FAILURE_MODE_TITLES[failure_mode]} -- "
            f"{FAILURE_MODE_DETAIL[failure_mode]}. "
            f"Severity is scored from the single highest-scoring instance; the "
            f"{len(evidence)} affected case(s) indicate reproducibility, not impact."
        )
        findings.append(
            Finding(
                finding_id=finding_id,
                title=title,
                category=category,
                severity_score=score,
                severity_tier=tier,
                description=description,
                remediation=REMEDIATIONS[failure_mode],
                evidence=evidence,
            )
        )
        finding_meta[finding_id] = {
            "subfamily": subfamily,
            "failure_mode": failure_mode,
            "validity_tiers": sorted(group["validity_tiers"]),
            # Reproducibility, kept separate from severity on purpose.
            "affected_cases": len(evidence),
        }
        finding_groups.append(FindingGroupRef(category, subfamily, failure_mode, evidence))

    return findings, finding_meta, finding_groups


# --------------------------------------------------------------------------------------
# per-version orchestration
# --------------------------------------------------------------------------------------


@dataclass
class VersionAnalysis:
    version: str
    category_stats: dict
    findings: list
    finding_meta: dict
    finding_groups: list
    diagnostic_observations: list
    review_cases: list
    drift: "drift.DriftSummary"
    operational: dict
    evaluable_attack_ids_by_mode: dict[str, set[str]]


def comparison_evidence(
    evaluations: list[CaseEvaluation], drift_summary: drift.DriftSummary,
    results: list[RunResult],
) -> dict[str, set[str]]:
    """Keep evaluability separate from whether a request was recorded as completed.

    Only actual automatically evaluated rows can rule out operational failures.
    A connection failure alone cannot establish that an HTTP weakness was fixed,
    though any positively observed failure (such as failed health) remains evidence.
    Flip resolution additionally needs an eligible clean/attacked prediction pair;
    clean rejection does not supply a prediction and cannot demonstrate invariance.
    """
    scored = {e.attack_id for e in evaluations if e.bucket in ("pass", "fail")}
    rows = {r.attack_id: r for r in results if r.case_type == "attack"}
    responses = {aid for aid in scored if rows[aid].status_code is not None}
    by_mode = {mode: set(responses) for mode in severity.BASE_WEIGHTS}
    # Health and request outcome are observed even when HTTP/prediction evidence is absent.
    for mode in (severity.FINDING_SERVICE_UNAVAILABLE, severity.FINDING_CONNECTION_FAILURE,
                 severity.FINDING_TIMEOUT):
        by_mode[mode] = set(scored)
    by_mode[severity.FINDING_SLOW_RESPONSE] |= {
        aid for aid in scored if rows[aid].latency_band == "timeout"
    }
    for evaluation in evaluations:
        for instance in evaluation.instances:
            by_mode[instance.failure_mode].add(evaluation.attack_id)
    by_mode[severity.FINDING_PREDICTION_FLIP] = {
        record.attack_id for record in drift_summary.records if record.status == "eligible"
    }
    return by_mode


def analyze_version(results: list[RunResult], manifest: dict[str, dict]) -> VersionAnalysis:
    validate_manifest(manifest)
    version = validate_rows(results)
    drift_summary = drift.compute_drift(results, manifest)
    drift_by_attack = {record.attack_id: record for record in drift_summary.records}

    evaluations: list[CaseEvaluation] = []
    for result in results:
        if result.case_type != "attack":
            continue
        meta = manifest.get(result.attack_id)
        if meta is None:
            raise ValueError(
                f"attack_id {result.attack_id!r} has a result but no manifest entry; "
                "the manifest is the only channel for oracle data and must be complete"
            )
        evaluations.append(evaluate_case(result, meta, drift_by_attack.get(result.attack_id)))

    category_stats = compute_category_stats(evaluations)
    operational = compute_operational_stats(evaluations)
    findings, finding_meta, finding_groups = build_findings(evaluations, version)

    diagnostic_observations = [
        {"attack_id": e.attack_id, "category": e.category, "subfamily": e.subfamily,
         "validity_tier": e.validity_tier, "oracle": manifest[e.attack_id]["oracle"],
         "tier_differs_from_diagnostic": e.validity_tier != TIER_DIAGNOSTIC}
        for e in evaluations if e.bucket == "diagnostic"
    ]
    review_cases = [
        {"attack_id": e.attack_id, "category": e.category, "subfamily": e.subfamily}
        for e in evaluations if e.bucket == "review"
    ]

    return VersionAnalysis(
        version=version,
        category_stats=category_stats,
        findings=findings,
        finding_meta=finding_meta,
        finding_groups=finding_groups,
        diagnostic_observations=diagnostic_observations,
        review_cases=review_cases,
        drift=drift_summary,
        operational=operational,
        evaluable_attack_ids_by_mode=comparison_evidence(evaluations, drift_summary, results),
    )


def format_rate(value: Optional[float]):
    """Zero eligible cases (None) reports as the literal string "N/A", never 0."""
    return "N/A" if value is None else value


def build_drift_block(drift_summary) -> dict:
    """The drift block, always carrying its baseline denominator alongside the rate.

    The brief requires the reduced denominator ("36 of 42 eligible") to be stated wherever
    a flip rate appears, so the two are emitted together and never separately.
    """
    census = drift_summary.baselines
    return {
        "eligible_comparisons": drift_summary.eligible,
        "qualifying_flips": drift_summary.qualifying_flips,
        "flip_rate": format_rate(drift_summary.flip_rate),
        "baseline_denominator": {
            "eligible": census.eligible,
            "total": census.total,
            "excluded_below_threshold": census.below_threshold,
            "excluded_baselines": [
                {"baseline_id": bid, "clean_confidence": conf}
                for bid, conf in census.below_threshold_ids
            ],
            "no_prediction": census.no_prediction_ids,
            "statement": census.summary_text,
            "threshold": drift.CLEAN_CONFIDENCE_THRESHOLD,
        },
        "confidence_change": {
            "mean_delta_on_flips": drift_summary.mean_flip_confidence_delta,
            "per_flip": [
                {
                    "attack_id": aid,
                    "clean_confidence": clean,
                    "attacked_confidence": attacked,
                    "delta": delta,
                }
                for aid, clean, attacked, delta in drift_summary.flip_confidence_deltas
            ],
        },
        "excluded": drift_summary.excluded,
        "unevaluable": drift_summary.unevaluable,
        "flip_attack_ids": drift_summary.flip_attack_ids,
    }


def validity_tier_census(analysis: VersionAnalysis) -> dict:
    """How much of the scored evidence is GOLD vs SILVER, for honest reporting."""
    census: dict[str, int] = {}
    for meta in analysis.finding_meta.values():
        for tier in meta["validity_tiers"]:
            census[tier] = census.get(tier, 0) + 1
    return census


def build_version_summary(analysis: VersionAnalysis, run_meta: dict) -> dict:
    return {
        "version": analysis.version,
        "coverage": run_meta.get("coverage", {}),
        "category_stats": {
            category: {**stats, "failure_rate": format_rate(stats["failure_rate"])}
            for category, stats in analysis.category_stats.items()
        },
        "operational": analysis.operational,
        "drift": build_drift_block(analysis.drift),
        "findings": [
            {
                "finding": dataclasses.asdict(finding),
                "subfamily": analysis.finding_meta[finding.finding_id]["subfamily"],
                "failure_mode": analysis.finding_meta[finding.finding_id]["failure_mode"],
                "validity_tiers": analysis.finding_meta[finding.finding_id]["validity_tiers"],
                "affected_cases": analysis.finding_meta[finding.finding_id]["affected_cases"],
            }
            for finding in analysis.findings
        ],
        "validity_tier_census": validity_tier_census(analysis),
        "diagnostic_observations": analysis.diagnostic_observations,
        "review_cases": analysis.review_cases,
        "limitations": list(LIMITATION_NOTES),
    }


def build_comparison_summary(
    v1_analysis: VersionAnalysis, v2_analysis: VersionAnalysis, meta_v1: dict, meta_v2: dict
) -> dict:
    """Build the V1-vs-V2 comparison JSON.

    When the planned-suite fingerprint or the manifest hash disagrees, the brief is
    explicit: "do not make whole-suite equivalence claims at all." That means actually
    withholding the derived comparison fields (resolved/remaining/newly-appearing findings
    and the paired category-rate deltas), not just reporting the mismatch alongside them --
    a flag next to a claim does not stop a report template from rendering the claim.
    """
    result = compare.compare_versions(
        meta_v1=meta_v1,
        meta_v2=meta_v2,
        v1_groups=v1_analysis.finding_groups,
        v2_groups=v2_analysis.finding_groups,
        v2_evaluable_attack_ids_by_mode=v2_analysis.evaluable_attack_ids_by_mode,
        v1_evaluable_attack_ids_by_mode=v1_analysis.evaluable_attack_ids_by_mode,
    )

    summary = {
        "fingerprints": {
            "planned_match": result.fingerprints.planned_match,
            "manifest_match": result.fingerprints.manifest_match,
            "whole_suite_comparable": result.fingerprints.whole_suite_comparable,
        },
        "coverage": {
            "v1": result.coverage.v1_coverage,
            "v2": result.coverage.v2_coverage,
            "matched_count": len(result.coverage.matched),
            "v1_only_count": len(result.coverage.v1_only),
            "v2_only_count": len(result.coverage.v2_only),
            "unavailable_count": len(result.coverage.unavailable),
            # Unmatched evidence, listed not just counted: these are the cases where a
            # before/after claim is not supported by both sides.
            "v1_only": result.coverage.v1_only,
            "v2_only": result.coverage.v2_only,
            "unavailable": result.coverage.unavailable,
        },
        "limitations": list(LIMITATION_NOTES),
    }

    if not result.fingerprints.whole_suite_comparable:
        summary["comparison_withheld_reason"] = (
            "planned-suite fingerprint or manifest hash differs between V1 and V2; "
            "whole-suite equivalence claims (resolved/remaining/newly-appearing findings, "
            "paired category failure-rate deltas) are withheld rather than reported"
        )
        return summary

    summary.update(
        {
            # Four operational numbers kept distinct on both sides: unhandled 5xx,
            # timeouts, connection failures, and observed service unavailability.
            "operational": {"v1": v1_analysis.operational, "v2": v2_analysis.operational},
            "drift": {
                "v1_qualifying_flips": v1_analysis.drift.qualifying_flips,
                "v2_qualifying_flips": v2_analysis.drift.qualifying_flips,
                "v1_eligible_comparisons": v1_analysis.drift.eligible,
                "v2_eligible_comparisons": v2_analysis.drift.eligible,
                "v1_flip_rate": format_rate(v1_analysis.drift.flip_rate),
                "v2_flip_rate": format_rate(v2_analysis.drift.flip_rate),
                # The reduced denominator travels with every flip rate.
                "v1_baseline_denominator": v1_analysis.drift.baselines.summary_text,
                "v2_baseline_denominator": v2_analysis.drift.baselines.summary_text,
            },
            "category_failure_rates": {
                category: {
                    version: {"failed": stats[category]["failed"],
                              "eligible": stats[category]["eligible"],
                              "rate": format_rate(stats[category]["failure_rate"])}
                    for version, stats in (("v1", v1_analysis.category_stats),
                                           ("v2", v2_analysis.category_stats))
                }
                for category in CATEGORIES
            },
            "findings_resolved": [
                list(r.key) for r in result.resolutions if r.status == "resolved"
            ],
            "findings_remaining": [
                {"key": list(r.key), "remaining_ids": r.remaining_ids}
                for r in result.resolutions if r.status == "remaining"
            ],
            "findings_unavailable": [
                {"key": list(r.key), "unavailable_ids": r.unavailable_ids}
                for r in result.resolutions if r.status == "unavailable"
            ],
            "findings_newly_appearing": [list(g.key) for g in result.newly_appearing],
            "inconclusive_new_findings": [
                {"key": list(g.key), "unavailable_ids": g.evidence_ids}
                for g in result.inconclusive_new
            ],
            "finding_comparisons": [
                {"key": list(r.key), "status": r.status,
                 "remaining_ids": r.remaining_ids, "unavailable_ids": r.unavailable_ids,
                 "improved_ids": r.improved_ids}
                for r in result.resolutions
            ],
            "new_finding_evidence": [
                {"key": list(g.key), "regression_ids": g.evidence_ids}
                for g in result.newly_appearing
            ],
        }
    )
    return summary


# --------------------------------------------------------------------------------------
# file loading + full pipeline
# --------------------------------------------------------------------------------------


def load_manifest(path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle, object_pairs_hook=_unique_object)
    validate_manifest(manifest)
    return manifest


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_results(path) -> list[RunResult]:
    """Read one version's JSONL result rows.

    A malformed line is raised, never skipped. Silently dropping a row would quietly
    shrink the evidence base and desynchronise the results file from the coverage lists
    in run_meta, which is exactly the "absence of evidence read as evidence of a fix"
    failure the comparison is built to prevent. The error names the file, the line and
    the offending text, because a bare JSONDecodeError gives the reader nothing to act on
    -- a truncated or half-written results file is the realistic cause.
    """
    results = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line, object_pairs_hook=_unique_object)
            except ValueError as exc:
                raise ValueError(
                    f"{path} line {line_number} is not valid JSON ({exc}). "
                    f"Offending text: {line[:120]!r}. The results file looks truncated or "
                    "partially written; re-run that version rather than analysing it."
                ) from exc
            try:
                results.append(RunResult(**row))
            except TypeError as exc:
                raise ValueError(f"{path} line {line_number} does not match RunResult: {exc}") from exc
    validate_rows(results)
    return results


def load_run_meta(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_unique_object)


def run_analysis(
    *,
    manifest_path,
    results_v1_path,
    results_v2_path,
    meta_v1_path,
    meta_v2_path,
    manifest_v2_path=None,
) -> dict:
    """Load every input, run both versions, and return findings + summary JSON for each."""
    # Hash and parse the same bytes, so scoring cannot read a different file snapshot.
    manifest_bytes = Path(manifest_path).read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
    validate_manifest(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_v2_sha = manifest_sha
    if manifest_v2_path is not None:
        v2_bytes = Path(manifest_v2_path).read_bytes()
        manifest_v2_sha = hashlib.sha256(v2_bytes).hexdigest()
        if v2_bytes != manifest_bytes:
            raise ValueError("V1 and V2 manifest files differ; cannot score both with one oracle set")
    results_v1 = load_results(results_v1_path)
    results_v2 = load_results(results_v2_path)
    meta_v1 = load_run_meta(meta_v1_path)
    meta_v2 = load_run_meta(meta_v2_path)

    validate_run(results_v1, meta_v1, manifest, "v1", manifest_sha)
    validate_run(results_v2, meta_v2, manifest, "v2", manifest_v2_sha)
    if (meta_v1["fingerprints"]["planned_suite_sha256"] == meta_v2["fingerprints"]["planned_suite_sha256"]
            and meta_v1["case_ids"]["planned"] != meta_v2["case_ids"]["planned"]):
        raise ValueError("matching planned fingerprints have inconsistent planned case IDs/order")
    v1_attacks = {r.attack_id: r for r in results_v1 if r.case_type == "attack"}
    for row in results_v2:
        if row.case_type == "attack" and row.attack_id in v1_attacks:
            if row.baseline_id != v1_attacks[row.attack_id].baseline_id:
                raise ValueError(f"{row.attack_id}: baseline association differs across versions")

    analysis_v1 = analyze_version(results_v1, manifest)
    analysis_v2 = analyze_version(results_v2, manifest)
    analysis_v1.version = "v1"
    analysis_v2.version = "v2"

    return {
        "schema_version": 2,
        "findings_v1": analysis_v1.findings,
        "findings_v2": analysis_v2.findings,
        "summary_v1": build_version_summary(analysis_v1, meta_v1),
        "summary_v2": build_version_summary(analysis_v2, meta_v2),
        "comparison": build_comparison_summary(analysis_v1, analysis_v2, meta_v1, meta_v2),
    }


def run_analysis_from_dir(results_dir: str = "results") -> dict:
    """Accept runner files in one directory or preserved v1/ and v2/ subdirectories."""
    base = Path(results_dir)
    if not (base / DEFAULT_MANIFEST_NAME).exists() and (base / "v1" / DEFAULT_MANIFEST_NAME).exists():
        return run_analysis(
            manifest_path=base / "v1" / DEFAULT_MANIFEST_NAME,
            manifest_v2_path=base / "v2" / DEFAULT_MANIFEST_NAME,
            results_v1_path=base / "v1" / "results_v1.jsonl",
            results_v2_path=base / "v2" / "results_v2.jsonl",
            meta_v1_path=base / "v1" / "run_meta_v1.json",
            meta_v2_path=base / "v2" / "run_meta_v2.json",
        )
    return run_analysis(
        manifest_path=base / DEFAULT_MANIFEST_NAME,
        results_v1_path=base / "results_v1.jsonl",
        results_v2_path=base / "results_v2.jsonl",
        meta_v1_path=base / "run_meta_v1.json",
        meta_v2_path=base / "run_meta_v2.json",
    )


if __name__ == "__main__":
    import sys

    output = run_analysis_from_dir(sys.argv[1] if len(sys.argv) > 1 else "results")
    print(json.dumps({"schema_version": output["schema_version"],
                     "summary_v1": output["summary_v1"], "summary_v2": output["summary_v2"],
                     "comparison": output["comparison"]}, indent=2, allow_nan=False))
