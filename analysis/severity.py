"""Scores an issue and maps the score onto a Critical, High, Medium or Low tier.

Severity belongs to the underlying weakness, not to how many attacks reproduced it: a
grouped finding is scored once, from its single highest-scoring qualifying instance, and
the base weights and magnitude adjustments below are frozen -- do not change them without
team agreement, since a changed weight silently changes every result.
"""

from __future__ import annotations

from typing import Optional

# -- finding kinds (failure modes a grouped finding can represent) --------------------

FINDING_SERVICE_UNAVAILABLE = "service_unavailable"
FINDING_UNHANDLED_5XX = "unhandled_5xx"
FINDING_INFO_LEAK = "info_leak"
FINDING_TIMEOUT = "timeout"
FINDING_PREDICTION_FLIP = "prediction_flip"
FINDING_INVALID_INPUT_ACCEPTED = "invalid_input_accepted"
FINDING_SLOW_RESPONSE = "slow_response"

# -- frozen base weights ---------------------------------------------------------------

BASE_WEIGHTS: dict[str, float] = {
    FINDING_SERVICE_UNAVAILABLE: 100.0,
    FINDING_UNHANDLED_5XX: 70.0,
    FINDING_INFO_LEAK: 65.0,
    FINDING_TIMEOUT: 60.0,
    FINDING_PREDICTION_FLIP: 40.0,
    FINDING_INVALID_INPUT_ACCEPTED: 30.0,
    FINDING_SLOW_RESPONSE: 20.0,
}

# -- frozen magnitude adjustments -------------------------------------------------------

FLIP_ADJUSTMENT_SCALE = 50.0
FLIP_ADJUSTMENT_CAP = 20.0

LEAK_STACK_OR_PATH_ADJUSTMENT = 20.0
LEAK_INTERNAL_NAMES_ADJUSTMENT = 5.0

SIZE_ADJUSTMENTS: dict[str, float] = {
    "oversized_100kb": 20.0,
    "oversized_1mb": 10.0,
    "oversized_10mb": 0.0,
}

SLOW_ADJUSTMENT_SCALE = 2.0
SLOW_ADJUSTMENT_CAP = 16.0
SLOW_BAND_FLOOR_SECONDS = 2.0

INVALID_INPUT_CONFIDENT_ADJUSTMENT = 10.0
INVALID_INPUT_CONFIDENCE_THRESHOLD = 0.6

# -- frozen tiers ------------------------------------------------------------------------

TIER_CRITICAL = "Critical"
TIER_HIGH = "High"
TIER_MEDIUM = "Medium"
TIER_LOW = "Low"


def tier_for_score(score: float) -> str:
    if score >= 85:
        return TIER_CRITICAL
    if score >= 60:
        return TIER_HIGH
    if score >= 35:
        return TIER_MEDIUM
    return TIER_LOW


def flip_adjustment(clean_confidence: Optional[float]) -> float:
    """(clean_confidence - 0.6) * 50, capped at +20, floored at 0.

    A flip is only ever scored when it already qualified (clean_confidence >= 0.6), so the
    floor is a defensive guard, not an expected path.
    """
    if clean_confidence is None:
        return 0.0
    return max(0.0, min((clean_confidence - 0.6) * FLIP_ADJUSTMENT_SCALE, FLIP_ADJUSTMENT_CAP))


def leak_adjustment(leak_kind: Optional[str]) -> float:
    """+20 for a stack trace or absolute path, +5 for internal names only, else 0."""
    if leak_kind == "stack_or_path":
        return LEAK_STACK_OR_PATH_ADJUSTMENT
    if leak_kind == "internal_names":
        return LEAK_INTERNAL_NAMES_ADJUSTMENT
    return 0.0


def size_adjustment(subfamily: Optional[str]) -> float:
    """Read the oversized tier from the subfamily name; the manifest has no size field."""
    return SIZE_ADJUSTMENTS.get(subfamily, 0.0)


def slow_response_adjustment(seconds: Optional[float]) -> float:
    """(seconds - 2) * 2, capped at +16, floored at 0."""
    if seconds is None:
        return 0.0
    return max(0.0, min((seconds - SLOW_BAND_FLOOR_SECONDS) * SLOW_ADJUSTMENT_SCALE, SLOW_ADJUSTMENT_CAP))


def invalid_input_adjustment(accepted_confidence: Optional[float]) -> float:
    """+10 if the endpoint answered with confidence at or above 0.6."""
    if accepted_confidence is not None and accepted_confidence >= INVALID_INPUT_CONFIDENCE_THRESHOLD:
        return INVALID_INPUT_CONFIDENT_ADJUSTMENT
    return 0.0


def compute_severity(failure_mode: str, **context) -> tuple[float, str]:
    """Score one instance of one failure mode. Each adjustment applies only to its own kind.

    Recognised context keys, by failure_mode:
      prediction_flip         -> clean_confidence
      info_leak                -> leak_kind ("stack_or_path" | "internal_names" | None)
      invalid_input_accepted   -> accepted_confidence
      slow_response            -> seconds
      unhandled_5xx / timeout  -> subfamily (only oversized_* subfamilies adjust)
      service_unavailable      -> (no adjustment; always exactly the base weight)
    """
    if failure_mode not in BASE_WEIGHTS:
        raise ValueError(f"unknown failure mode {failure_mode!r}")

    base = BASE_WEIGHTS[failure_mode]
    adjustment = 0.0

    if failure_mode == FINDING_PREDICTION_FLIP:
        adjustment = flip_adjustment(context.get("clean_confidence"))
    elif failure_mode == FINDING_INFO_LEAK:
        adjustment = leak_adjustment(context.get("leak_kind"))
    elif failure_mode == FINDING_INVALID_INPUT_ACCEPTED:
        adjustment = invalid_input_adjustment(context.get("accepted_confidence"))
    elif failure_mode == FINDING_SLOW_RESPONSE:
        adjustment = slow_response_adjustment(context.get("seconds"))
    elif failure_mode in (FINDING_UNHANDLED_5XX, FINDING_TIMEOUT):
        adjustment = size_adjustment(context.get("subfamily"))

    # Round away float noise (e.g. 19.499999999999996) before it can shift a tier boundary.
    score = round(base + adjustment, 6)
    return score, tier_for_score(score)


def score_group(instance_scores: list[float]) -> tuple[float, str]:
    """A grouped finding scores its single highest qualifying instance, never a sum."""
    if not instance_scores:
        raise ValueError("a finding group needs at least one scored instance")
    best = max(instance_scores)
    return best, tier_for_score(best)
