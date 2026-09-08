"""
Category 3 - adversarial perturbations (derived).

Character-level edits a human reads the same way, applied to a content word so the meaning
is preserved (an invariance test: the label must not change). Provenance is per-transform
and honest -- not everything here is TextBugger:

  * swap / keyboard-typo / delete / word-split -> TextBugger (Li et al., NDSS 2019). Note
    TextBugger's Insert operation inserts a SPACE into a word, which is `word_split` here.
  * duplicate-a-char / repeat-char / misspell   -> natural typing noise (NL-Augmenter-inspired).
  * capitalization                              -> CheckList invariance (casing).

Deliberately excluded (subtask brief): negation changes and homoglyphs (homoglyphs live in
encoding.py). All edits are deterministic, so the suite is reproducible.

Sanitizer expectation: ``v2_passes_through``. V2's four defenses do not touch typos, so this
is exactly the family V2 is documented NOT to fix (that would require retraining the model).
We state it openly rather than pretend it is solved.
"""

from __future__ import annotations

from contract import AttackCase, BaselineCase
from attacks import metadata as md

_TEXTBUGGER = "TextBugger (Li et al., NDSS 2019)"
_NATURAL_NOISE = "Natural typing noise (NL-Augmenter-inspired)"
_CHECKLIST = "CheckList INV (Ribeiro et al., ACL 2020)"

# source -> (source_url, source_doi). Only citations verified real are included.
_SOURCE_META = {
    _TEXTBUGGER: ("https://arxiv.org/abs/1812.05271", None),
    _NATURAL_NOISE: ("https://github.com/GEM-benchmark/NL-Augmenter", None),
    _CHECKLIST: ("https://aclanthology.org/2020.acl-main.442/", "10.18653/v1/2020.acl-main.442"),
}

_STOPWORDS = frozenset({
    "i", "a", "an", "the", "am", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "it", "its", "and", "or", "but", "so", "very",
    "my", "me", "you", "he", "she", "they", "we", "this", "that", "for", "with",
    "as", "do", "did", "not", "no",  # 'not'/'no' kept out: never touch negation
})

_KEYBOARD = {
    "a": "s", "b": "v", "c": "x", "d": "f", "e": "r", "f": "g", "g": "h", "h": "j",
    "i": "o", "j": "k", "k": "l", "l": "k", "m": "n", "n": "m", "o": "p", "p": "o",
    "q": "w", "r": "t", "s": "d", "t": "y", "u": "i", "v": "b", "w": "e", "x": "c",
    "y": "u", "z": "x",
}

_VOWELS = "aeiou"


# ======================================================================================
# Target selection: choose the nth-longest content word and edit only its alphabetic core.
# ======================================================================================

def _split_affixes(token: str) -> tuple[str, str, str]:
    start = 0
    while start < len(token) and not token[start].isalpha():
        start += 1
    end = len(token)
    while end > start and not token[end - 1].isalpha():
        end -= 1
    return token[:start], token[start:end], token[end:]


def _ranked_content_indices(words: list[str]) -> list[int]:
    """Indices of alphabetic non-stopword tokens, longest core first (deterministic)."""
    scored = []
    for idx, token in enumerate(words):
        _, core, _ = _split_affixes(token)
        if core and core.lower() not in _STOPWORDS:
            scored.append((len(core), -idx, idx))  # tie-break: earlier word first
    scored.sort(reverse=True)
    ranked = [idx for _, _, idx in scored]
    if ranked:
        return ranked
    # fallback: any token with an alpha core
    return [idx for idx, tok in enumerate(words) if _split_affixes(tok)[1]]


def _edit_nth_target(text: str, editor, n: int = 0) -> str:
    """Apply ``editor`` (core -> core) to the nth-ranked content word."""
    words = text.split(" ")
    ranked = _ranked_content_indices(words)
    if len(ranked) <= n:
        return text
    idx = ranked[n]
    prefix, core, suffix = _split_affixes(words[idx])
    words[idx] = f"{prefix}{editor(core)}{suffix}"
    return " ".join(words)


# ======================================================================================
# Layer 1: pure core-editors (first/last letter preserved for char-level ops).
# ======================================================================================

def swap_adjacent(core: str) -> str:
    if len(core) < 4:
        return core
    i = len(core) // 2 - 1
    chars = list(core)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def keyboard_typo(core: str) -> str:
    if len(core) < 3:
        return core
    i = len(core) // 2
    lower = core[i].lower()
    if lower not in _KEYBOARD:
        return core
    repl = _KEYBOARD[lower]
    return core[:i] + (repl.upper() if core[i].isupper() else repl) + core[i + 1:]


