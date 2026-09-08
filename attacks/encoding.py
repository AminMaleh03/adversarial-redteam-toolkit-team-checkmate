r"""
Category 4 - encoding attacks (the crown jewel).

Two layers, kept strictly apart:
  * transformers  -  pure ``str -> str`` (with an applied-count), no ids, no contract.
  * builders      -  wrap a baseline into AttackCase objects + register metadata.

Research basis
--------------
* Bad Characters (Boucher, Shumailov, Anderson, Papernot; IEEE S&P 2022) defines four
  families of imperceptible perturbations: invisible characters, homoglyphs, reorderings
  (bidi), and deletions. One injection degrades a vulnerable model; three can break it --
  hence we vary dose (1/3/5). We also vary *position* (leading/middle/trailing), so the
  suite is a dose x position matrix, not just increasingly corrupted prefixes.
* Unicode UTS #39 (Unicode Security Mechanisms, https://www.unicode.org/reports/tr39/) is
  the authority on visually confusable characters. We curate a small Latin->Cyrillic slice
  from it rather than expanding the whole confusables table. Pinned to the current stable
  Unicode 17.0 (2025); the curated pairs are stable across versions.

All control/invisible characters are written as explicit escapes (\u200b, \x08), never as
literal invisible bytes in the source, so the file is reviewable and cannot carry a hidden
character that a diff would miss.

The deliberate contrast this file sets up
-----------------------------------------
V2's defense #4 is NFKC normalize + strip of control/format characters.
  * Full-width Latin (compatibility chars) IS folded by NFKC   -> v2_normalizes.
  * Zero-width / bidi / deletion / null are control/format     -> v2_strips.
  * Mixed-script homoglyphs are neither, so they survive        -> v2_passes_through.
The last line is a hypothesis about the *sanitizer*, not a proven model vulnerability;
whether the classifier flips is measured by the runner.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import metadata as md

# --------------------------------------------------------------------------------------
# Curated confusable data (Unicode UTS #39, stable Unicode 17.0). One-character,
# length-preserving, visually convincing Latin -> Cyrillic substitutions.
# --------------------------------------------------------------------------------------
_UNICODE_VERSION = "Unicode 17.0 (UTS #39)"
_UTS39_URL = "https://www.unicode.org/reports/tr39/"
_TRANSFORM_VERSION = "curated-confusables-v1"

LATIN_TO_CONFUSABLE: dict[str, str] = {
    # lowercase Latin -> Cyrillic look-alikes
    "a": "а", "c": "с", "e": "е", "i": "і", "j": "ј",
    "o": "о", "p": "р", "s": "ѕ", "x": "х", "y": "у",
    # uppercase Latin -> Cyrillic look-alikes
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н",
    "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
    "X": "Х",
}

# Invisible / control-format characters (written as escapes on purpose).
_ZERO_WIDTH = ["\u200b", "\u200c", "\u200d", "\u2060"]  # ZWSP, ZWNJ, ZWJ, WORD JOINER
_RLO = "\u202e"      # RIGHT-TO-LEFT OVERRIDE
_PDF = "\u202c"      # POP DIRECTIONAL FORMATTING
_BACKSPACE = "\x08"  # deletion-family cancel char
_NULL = "\x00"

_FULLWIDTH_OFFSET = 0xFEE0  # ASCII 0x21..0x7E -> U+FF01..U+FF5E (compatibility chars)

_DOSES = (1, 3, 5)
_POSITIONS = ("leading", "middle", "trailing")


# ======================================================================================
# Position helper: pick which eligible indices to touch, deterministically.
# ======================================================================================

def _select(eligible: list[int], dose: int, position: str) -> list[int]:
    if not eligible or dose <= 0:
        return []
    dose = min(dose, len(eligible))
    if position == "leading":
        return eligible[:dose]
    if position == "trailing":
        return eligible[-dose:]
    # middle
    mid = len(eligible) // 2
    start = max(0, mid - dose // 2)
    return eligible[start:start + dose]


# ======================================================================================
# Layer 1: pure transformers. Each returns (transformed_text, chars_actually_applied).
# ======================================================================================

def apply_homoglyphs(text: str, dose: int, position: str = "leading") -> tuple[str, int]:
    """Replace ``dose`` eligible Latin letters with confusables at the given position."""
    eligible = [i for i, ch in enumerate(text) if ch in LATIN_TO_CONFUSABLE]
    chosen = set(_select(eligible, dose, position))
    out = [LATIN_TO_CONFUSABLE[ch] if i in chosen else ch for i, ch in enumerate(text)]
    return "".join(out), len(chosen)


def insert_zero_width(text: str, dose: int, position: str = "leading") -> tuple[str, int]:
    """Insert ``dose`` zero-width characters before interior positions."""
    interior = list(range(1, len(text)))
    chosen = set(_select(interior, dose, position))
    out: list[str] = []
    applied = 0
    for i, ch in enumerate(text):
        if i in chosen:
            out.append(_ZERO_WIDTH[applied % len(_ZERO_WIDTH)])
            applied += 1
        out.append(ch)
    return "".join(out), applied


def apply_deletion(text: str, dose: int, position: str = "leading") -> tuple[str, int]:
    """Insert ``dose`` junk-char + backspace pairs after interior, non-space characters."""
    interior = [i for i in range(1, len(text) - 1) if text[i] != " "]
    chosen = set(_select(interior, dose, position))
    out: list[str] = []
    applied = 0
    for i, ch in enumerate(text):
        out.append(ch)
        if i in chosen:
            out.append("z" + _BACKSPACE)
            applied += 1
    return "".join(out), applied


def apply_bidi_reorder(text: str, position: str = "middle") -> tuple[str, int]:
    """
    A genuine reordering: swap an adjacent interior pair but wrap it in RLO...PDF so it
    renders in the ORIGINAL order while the encoded byte order is swapped. This is the
    encoded-vs-rendered mismatch Bad Characters exploits, not a bare control injection.
    """
    interior = [i for i in range(1, len(text) - 2) if text[i] != " " and text[i + 1] != " "]
    chosen = _select(interior, 1, position)
    if not chosen:
        return text, 0
    i = chosen[0]
    a, b = text[i], text[i + 1]
    reordered = f"{_RLO}{b}{a}{_PDF}"  # encoded 'ba', renders as 'ab'
    return text[:i] + reordered + text[i + 2:], 1


def to_fullwidth(text: str) -> tuple[str, int]:
    """Map ASCII printables to full-width compatibility forms (NFKC folds these back)."""
    out: list[str] = []
    applied = 0
    for ch in text:
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            out.append(chr(code + _FULLWIDTH_OFFSET))
            applied += 1
        else:
            out.append(ch)
    return "".join(out), applied


# ======================================================================================
# Layer 2: builders.
# ======================================================================================

def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Per-baseline (invariance) encoding cases: a dose x position matrix for one sentence."""
    cases: list[AttackCase] = []
    text = baseline.text

    def add(subfamily: str, attacked: str, *, applied: int, position: str,
            sanitizer: str, script_change: str | None, source: str, source_version: str | None,
            source_url: str | None, tier: str, notes: str, id_suffix: str) -> None:
        if attacked == text or applied == 0:
            return  # no-op on this sentence; not an attack
        aid = f"{baseline.baseline_id}.encoding.{subfamily}.{id_suffix}"
        case = AttackCase(
            attack_id=aid,
            baseline_id=baseline.baseline_id,
            category="encoding",
            original_text=text,
            attacked_text=attacked,
        )
        meta = md.AttackMetadata(
            attack_id=aid, family="encoding", subfamily=subfamily,
            relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source=source, source_version=source_version, source_url=source_url,
            transform_version=_TRANSFORM_VERSION, validity_tier=tier, semantic_risk="low",
            requires_baseline=True, dose=applied, position=position, script_change=script_change,
            expected_sanitizer_behavior=sanitizer, expected_http_behavior=md.HTTP_EXPECT_200,
            notes=notes,
        )
        cases.append(md.register(case, meta))

    # Homoglyphs: full dose x position matrix (the star family).
    for position in _POSITIONS:
        for dose in _DOSES:
            attacked, applied = apply_homoglyphs(text, dose, position)
            add("homoglyph", attacked, applied=applied, position=position,
                sanitizer=md.SAN_V2_PASSES_THROUGH, script_change="Latin->Cyrillic",
                source="Unicode UTS #39", source_version=_UNICODE_VERSION, source_url=_UTS39_URL,
                tier=md.TIER_SILVER, id_suffix=f"{position}.d{dose}",
                notes="NFKC does not fold cross-script confusables; hypothesis is V2 leaves it intact.")

    # Zero-width: position response at a fixed dose (dose response is covered by homoglyphs).
    for position in _POSITIONS:
        attacked, applied = insert_zero_width(text, 3, position)
        add("invisible_zero_width", attacked, applied=applied, position=position,
            sanitizer=md.SAN_V2_STRIPS, script_change=None,
            source="Bad Characters (Boucher et al. 2022)", source_version=None,
            source_url="https://github.com/nickboucher/imperceptible",
            tier=md.TIER_SILVER, id_suffix=f"{position}.d3",
            notes="Zero-width chars are category Cf; V2's control-char strip should remove them.")

    # Deletion (backspace) family: position response at dose 1.
    for position in _POSITIONS:
        attacked, applied = apply_deletion(text, 1, position)
        add("deletion_backspace", attacked, applied=applied, position=position,
            sanitizer=md.SAN_V2_STRIPS, script_change=None,
            source="Bad Characters (Boucher et al. 2022)", source_version=None,
            source_url="https://github.com/nickboucher/imperceptible",
            tier=md.TIER_SILVER, id_suffix=f"{position}.d1",
            notes="Injected char + U+0008; visually cancels but changes the byte/token stream.")

    # Full-width compatibility contrast (whole sentence): NFKC folds this back.
    attacked, applied = to_fullwidth(text)
    add("compatibility_fullwidth", attacked, applied=applied, position="whole",
        sanitizer=md.SAN_V2_NORMALIZES, script_change="Latin->Fullwidth",
        source="Unicode NFKC compatibility mapping", source_version=_UNICODE_VERSION,
        source_url=_UTS39_URL, tier=md.TIER_SILVER, id_suffix="whole",
        notes="Contrast to homoglyphs: NFKC DOES fold full-width forms back to ASCII.")

    # Genuine bidi reordering (single, middle). Render-dependent -> REVIEW.
    attacked, applied = apply_bidi_reorder(text, "middle")
    add("bidi_reorder", attacked, applied=applied, position="middle",
        sanitizer=md.SAN_V2_STRIPS, script_change=None,
        source="Bad Characters (Boucher et al. 2022)", source_version=None,
        source_url="https://github.com/nickboucher/imperceptible",
        tier=md.TIER_REVIEW, id_suffix="middle",
        notes="Adjacent pair encoded swapped under RLO/PDF so it renders unchanged; render-dependent.")

    return cases


def standalone() -> list[AttackCase]:
    """Standalone encoding payloads that need no baseline (just the null byte now)."""
    null_text = f"I feel {_NULL} completely fine today"
    null_case = AttackCase(
        attack_id="encoding.null_byte",
        baseline_id=None,
        category="encoding",
        original_text=None,
        attacked_text=null_text,
    )
    md.register(
        null_case,
        md.AttackMetadata(
            attack_id="encoding.null_byte", family="encoding", subfamily="null_byte",
            relation=md.REL_AVAILABILITY, oracle=md.ORACLE_STAY_AVAILABLE,
            source="Bad Characters (Boucher et al. 2022)",
            source_url="https://github.com/nickboucher/imperceptible",
            validity_tier=md.TIER_GOLD, semantic_risk="none", requires_baseline=False,
            expected_sanitizer_behavior=md.SAN_V2_STRIPS, expected_http_behavior=md.HTTP_MEASURE,
            notes="Null (U+0000, category Cc) inside text; V2 should strip, V1 behaviour measured.",
        ),
    )
    return [null_case]
