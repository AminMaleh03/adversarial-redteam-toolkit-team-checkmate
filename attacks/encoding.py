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
  hence dose (1/3/5). We also vary position (leading/middle/trailing): a dose x position
  matrix, not just corrupted prefixes.
* Unicode UTS #39 (Security Mechanisms) is the authority on visually confusable characters.
  We curate small Latin->Cyrillic and Latin->Greek slices from it (verified against a
  vendored excerpt of confusables.txt), not the whole table. Pinned to UTS #39 v17.0.0
  rev 32 (2025-09-04) -- the current stable, normatively-citeable revision. (Note: the
  Unicode Standard 18.0 CORE is not released yet as of Sep 2026, so we do not cite it.)
* Unicode UAX #15 (Normalization Forms) is the authority for NFKC. The full-width and
  ligature families are compatibility-equivalent under NFKC and are cited to UAX #15, not
  UTS #39.

All control/invisible characters are constructed with ``chr(...)`` from their code points,
never pasted as literal invisible bytes, so the source is reviewable and a diff cannot hide
a character. A test asserts the exact code points.

The deliberate contrast this file sets up
-----------------------------------------
V2's defense #4 is NFKC normalize + strip of control/format characters.
  * Full-width Latin and ligatures ARE folded by NFKC          -> v2_normalizes.
  * Zero-width / bidi / deletion / null are control/format     -> v2_strips.
  * Mixed-script homoglyphs are neither, so they survive        -> v2_passes_through.