def delete_char(core: str) -> str:
    if len(core) < 4:
        return core
    i = len(core) // 2
    return core[:i] + core[i + 1:]


def word_split(core: str) -> str:
    """TextBugger Insert: put a space inside the word ('happy' -> 'hap py')."""
    if len(core) < 4:
        return core
    i = len(core) // 2
    return core[:i] + " " + core[i:]


def insert_char(core: str) -> str:
    """Duplicate one interior letter (natural typing noise, not TextBugger)."""
    if len(core) < 3:
        return core
    i = len(core) // 2
    return core[:i] + core[i] + core[i:]


def repeat_char(core: str) -> str:
    if len(core) < 2:
        return core
    return core + core[-1] * 2


def misspell(core: str) -> str:
    if len(core) < 4:
        return core
    for i in range(1, len(core) - 1):
        if core[i] == core[i + 1]:
            return core[:i] + core[i + 1:]
    ie = core.find("ie")
    if ie != -1:
        return core[:ie] + "ei" + core[ie + 2:]
    for i in range(1, len(core) - 1):
        if core[i].isalpha() and core[i].lower() not in _VOWELS:
            return core[:i] + core[i] + core[i:]
    i = len(core) // 2
    return core[:i] + core[i] + core[i:]


def to_upper(core: str) -> str:
    up = core.upper()
    return up if up != core else core.lower()


# ======================================================================================
# Layer 2: builder.
# ======================================================================================

# (subfamily, editor, target_n, dose, source, tier, semantic_risk, notes)
_PERTURBATIONS = [
    ("swap_adjacent", swap_adjacent, 0, 1, _TEXTBUGGER, md.TIER_SILVER, "low",
     "Two interior letters transposed (TextBugger swap)."),
    ("keyboard_typo", keyboard_typo, 0, 1, _TEXTBUGGER, md.TIER_SILVER, "low",
     "One interior letter replaced by a QWERTY neighbour (TextBugger substitute)."),
    ("keyboard_typo_second_word", keyboard_typo, 1, 1, _TEXTBUGGER, md.TIER_SILVER, "low",
     "Same typo applied to the SECOND content word, to cover multi-word edits."),
    ("delete_char", delete_char, 0, 1, _TEXTBUGGER, md.TIER_SILVER, "low",
     "One interior letter deleted (TextBugger delete)."),
    ("word_split", word_split, 0, 1, _TEXTBUGGER, md.TIER_SILVER, "low",
     "A space inserted inside the word (TextBugger Insert)."),
    ("insert_char", insert_char, 0, 1, _NATURAL_NOISE, md.TIER_SILVER, "low",
     "One interior letter duplicated (natural typing noise)."),
    ("repeat_char", repeat_char, 0, 2, _NATURAL_NOISE, md.TIER_SILVER, "low",
     "Final letter elongated (natural typing noise)."),
    ("misspell", misspell, 0, 1, _NATURAL_NOISE, md.TIER_SILVER, "low",
     "A common natural misspelling."),
    ("capitalization", to_upper, 0, 0, _CHECKLIST, md.TIER_SILVER, "low",
     "Content word uppercased; casing only, meaning intact."),
]


def build_derived(baseline: BaselineCase) -> list[AttackCase]:
    """Build the per-baseline perturbation cases for one clean sentence."""
    cases: list[AttackCase] = []
    text = baseline.text

    for subfamily, editor, target_n, dose, source, tier, risk, notes in _PERTURBATIONS:
        attacked = _edit_nth_target(text, editor, target_n)
        if attacked == text:
            continue  # no-op on this sentence (e.g. no second content word); skip
        aid = f"{baseline.baseline_id}.perturbation.{subfamily}"
        case = AttackCase(
            attack_id=aid, baseline_id=baseline.baseline_id, category="perturbation",
            original_text=text, attacked_text=attacked,
        )
        source_url, source_doi = _SOURCE_META.get(source, (None, None))
        meta = md.AttackMetadata(
            attack_id=aid, family="perturbation", subfamily=subfamily,
            relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source=source, source_url=source_url, source_doi=source_doi,
            validity_tier=tier, semantic_risk=risk, requires_baseline=True,
            dose=dose, position="content_word",
            expected_sanitizer_behavior=md.SAN_V2_PASSES_THROUGH,
            expected_http_behavior=md.HTTP_EXPECT_200,
            notes=notes + " V2 does not fix perturbations (model-level weakness).",
        )
        cases.append(md.register(case, meta))

    return cases
