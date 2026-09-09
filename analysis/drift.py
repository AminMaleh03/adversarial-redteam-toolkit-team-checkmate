"""Detects prediction drift between a clean result and its attacked counterpart.

Drift is model-against-model: a clean baseline result compared against the attacked result
derived from it, both from the *same* endpoint version. The dataset label the baseline was
built to represent is context only and never enters this comparison.

Oracle/validity-tier vocabulary is mirrored here as plain string constants rather than
imported from ``attacks.metadata``: analysis never imports from ``attacks/`` (see AGENTS.md),
and the manifest JSON -- not the Python module -- is the actual interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contract import RunResult

ORACLE_LABEL_MATCH_BASELINE = "label_should_match_baseline"
ORACLE_REQUEST_REJECTED = "request_should_be_rejected_cleanly"
ORACLE_GRACEFUL_OR_TRUNCATE = "endpoint_should_fail_gracefully_or_apply_documented_truncation"
ORACLE_STAY_AVAILABLE = "endpoint_should_stay_available"
ORACLE_NO_INFO_LEAK = "error_response_must_not_leak_internals"
ORACLE_DIAGNOSTIC = "diagnostic_no_fixed_oracle"

# The complete tier vocabulary the manifest can carry. Only REVIEW and DIAGNOSTIC are
# branched on anywhere -- GOLD and SILVER both go through the normal automatic logic, so
# they are never tested for. They are declared here so this file documents the whole set
# a reader will meet in manifest.json, and so a typo is a NameError rather than a silent
# mismatch. The tier itself is preserved per finding (see analyze.build_findings) so the
# report can distinguish strong evidence from weaker semantic assumptions.
TIER_GOLD = "GOLD"
TIER_SILVER = "SILVER"
TIER_REVIEW = "REVIEW"
TIER_DIAGNOSTIC = "DIAGNOSTIC"

CLEAN_CONFIDENCE_THRESHOLD = 0.6

# Why a case is excluded from the flip denominator: a policy choice, not missing data.
EXCLUDE_MISSING_METADATA = "missing_metadata"
EXCLUDE_NOT_LABEL_ORACLE = "oracle_not_label_match_baseline"
EXCLUDE_DIAGNOSTIC = "diagnostic"
EXCLUDE_REVIEW_UNRESOLVED = "review_unresolved"
EXCLUDE_LOW_CLEAN_CONFIDENCE = "low_clean_confidence"

# Why a case can't be judged at all: missing data, not policy.
UNEVAL_MISSING_CLEAN_RESULT = "missing_clean_result"
UNEVAL_MISSING_ATTACKED_RESULT = "missing_attacked_result"
UNEVAL_MISSING_CLEAN_PREDICTION = "missing_clean_prediction"
UNEVAL_MISSING_ATTACKED_PREDICTION = "missing_attacked_prediction"


@dataclass
class DriftRecord:
    """The drift verdict for one (attack_id, baseline_id) pair in one version."""

    attack_id: str
    baseline_id: str
    version: str
    # "eligible", "excluded", or "unevaluable".
    status: str
    reason: Optional[str] = None
    qualifying_flip: bool = False
    clean_label: Optional[str] = None
    clean_confidence: Optional[float] = None
    attacked_label: Optional[str] = None
    attacked_confidence: Optional[float] = None
    confidence_delta: Optional[float] = None


@dataclass
class BaselineCensus:
    """How many clean baselines are usable as a drift reference at all.

    This is the "36 of 42" denominator. It has to be stated wherever a flip rate appears,
    and it cannot be reconstructed downstream from the attack-level exclusion count,
    because the number of derived attacks per baseline is not uniform.
    """

    total: int = 0
    eligible: int = 0
    below_threshold: int = 0
    below_threshold_ids: list = field(default_factory=list)   # (baseline_id, confidence)
    no_prediction_ids: list = field(default_factory=list)

    @property
    def summary_text(self) -> str:
        return f"{self.eligible} of {self.total} baselines eligible for flip scoring"


def baseline_confidence_census(results: list[RunResult]) -> BaselineCensus:
    """Count clean baseline predictions at or above the 0.6 threshold, for one version.

    The brief asks for this the moment a real run lands, not at report-writing time: if
    too few baselines clear 0.6, the answer is to discuss expanding the baseline with the
    same fixed sampling procedure, never to lower the threshold.
    """
    census = BaselineCensus()
    for result in results:
        if result.case_type != "baseline":
            continue
        census.total += 1
        if result.label is None or result.confidence is None:
            census.no_prediction_ids.append(result.baseline_id)
        elif result.confidence >= CLEAN_CONFIDENCE_THRESHOLD:
            census.eligible += 1
        else:
            census.below_threshold += 1
            census.below_threshold_ids.append((result.baseline_id, result.confidence))
    census.below_threshold_ids.sort(key=lambda pair: (pair[1], pair[0]))
    census.no_prediction_ids.sort()
    return census


@dataclass
class DriftSummary:
    """Aggregate drift statistics for one endpoint version."""

    eligible: int = 0
    qualifying_flips: int = 0
    excluded: dict = field(default_factory=dict)
    unevaluable: dict = field(default_factory=dict)
    flip_attack_ids: list = field(default_factory=list)
    records: list = field(default_factory=list)
    baselines: BaselineCensus = field(default_factory=BaselineCensus)

    @property
    def flip_rate(self) -> Optional[float]:
        """None means N/A (zero eligible comparisons), never 0."""
        if self.eligible == 0:
            return None
        return self.qualifying_flips / self.eligible

    @property
    def flip_confidence_deltas(self) -> list:
        """(attack_id, clean_confidence, attacked_confidence, delta) for qualifying flips."""
        return [
            (r.attack_id, r.clean_confidence, r.attacked_confidence, r.confidence_delta)
            for r in self.records
            if r.status == "eligible" and r.qualifying_flip and r.confidence_delta is not None
        ]

    @property
    def mean_flip_confidence_delta(self) -> Optional[float]:
        deltas = [row[3] for row in self.flip_confidence_deltas]
        if not deltas:
            return None
        return sum(deltas) / len(deltas)


def has_usable_prediction(result: Optional[RunResult]) -> bool:
    return result is not None and result.label is not None and result.confidence is not None


def evaluate_pair(
    attack_id: str,
    baseline_id: str,
    version: str,
    clean: Optional[RunResult],
    attacked: Optional[RunResult],
    meta: Optional[dict],
) -> DriftRecord:
    """Judge one derived-attack / clean-baseline pair against the frozen flip rule."""
    if meta is None:
        return DriftRecord(attack_id, baseline_id, version, "excluded", EXCLUDE_MISSING_METADATA)
    if meta.get("oracle") != ORACLE_LABEL_MATCH_BASELINE:
        return DriftRecord(attack_id, baseline_id, version, "excluded", EXCLUDE_NOT_LABEL_ORACLE)
    if meta.get("validity_tier") == TIER_DIAGNOSTIC:
        return DriftRecord(attack_id, baseline_id, version, "excluded", EXCLUDE_DIAGNOSTIC)
    if meta.get("validity_tier") == TIER_REVIEW:
        return DriftRecord(attack_id, baseline_id, version, "excluded", EXCLUDE_REVIEW_UNRESOLVED)

    if clean is None:
        return DriftRecord(attack_id, baseline_id, version, "unevaluable", UNEVAL_MISSING_CLEAN_RESULT)
    if attacked is None:
        return DriftRecord(
            attack_id, baseline_id, version, "unevaluable", UNEVAL_MISSING_ATTACKED_RESULT
        )
    if not has_usable_prediction(clean):
        return DriftRecord(
            attack_id, baseline_id, version, "unevaluable", UNEVAL_MISSING_CLEAN_PREDICTION
        )

    if clean.confidence < CLEAN_CONFIDENCE_THRESHOLD:
        return DriftRecord(
            attack_id, baseline_id, version, "excluded", EXCLUDE_LOW_CLEAN_CONFIDENCE,
            clean_label=clean.label, clean_confidence=clean.confidence,
        )

    if not has_usable_prediction(attacked):
        return DriftRecord(
            attack_id, baseline_id, version, "unevaluable", UNEVAL_MISSING_ATTACKED_PREDICTION,
            clean_label=clean.label, clean_confidence=clean.confidence,
        )

    flip = attacked.label != clean.label
    return DriftRecord(
        attack_id, baseline_id, version, "eligible", None,
        qualifying_flip=flip,
        clean_label=clean.label,
        clean_confidence=clean.confidence,
        attacked_label=attacked.label,
        attacked_confidence=attacked.confidence,
        confidence_delta=attacked.confidence - clean.confidence,
    )


def compute_drift(results: list[RunResult], manifest: dict[str, dict]) -> DriftSummary:
    """Compute drift over one version's results (baseline rows + attack rows mixed).

    Pairing never crosses versions: only baseline rows found in this same ``results``
    list are used as the clean reference, so a V1 attack can never be compared against
    a V2 clean result. Standalone attacks (no baseline_id) are skipped cleanly -- they
    never enter any counter, eligible or excluded.
    """
    clean_by_baseline: dict[str, RunResult] = {}
    for result in results:
        if result.case_type == "baseline":
            clean_by_baseline[result.baseline_id] = result

    summary = DriftSummary(baselines=baseline_confidence_census(results))
    for result in results:
        if result.case_type != "attack" or result.baseline_id is None:
            continue
        meta = manifest.get(result.attack_id)
        clean = clean_by_baseline.get(result.baseline_id)
        record = evaluate_pair(
            result.attack_id, result.baseline_id, result.version, clean, result, meta
        )
        summary.records.append(record)
        if record.status == "eligible":
            summary.eligible += 1
            if record.qualifying_flip:
                summary.qualifying_flips += 1
                summary.flip_attack_ids.append(record.attack_id)
        elif record.status == "excluded":
            summary.excluded[record.reason] = summary.excluded.get(record.reason, 0) + 1
        else:
            summary.unevaluable[record.reason] = summary.unevaluable.get(record.reason, 0) + 1
    return summary