The last line is a hypothesis about the sanitizer, measured by the runner.
"""

from __future__ import annotations

import os

from contract import AttackCase, BaselineCase
from attacks import metadata as md

# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------
_UTS39_VERSION = "UTS #39 v17.0.0 rev 32 (2025-09-04)"
_UTS39_URL = "https://www.unicode.org/reports/tr39/"
_UAX15_VERSION = "UAX #15 (Unicode Normalization Forms)"
_UAX15_URL = "https://www.unicode.org/reports/tr15/"
_BADCHARS = "Bad Characters (Boucher et al., IEEE S&P 2022)"
_BADCHARS_URL = "https://arxiv.org/abs/2106.09898"
_TRANSFORM_VERSION = "curated-confusables-v2"

# --------------------------------------------------------------------------------------
# Curated confusable data (verified against attacks/data/uts39_confusables_curated.txt).
# Latin prototype -> visually-confusable single character, length-preserving.
# --------------------------------------------------------------------------------------
LATIN_TO_CONFUSABLE: dict[str, str] = {  # Latin -> Cyrillic
    "a": "а", "c": "с", "e": "е", "i": "і", "j": "ј",
    "o": "о", "p": "р", "s": "ѕ", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н",
    "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х",
}
LATIN_TO_GREEK: dict[str, str] = {  # Latin -> Greek
    "a": "α", "o": "ο", "p": "ρ", "v": "ν",
    "A": "Α", "B": "Β", "E": "Ε", "H": "Η", "I": "Ι", "K": "Κ",
    "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ", "Z": "Ζ",
}

# Ligatures folded by NFKC (compatibility decomposition). Longest first.
_LIGATURES = [("ffi", chr(0xFB03)), ("ffl", chr(0xFB04)),
              ("fi", chr(0xFB01)), ("fl", chr(0xFB02)), ("ff", chr(0xFB00))]

# Invisible / control-format characters, built from code points (never literal bytes).
_ZERO_WIDTH = [chr(0x200B), chr(0x200C), chr(0x200D), chr(0x2060)]  # ZWSP ZWNJ ZWJ WORDJOINER
_RLO = chr(0x202E)      # RIGHT-TO-LEFT OVERRIDE
_PDF = chr(0x202C)      # POP DIRECTIONAL FORMATTING
_BACKSPACE = chr(0x08)  # deletion-family cancel char
_NULL = chr(0x00)

_FULLWIDTH_OFFSET = 0xFEE0  # ASCII 0x21..0x7E -> U+FF01..U+FF5E (compatibility chars)

_DOSES = (1, 3, 5)
_POSITIONS = ("leading", "middle", "trailing")

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "uts39_confusables_curated.txt")


def load_confusable_fixture() -> dict[str, str]:
    """Parse the vendored UTS #39 excerpt into {confusable_char: latin_char}."""
    mapping: dict[str, str] = {}
    with open(_DATA_PATH, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split(";")
            mapping[chr(int(fields[0].strip(), 16))] = chr(int(fields[1].strip(), 16))
    return mapping


# ======================================================================================
# Layer 1: pure transformers. Each returns (transformed_text, chars_actually_applied).
# ======================================================================================

def _select(eligible: list[int], dose: int, position: str) -> list[int]:
    if not eligible or dose <= 0:
        return []
    dose = min(dose, len(eligible))
    if position == "leading":
        return eligible[:dose]
    if position == "trailing":
        return eligible[-dose:]
    mid = len(eligible) // 2
    start = max(0, mid - dose // 2)
    return eligible[start:start + dose]


def apply_homoglyphs(text: str, dose: int, position: str = "leading",
                     mapping: dict[str, str] | None = None) -> tuple[str, int]:
    """Replace ``dose`` eligible Latin letters with confusables at the given position."""
    mapping = mapping or LATIN_TO_CONFUSABLE
    eligible = [i for i, ch in enumerate(text) if ch in mapping]
    chosen = set(_select(eligible, dose, position))
    out = [mapping[ch] if i in chosen else ch for i, ch in enumerate(text)]
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
    Genuine reordering: swap an adjacent interior pair but wrap it in RLO...PDF so it renders
    in the ORIGINAL order while the encoded byte order is swapped (the encoded-vs-rendered
    mismatch Bad Characters exploits), not a bare control injection.
    """
    interior = [i for i in range(1, len(text) - 2) if text[i] != " " and text[i + 1] != " "]
    chosen = _select(interior, 1, position)
    if not chosen:
        return text, 0
    i = chosen[0]
    a, b = text[i], text[i + 1]
    return text[:i] + f"{_RLO}{b}{a}{_PDF}" + text[i + 2:], 1


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


def to_ligatures(text: str) -> tuple[str, int]:
    """Replace f-ligature sequences (fi/fl/ff/ffi/ffl) with the single ligature char (NFKC-folded)."""
    out = text
    applied = 0
    for seq, lig in _LIGATURES:
        count = out.count(seq)
        if count:
            out = out.replace(seq, lig)
            applied += count
    return out, applied


# ======================================================================================
# Layer 2: builders.
# ======================================================================================

def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Per-baseline (invariance) encoding cases: a dose x position matrix for one sentence."""
    cases: list[AttackCase] = []
    text = baseline.text

    def add(subfamily, attacked, *, applied, position, sanitizer, script_change, source,
            source_version, source_url, tier, notes, id_suffix, source_doi=None):
        if attacked == text or applied == 0:
            return
        aid = f"{baseline.baseline_id}.encoding.{subfamily}.{id_suffix}"
        case = AttackCase(attack_id=aid, baseline_id=baseline.baseline_id, category="encoding",
                          original_text=text, attacked_text=attacked)
        meta = md.AttackMetadata(
            attack_id=aid, family="encoding", subfamily=subfamily,
            relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source=source, source_version=source_version, source_url=source_url,
            source_doi=source_doi, transform_version=_TRANSFORM_VERSION, validity_tier=tier,
            semantic_risk="low", requires_baseline=True, dose=applied, position=position,
            script_change=script_change, expected_sanitizer_behavior=sanitizer,
            expected_http_behavior=md.HTTP_EXPECT_200, notes=notes)
        cases.append(md.register(case, meta))

    # Cyrillic homoglyphs: full dose x position matrix (the star family).
    for position in _POSITIONS:
        for dose in _DOSES:
            attacked, applied = apply_homoglyphs(text, dose, position, LATIN_TO_CONFUSABLE)
            add("homoglyph", attacked, applied=applied, position=position,
                sanitizer=md.SAN_V2_PASSES_THROUGH, script_change="Latin->Cyrillic",
                source="Unicode UTS #39", source_version=_UTS39_VERSION, source_url=_UTS39_URL,
                tier=md.TIER_SILVER, id_suffix=f"{position}.d{dose}",
                notes="NFKC does not fold cross-script confusables; hypothesis is V2 leaves it intact.")

    # Greek homoglyphs: leaner matrix, so the report can compare script families.
    for position in _POSITIONS:
        for dose in (1, 3):
            attacked, applied = apply_homoglyphs(text, dose, position, LATIN_TO_GREEK)
            add("homoglyph_greek", attacked, applied=applied, position=position,
                sanitizer=md.SAN_V2_PASSES_THROUGH, script_change="Latin->Greek",
                source="Unicode UTS #39", source_version=_UTS39_VERSION, source_url=_UTS39_URL,
                tier=md.TIER_SILVER, id_suffix=f"{position}.d{dose}",
                notes="Latin->Greek confusables; same NFKC gap as Cyrillic, different script family.")

    # Zero-width: position response at a fixed dose.
    for position in _POSITIONS:
        attacked, applied = insert_zero_width(text, 3, position)
        add("invisible_zero_width", attacked, applied=applied, position=position,
            sanitizer=md.SAN_V2_STRIPS, script_change=None, source=_BADCHARS,
            source_version=None, source_url=_BADCHARS_URL, tier=md.TIER_SILVER,
            id_suffix=f"{position}.d3",
            notes="Zero-width chars are category Cf; V2's control-char strip should remove them.")

    # Deletion (backspace): position response at dose 1.
    for position in _POSITIONS:
        attacked, applied = apply_deletion(text, 1, position)
        add("deletion_backspace", attacked, applied=applied, position=position,
            sanitizer=md.SAN_V2_STRIPS, script_change=None, source=_BADCHARS,
            source_version=None, source_url=_BADCHARS_URL, tier=md.TIER_SILVER,
            id_suffix=f"{position}.d1",
            notes="Injected char + U+0008; visually cancels but changes the byte/token stream.")

    # Full-width compatibility contrast (NFKC folds it back) -- cited to UAX #15.
    attacked, applied = to_fullwidth(text)
    add("compatibility_fullwidth", attacked, applied=applied, position="whole",
        sanitizer=md.SAN_V2_NORMALIZES, script_change="Latin->Fullwidth",
        source="Unicode UAX #15 (compatibility mapping)", source_version=_UAX15_VERSION,
        source_url=_UAX15_URL, tier=md.TIER_SILVER, id_suffix="whole",
        notes="Positive control for V2's NFKC: full-width forms fold back to ASCII.")

    # Ligature compatibility contrast (fires only when fi/fl/ff present) -- UAX #15.
    attacked, applied = to_ligatures(text)
    add("compatibility_ligature", attacked, applied=applied, position="whole",
        sanitizer=md.SAN_V2_NORMALIZES, script_change="Latin->Ligature",
        source="Unicode UAX #15 (compatibility mapping)", source_version=_UAX15_VERSION,
        source_url=_UAX15_URL, tier=md.TIER_SILVER, id_suffix="whole",
        notes="Positive control for V2's NFKC: f-ligatures fold back to ASCII when present.")

    # Genuine bidi reordering (single, middle). Render-dependent -> REVIEW.
    attacked, applied = apply_bidi_reorder(text, "middle")
    add("bidi_reorder", attacked, applied=applied, position="middle",
        sanitizer=md.SAN_V2_STRIPS, script_change=None, source=_BADCHARS,
        source_version=None, source_url=_BADCHARS_URL, tier=md.TIER_REVIEW, id_suffix="middle",
        notes="Adjacent pair encoded swapped under RLO/PDF so it renders unchanged; render-dependent.")

    return cases


def standalone() -> list[AttackCase]:
    """Standalone encoding payloads that need no baseline (just the null byte)."""
    null_text = f"I feel {_NULL} completely fine today"
    null_case = AttackCase(attack_id="encoding.null_byte", baseline_id=None, category="encoding",
                           original_text=None, attacked_text=null_text)
    md.register(null_case, md.AttackMetadata(
        attack_id="encoding.null_byte", family="encoding", subfamily="null_byte",
        relation=md.REL_AVAILABILITY, oracle=md.ORACLE_STAY_AVAILABLE, source=_BADCHARS,
        source_url=_BADCHARS_URL, validity_tier=md.TIER_GOLD, semantic_risk="none",
        requires_baseline=False, expected_sanitizer_behavior=md.SAN_V2_STRIPS,
        expected_http_behavior=md.HTTP_MEASURE,
        notes="Null (U+0000, category Cc) inside text; V2 should strip, V1 behaviour measured."))
    return [null_case]
