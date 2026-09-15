"""Additional-evaluation (OCES) analysis: paraphrase and distractor families.

Exactly two families, under the existing invariant / ``label_should_match_baseline``
oracle. There is no negation family, no directional oracle, no score-drop threshold and no
new severity weight: those were removed from the plan and are not implemented here.

What a violation means
----------------------
A changed prediction is a **consistency** failure under a transformation that was intended
to preserve the label. It does not by itself establish which prediction is correct. Where
the clean baseline was itself misclassified against its own reference label, an induced
change cannot be called induced *mis*classification, so the two are counted separately.

Author exposure
---------------
These cases were authored after the evaluated defenses were frozen, by authors who knew
what those defenses were. That is stated verbatim on every emitted block and the evaluation
is never described as a blind holdout or as design-independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contract import OCES_FAMILIES, OCES_FAMILY_DISTRACTOR, OCES_FAMILY_PARAPHRASE

from analysis.coverage import rate
from analysis.drift import (
    CLEAN_CONFIDENCE_THRESHOLD,
    TIER_DIAGNOSTIC,
    TIER_REVIEW,
)

# Exactly one of these per planned case per target.
STATUS_MEETS = "meets_expectation"
STATUS_VIOLATES = "violates_expectation"
STATUS_EXCLUDED = "excluded"
STATUS_UNEVALUABLE = "unevaluable"
STATUS_NOT_EXECUTED = "not_executed"
STATUSES = (STATUS_MEETS, STATUS_VIOLATES, STATUS_EXCLUDED, STATUS_UNEVALUABLE,
            STATUS_NOT_EXECUTED)

# Only the first two enter a semantic rate.
SCORED_STATUSES = (STATUS_MEETS, STATUS_VIOLATES)

AUTHOR_EXPOSURE_STATEMENT = (
    "Additional evaluation authored after the evaluated defenses were frozen; the authors "
    "were aware of the defenses; not a blind holdout."
)

INTERPRETATION_LIMITS = (
    "Valid JSON, an accepted type, bounded tokens and an unchanged clean_text result "
    "establish only that those specific input gates accepted the text unchanged. They do "
    "not show the exception handler is irrelevant and they do not show semantic "
    "preservation.",
    "A changed prediction is a consistency failure under an intended label-preserving "
    "change. It does not establish which prediction is correct.",
)


@dataclass
class CaseOutcome:
    """One planned OCES case, for one target."""

    case_id: str
    family: str
    target_id: str
    status: str
    reason: str | None = None
    clean_label: str | None = None
    clean_confidence: float | None = None
    observed_label: str | None = None
    observed_confidence: float | None = None
    validity_tier: str | None = None
    clean_matches_reference: bool | None = None
    evidence_refs: list = field(default_factory=list)


def classify_case(
    *,
    case_id: str,
    family: str,
    target_id: str,
    meta: dict,
    clean,
    attacked,
    reference_label: str | None = None,
) -> CaseOutcome:
    """Give one planned case exactly one status for this target.

    Ordering matters. Tier exclusions come first, because a REVIEW or DIAGNOSTIC case is
    never automatically scored whatever the rows show. Then missing execution, then
    missing predictions -- an absent prediction is never counted as successful invariance.
    """
    if family not in OCES_FAMILIES:
        raise ValueError(f"{case_id}: unsupported OCES family {family!r}")

    tier = (meta or {}).get("validity_tier")
    common = dict(case_id=case_id, family=family, target_id=target_id, validity_tier=tier)

    if tier == TIER_DIAGNOSTIC:
        return CaseOutcome(**common, status=STATUS_EXCLUDED,
                           reason="diagnostic tier: observation only, never auto-scored")
    if tier == TIER_REVIEW:
        return CaseOutcome(**common, status=STATUS_EXCLUDED,
                           reason="REVIEW tier: needs human review before it can be trusted")

    if attacked is None:
        return CaseOutcome(**common, status=STATUS_NOT_EXECUTED,
                           reason="no recorded result row for this case on this target")
    evidence = [f"attack:{case_id}"]
    if clean is None:
        return CaseOutcome(**common, status=STATUS_UNEVALUABLE,
                           reason="no clean baseline result for the same target",
                           evidence_refs=evidence)
    if clean.label is None or clean.confidence is None:
        return CaseOutcome(**common, status=STATUS_UNEVALUABLE,
                           reason="clean baseline produced no usable prediction",
                           evidence_refs=evidence)
    if clean.confidence < CLEAN_CONFIDENCE_THRESHOLD:
        return CaseOutcome(**common, status=STATUS_EXCLUDED,
                           reason=f"clean confidence {clean.confidence} below the "
                                  f"{CLEAN_CONFIDENCE_THRESHOLD} threshold",
                           clean_label=clean.label, clean_confidence=clean.confidence,
                           evidence_refs=evidence)
    if attacked.label is None:
        # Operational failure stays visible; it is not a semantic success.
        return CaseOutcome(**common, status=STATUS_UNEVALUABLE,
                           reason=(f"no prediction recorded (status {attacked.status_code}, "
                                   f"band {attacked.latency_band})"),
                           clean_label=clean.label, clean_confidence=clean.confidence,
                           evidence_refs=evidence)

    clean_matches_reference = (
        None if reference_label is None else clean.label == reference_label
    )
    status = STATUS_MEETS if attacked.label == clean.label else STATUS_VIOLATES
    return CaseOutcome(
        **common,
        status=status,
        reason=None if status == STATUS_MEETS else "top label changed under an intended "
                                                   "label-preserving transformation",
        clean_label=clean.label,
        clean_confidence=clean.confidence,
        observed_label=attacked.label,
        observed_confidence=attacked.confidence,
        clean_matches_reference=clean_matches_reference,
        evidence_refs=evidence,
    )


def summarise(outcomes: list, *, target_id: str) -> dict:
    """Per-family and overall counts for one target."""
    families = {}
    for family in OCES_FAMILIES:
        rows = [o for o in outcomes if o.family == family]
        counts = {status: sum(1 for o in rows if o.status == status) for status in STATUSES}
        scored = counts[STATUS_MEETS] + counts[STATUS_VIOLATES]
        violations = [o for o in rows if o.status == STATUS_VIOLATES]
        # Only a violation whose clean prediction matched its reference label can be
        # described as induced misclassification; the rest are consistency failures.
        induced = [o for o in violations if o.clean_matches_reference is True]
        families[family] = {
            "planned": len(rows),
            "statuses": counts,
            "violation_rate": rate(counts[STATUS_VIOLATES], scored),
            "violation_case_ids": [o.case_id for o in violations],
            "induced_misclassification": {
                "count": len(induced),
                "case_ids": [o.case_id for o in induced],
                "note": ("Counted only where the clean prediction matched its reference "
                         "label; otherwise a change is a consistency failure and the "
                         "correct label is not established."),
            },
        }

    all_counts = {status: sum(1 for o in outcomes if o.status == status) for status in STATUSES}
    scored_total = all_counts[STATUS_MEETS] + all_counts[STATUS_VIOLATES]
    return {
        "target_id": target_id,
        "planned": len(outcomes),
        "statuses": all_counts,
        "violation_rate": rate(all_counts[STATUS_VIOLATES], scored_total),
        "families": families,
        "author_exposure": AUTHOR_EXPOSURE_STATEMENT,
        "interpretation_limits": list(INTERPRETATION_LIMITS),
    }


def build_oces_block(
    *,
    outcomes_by_target: dict,
    seed_hashes: dict | None = None,
) -> dict:
    """The ``oces`` block of a v3 evaluation.

    Kept separate from the original core results and from any other model's: these rates
    describe this suite on this target and are not comparable with the core suite.
    """
    per_target = {
        target_id: summarise(outcomes, target_id=target_id)
        for target_id, outcomes in outcomes_by_target.items()
    }
    cases = {
        target_id: [
            {
                "case_id": o.case_id, "family": o.family, "status": o.status,
                "reason": o.reason, "validity_tier": o.validity_tier,
                "clean_label": o.clean_label, "clean_confidence": o.clean_confidence,
                "observed_label": o.observed_label,
                "observed_confidence": o.observed_confidence,
                "clean_matches_reference": o.clean_matches_reference,
                "evidence_refs": o.evidence_refs,
            }
            for o in outcomes
        ]
        for target_id, outcomes in outcomes_by_target.items()
    }
    return {
        "families": list(OCES_FAMILIES),
        "summaries": per_target,
        "cases": cases,
        "provenance": dict(seed_hashes or {}),
        "author_exposure": AUTHOR_EXPOSURE_STATEMENT,
        "separation_note": (
            "OCES findings and rates are reported separately from the original core suite "
            "and from other models. The suites test different things on different data."
        ),
    }
