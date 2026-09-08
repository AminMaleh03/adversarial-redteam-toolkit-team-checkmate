"""
Category 5 - whitespace and formatting manipulation (derived).

Surface layout should not change a text classifier's semantic prediction, so these are
invariance tests. Most are expected to be neutralized by V2's whitespace collapse, which
makes them a clean before/after story; repeated punctuation is the exception (V2 does not
touch it), so it is tagged v2_passes_through. Framed against NL-Augmenter's treatment of
natural formatting noise rather than as arbitrary corruption.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import metadata as md

_NBSP = "\u00a0"    # no-break space (NFKC folds this to a normal space)
_EM_SPACE = "\u2003"  # em space


# ======================================================================================
# Layer 1: pure transformers.
# ======================================================================================

def interior_runs(text: str) -> str:
    """Turn each single space into a run of five spaces."""
    return text.replace(" ", "     ")


def tabs(text: str) -> str:
    """Replace spaces with tab characters."""
    return text.replace(" ", "\t")


def newlines(text: str) -> str:
    """Replace spaces with newlines."""
    return text.replace(" ", "\n")


def leading_trailing(text: str) -> str:
    """Pad the text with leading and trailing whitespace."""
    return "   " + text + "   "


def repeated_punctuation(text: str) -> str:
    """Append repeated punctuation (not whitespace; V2 leaves this intact)."""
    return text + "!!!???..."


def unicode_spaces(text: str) -> str:
    """Replace normal spaces with Unicode space look-alikes (NBSP / em space)."""
    out = []
    for i, ch in enumerate(text):
        out.append(_NBSP if ch == " " and i % 2 == 0 else (_EM_SPACE if ch == " " else ch))
    return "".join(out)


# ======================================================================================
# Layer 2: builder.
# ======================================================================================

# (subfamily, transformer, sanitizer, tier, risk, relation, oracle, notes)
_INV, _DIAG = md.REL_INVARIANT, md.REL_DIAGNOSTIC
_O_MATCH, _O_DIAG = md.ORACLE_LABEL_MATCH_BASELINE, md.ORACLE_DIAGNOSTIC
_WHITESPACE = [
    ("interior_runs", interior_runs, md.SAN_V2_COLLAPSES_WS, md.TIER_SILVER, "low", _INV, _O_MATCH,
     "Multiple spaces between words; V2 collapses to single spaces."),
    ("tabs", tabs, md.SAN_V2_COLLAPSES_WS, md.TIER_SILVER, "low", _INV, _O_MATCH,
     "Spaces replaced by tabs; V2 collapses whitespace runs."),
    ("newlines", newlines, md.SAN_V2_COLLAPSES_WS, md.TIER_SILVER, "low", _INV, _O_MATCH,
     "Spaces replaced by newlines; V2 collapses whitespace runs."),
    ("leading_trailing", leading_trailing, md.SAN_V2_COLLAPSES_WS, md.TIER_SILVER, "low", _INV, _O_MATCH,
     "Leading/trailing padding; V2 strips it."),
    # Repeated punctuation is NOT whitespace and can nudge intensity/sentiment, so there is
    # no guaranteed invariance relation -> diagnostic, REVIEW, medium risk, never auto-scored.
    ("repeated_punctuation", repeated_punctuation, md.SAN_V2_PASSES_THROUGH, md.TIER_REVIEW, "medium",
     _DIAG, _O_DIAG,
     "Repeated punctuation; not whitespace, may shift intensity -> diagnostic, V2 leaves it intact."),
    ("unicode_spaces", unicode_spaces, md.SAN_V2_COLLAPSES_WS, md.TIER_SILVER, "low", _INV, _O_MATCH,
     "NBSP/em-space instead of normal spaces; NFKC folds them, then whitespace collapse."),
]


def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Build the per-baseline whitespace cases for one clean sentence."""
    cases: list[AttackCase] = []
    text = baseline.text

    for subfamily, transformer, sanitizer, tier, risk, relation, oracle, notes in _WHITESPACE:
        attacked = transformer(text)
        if attacked == text:
            continue
        aid = f"{baseline.baseline_id}.whitespace.{subfamily}"
        case = AttackCase(
            attack_id=aid,
            baseline_id=baseline.baseline_id,
            category="whitespace",
            original_text=text,
            attacked_text=attacked,
        )
        meta = md.AttackMetadata(
            attack_id=aid,
            family="whitespace",
            subfamily=subfamily,
            relation=relation,
            oracle=oracle,
            source="NL-Augmenter (formatting noise), CheckList INV",
            source_url="https://github.com/GEM-benchmark/NL-Augmenter",
            validity_tier=tier,
            semantic_risk=risk,
            requires_baseline=True,
            position="whole",
            expected_sanitizer_behavior=sanitizer,
            expected_http_behavior=md.HTTP_EXPECT_200,
            notes=notes,
        )
        cases.append(md.register(case, meta))

    return cases
