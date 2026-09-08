"""
Category 6 - truncation and long-semantic input (derived).

Bury a real, labelled sentence at the start or the end of a block of neutral filler and
see whether the model still picks up its emotion (a CheckList-style robustness-to-
irrelevant-additions / invariance test). Two length regimes:

  * short filler stays under the assumed limit  -> both V1 and V2 process it, so this is a
    clean test of positional sensitivity alone.
  * long filler goes over the assumed limit     -> V2 should reject on length before
    inference, while V1 (which never truncates) feeds the whole thing to the model. That
    difference is part of the before/after story; the length threshold itself is measured
    by the runner, so these are hypotheses, not assertions.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import metadata as md

# Neutral filler unit (~9 words). Deliberately emotion-free so any predicted emotion must
# come from the buried signal, not the filler.
_FILLER_UNIT = "the document also records routine administrative details for later reference"

_SHORT_FILLER_WORDS = 40      # comfortably under a ~512-token limit
_LONG_FILLER_WORDS = 600      # comfortably over it


def _filler(word_count: int) -> str:
    unit_words = _FILLER_UNIT.split()
    repeats = (word_count // len(unit_words)) + 1
    words = (unit_words * repeats)[:word_count]
    return " ".join(words)


def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Build the per-baseline truncation cases for one clean sentence."""
    cases: list[AttackCase] = []
    signal = baseline.text
    short_filler = _filler(_SHORT_FILLER_WORDS)
    long_filler = _filler(_LONG_FILLER_WORDS)

    # (subfamily, attacked_text, position, sanitizer, http, notes)
    variants = [
        ("signal_start_short", f"{signal} {short_filler}", "start",
         md.SAN_NOT_APPLICABLE, md.HTTP_EXPECT_200,
         "Signal first, short filler after (under limit); pure position test, both versions run."),
        ("signal_end_short", f"{short_filler} {signal}", "end",
         md.SAN_NOT_APPLICABLE, md.HTTP_EXPECT_200,
         "Short filler first, signal last (under limit); pure position test, both versions run."),
        ("signal_start_long", f"{signal} {long_filler}", "start",
         md.SAN_V2_REJECTS_LENGTH, md.HTTP_MEASURE,
         "Signal first, long filler after (over limit); V1 processes it all, V2 rejects on length."),
        ("signal_end_long", f"{long_filler} {signal}", "end",
         md.SAN_V2_REJECTS_LENGTH, md.HTTP_MEASURE,
         "Long filler first, signal last (over limit); worst case for V1 attention, V2 rejects."),
    ]

    for subfamily, attacked, position, sanitizer, http, notes in variants:
        aid = f"{baseline.baseline_id}.truncation.{subfamily}"
        case = AttackCase(
            attack_id=aid,
            baseline_id=baseline.baseline_id,
            category="truncation",
            original_text=signal,
            attacked_text=attacked,
        )
        meta = md.AttackMetadata(
            attack_id=aid,
            family="truncation",
            subfamily=subfamily,
            relation=md.REL_INVARIANT,
            oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source="CheckList (robustness to irrelevant additions)",
            validity_tier=md.TIER_SILVER,
            semantic_risk="low",
            requires_baseline=True,
            position=position,
            boundary_source="approximate_word_estimate",
            expected_sanitizer_behavior=sanitizer,
            expected_http_behavior=http,
            notes=notes,
        )
        cases.append(md.register(case, meta))

    return cases
