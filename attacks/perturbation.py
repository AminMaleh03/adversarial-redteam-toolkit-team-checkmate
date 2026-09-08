"""
Category 3 - adversarial perturbations (derived).

Character-level edits that a human reads the same way, applied to a content word so the
meaning is preserved (this is an invariance test: the label must not change). Grounded in
TextBugger (Li et al., NDSS 2019); the stopword-skipping and first/last-letter-preserving
choices mirror the constraints that serious recipes (TextFooler, PWWS, TextBugger) use to
keep edits human-plausible.

Deliberately excluded (per the subtask brief):
  * negation changes -- they change meaning for a human too, so a flip proves nothing;
  * homoglyphs -- those live in encoding.py.

All edits are deterministic (no randomness), so the suite is reproducible run to run.

Sanitizer expectation: ``v2_passes_through``. V2's four defenses do not touch typos, so
this is exactly the family V2 is documented NOT to fix -- fixing it would mean retraining
the model, which is out of scope. We state that openly rather than pretend it is solved.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import metadata as md

# Small, common English stopword set. We avoid editing these so the edited token still
# carries the sentence's emotional content.
_STOPWORDS = frozenset({
    "i", "a", "an", "the", "am", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "it", "its", "and", "or", "but", "so", "very",
    "my", "me", "you", "he", "she", "they", "we", "this", "that", "for", "with",
    "as", "do", "did", "not", "no",  # 'not'/'no' kept out of edits: never touch negation
})

# QWERTY horizontal neighbours for keyboard-typo substitution.
_KEYBOARD = {
    "a": "s", "b": "v", "c": "x", "d": "f", "e": "r", "f": "g", "g": "h", "h": "j",
    "i": "o", "j": "k", "k": "l", "l": "k", "m": "n", "n": "m", "o": "p", "p": "o",
    "q": "w", "r": "t", "s": "d", "t": "y", "u": "i", "v": "b", "w": "e", "x": "c",
    "y": "u", "z": "x",
}

_VOWELS = "aeiou"


# ======================================================================================
# Target selection: pick one content word to edit, and edit only its alphabetic core.
# ======================================================================================

def _split_affixes(token: str) -> tuple[str, str, str]:
    """Split a token into (leading non-alpha, alpha core, trailing non-alpha)."""
    start = 0
    while start < len(token) and not token[start].isalpha():
        start += 1
    end = len(token)
    while end > start and not token[end - 1].isalpha():
        end -= 1
    return token[:start], token[start:end], token[end:]


def _target_index(words: list[str]) -> int:
    """Index of the longest non-stopword alphabetic token (falls back to the longest)."""
    best_idx, best_len = -1, -1
    for idx, token in enumerate(words):
        _, core, _ = _split_affixes(token)
        if not core or core.lower() in _STOPWORDS:
            continue
        if len(core) > best_len:
            best_idx, best_len = idx, len(core)
    if best_idx != -1:
        return best_idx
    # fallback: longest token with any alpha core
    for idx, token in enumerate(words):
        _, core, _ = _split_affixes(token)
        if core and len(core) > best_len:
            best_idx, best_len = idx, len(core)
    return best_idx


def _edit_target(text: str, editor) -> str:
    """Apply ``editor`` (core -> core) to the alpha core of the chosen content word."""
    words = text.split(" ")
    idx = _target_index(words)
    if idx == -1:
        return text
    prefix, core, suffix = _split_affixes(words[idx])
    new_core = editor(core)
    words[idx] = f"{prefix}{new_core}{suffix}"
    return " ".join(words)


# ======================================================================================
# Layer 1: pure core-editors (operate on a single word's alphabetic core).
# Each keeps the first and last letter fixed where it can, per TextBugger.
# ======================================================================================

def swap_adjacent(core: str) -> str:
    """Transpose two interior letters near the middle."""
    if len(core) < 4:
        return core
    i = len(core) // 2 - 1
    chars = list(core)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def keyboard_typo(core: str) -> str:
    """Replace one interior letter with a QWERTY neighbour."""
    if len(core) < 3:
        return core
    i = len(core) // 2
    lower = core[i].lower()
    if lower not in _KEYBOARD:
        return core
    repl = _KEYBOARD[lower]
    return core[:i] + (repl.upper() if core[i].isupper() else repl) + core[i + 1:]


def delete_char(core: str) -> str:
    """Delete one interior letter."""
    if len(core) < 4:
        return core
    i = len(core) // 2
    return core[:i] + core[i + 1:]


def insert_char(core: str) -> str:
    """Duplicate one interior letter (a character insertion)."""
    if len(core) < 3:
        return core
    i = len(core) // 2
    return core[:i] + core[i] + core[i:]


def repeat_char(core: str) -> str:
    """Elongate the last letter (e.g. 'happy' -> 'happyyy')."""
    if len(core) < 2:
        return core
    return core + core[-1] * 2


def misspell(core: str) -> str:
    """A common misspelling: single a doubled letter, swap 'ie'->'ei', or double a consonant."""
    if len(core) < 4:
        return core
    for i in range(1, len(core) - 1):
        if core[i] == core[i + 1]:  # doubled letter -> single it ("happpy" is not our aim)
            return core[:i] + core[i + 1:]
    ie = core.find("ie")
    if ie != -1:
        return core[:ie] + "ei" + core[ie + 2:]
    # fallback: double an interior consonant (a very common real-world misspelling)
    for i in range(1, len(core) - 1):
        if core[i].isalpha() and core[i].lower() not in _VOWELS:
            return core[:i] + core[i] + core[i:]
    # last resort: double the middle character
    i = len(core) // 2
    return core[:i] + core[i] + core[i:]


def to_upper(core: str) -> str:
    """Capitalization change: uppercase the whole word."""
    up = core.upper()
    return up if up != core else core.lower()


# ======================================================================================
# Layer 2: builder.
# ======================================================================================

# (subfamily, editor, dose, notes)
_PERTURBATIONS = [
    ("swap_adjacent", swap_adjacent, 1, "Two interior letters transposed (TextBugger swap)."),
    ("keyboard_typo", keyboard_typo, 1, "One interior letter replaced by a QWERTY neighbour."),
    ("delete_char", delete_char, 1, "One interior letter deleted."),
    ("insert_char", insert_char, 1, "One interior letter duplicated (insertion)."),
    ("repeat_char", repeat_char, 2, "Final letter elongated (character repetition)."),
    ("misspell", misspell, 1, "A common natural misspelling."),
    ("capitalization", to_upper, 0, "Content word uppercased; casing only, meaning intact."),
]


def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Build the per-baseline perturbation cases for one clean sentence."""
    cases: list[AttackCase] = []
    text = baseline.text

    for subfamily, editor, dose, notes in _PERTURBATIONS:
        attacked = _edit_target(text, editor)
        if attacked == text:
            # No-op on this sentence (e.g. target word too short); skip it.
            continue
        aid = f"{baseline.baseline_id}.perturbation.{subfamily}"
        case = AttackCase(
            attack_id=aid,
            baseline_id=baseline.baseline_id,
            category="perturbation",
            original_text=text,
            attacked_text=attacked,
        )
        meta = md.AttackMetadata(
            attack_id=aid,
            family="perturbation",
            subfamily=subfamily,
            relation=md.REL_INVARIANT,
            oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source="TextBugger (Li et al., NDSS 2019)",
            validity_tier=md.TIER_SILVER,
            semantic_risk="low",
            requires_baseline=True,
            dose=dose,
            position="content_word",
            expected_sanitizer_behavior=md.SAN_V2_PASSES_THROUGH,
            expected_http_behavior=md.HTTP_EXPECT_200,
            notes=notes + " V2 does not fix perturbations (model-level weakness).",
        )
        cases.append(md.register(case, meta))

    return cases
