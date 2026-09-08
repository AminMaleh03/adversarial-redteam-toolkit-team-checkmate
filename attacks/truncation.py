"""
Category 6 - truncation and long-semantic input (derived).

Three distinct things live here, each with the CORRECT relation/oracle (the earlier version
wrongly declared an over-limit case both "label must match" and "request should be rejected"
at once -- a contradiction, since a rejected request has no label to compare):

1. Positional signal placement, UNDER the limit -> invariance test. Bury a labelled
   sentence at the start/end of short neutral filler; both V1 and V2 run, so the label
   should not change with position. (CheckList: robustness to irrelevant additions.)

2. Positional signal placement, OVER the limit -> boundary test, NOT invariance. V2 should
   reject on length before inference; V1 never truncates and feeds the whole thing to the
   model. Oracle is graceful-rejection / documented-truncation. If V1 does return a
   prediction, the baseline comparison is kept only as diagnostic context in notes.

3. Actual truncation of the SIGNAL itself (head/tail cut) -> DIAGNOSTIC. Cutting a sentence
   can change its meaning for a human too, so there is no fixed label oracle; we inspect
   whether the model degrades, never auto-score it as a vulnerability.

The over/under split is by an assumed limit (word estimate); the real threshold is measured
by the runner -- Hugging Face truncation is configurable, so we do not assert V1 "processes
everything", only that V1 never truncates by construction (model.py) while V2 rejects.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import metadata as md

# Neutral, emotion-free filler so any predicted emotion must come from the buried signal.
_FILLER_UNIT = "the document also records routine administrative details for later reference"
_SHORT_FILLER_WORDS = 40      # comfortably under a ~512-token limit
_LONG_FILLER_WORDS = 600      # comfortably over it


def _filler(word_count: int) -> str:
    unit = _FILLER_UNIT.split()
    return " ".join((unit * ((word_count // len(unit)) + 1))[:word_count])


def _add(cases, baseline, subfamily, attacked, *, relation, oracle, tier, risk,
         position, sanitizer, http, notes):
    aid = f"{baseline.baseline_id}.truncation.{subfamily}"
    case = AttackCase(
        attack_id=aid, baseline_id=baseline.baseline_id, category="truncation",
        original_text=baseline.text, attacked_text=attacked,
    )
    meta = md.AttackMetadata(
        attack_id=aid, family="truncation", subfamily=subfamily,
        relation=relation, oracle=oracle,
        source="CheckList (robustness to irrelevant additions)",
        validity_tier=tier, semantic_risk=risk, requires_baseline=True,
        position=position, boundary_source="approximate_word_estimate",
        expected_sanitizer_behavior=sanitizer, expected_http_behavior=http, notes=notes,
    )
    cases.append(md.register(case, meta))


def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Build the per-baseline truncation/long-input cases for one clean sentence."""
    cases: list[AttackCase] = []
    signal = baseline.text
    short_filler = _filler(_SHORT_FILLER_WORDS)
    long_filler = _filler(_LONG_FILLER_WORDS)

    # 1. Under-limit positional invariance.
    _add(cases, baseline, "signal_start_short", f"{signal} {short_filler}",
         relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
         tier=md.TIER_SILVER, risk="low", position="start",
         sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
         notes="Signal first, short filler after (under limit); position invariance, both run.")
    _add(cases, baseline, "signal_end_short", f"{short_filler} {signal}",
         relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
         tier=md.TIER_SILVER, risk="low", position="end",
         sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
         notes="Short filler first, signal last (under limit); position invariance, both run.")

    # 2. Over-limit -> boundary, NOT invariance (no label to compare if V2 rejects).
    _add(cases, baseline, "signal_start_over_limit", f"{signal} {long_filler}",
         relation=md.REL_BOUNDARY, oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
         tier=md.TIER_GOLD, risk="none", position="start",
         sanitizer=md.SAN_V2_REJECTS_LENGTH, http=md.HTTP_MEASURE,
         notes=("Signal first, long filler after (over limit). V2 should reject on length; V1 "
                "feeds it to the model. If V1 predicts, compare to baseline only as diagnostic."))
    _add(cases, baseline, "signal_end_over_limit", f"{long_filler} {signal}",
         relation=md.REL_BOUNDARY, oracle=md.ORACLE_GRACEFUL_OR_TRUNCATE,
         tier=md.TIER_GOLD, risk="none", position="end",
         sanitizer=md.SAN_V2_REJECTS_LENGTH, http=md.HTTP_MEASURE,
         notes=("Long filler first, signal last (over limit); worst case for V1 attention. V2 "
                "should reject on length; V1 comparison is diagnostic only."))

    # 3. Actual truncation of the signal itself -> DIAGNOSTIC (meaning may change).
    words = signal.split()
    if len(words) >= 4:
        half = len(words) // 2
        _add(cases, baseline, "signal_head_only", " ".join(words[:half]),
             relation=md.REL_DIAGNOSTIC, oracle=md.ORACLE_DIAGNOSTIC,
             tier=md.TIER_DIAGNOSTIC, risk="high", position="start",
             sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
             notes="First half of the sentence only; truncation may change meaning -> inspect, never auto-score.")
        _add(cases, baseline, "signal_tail_only", " ".join(words[half:]),
             relation=md.REL_DIAGNOSTIC, oracle=md.ORACLE_DIAGNOSTIC,
             tier=md.TIER_DIAGNOSTIC, risk="high", position="end",
             sanitizer=md.SAN_NOT_APPLICABLE, http=md.HTTP_EXPECT_200,
             notes="Second half of the sentence only; truncation may change meaning -> inspect, never auto-score.")

    return cases
