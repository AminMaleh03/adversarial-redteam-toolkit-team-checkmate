"""
Tests for the attack library (owner: Lamei).

Covers everything the subtask requires:
  * every payload matches the AttackCase shape,
  * derived payloads carry a baseline_id, standalone ones leave it None,
  * the raw flag is correct,
  * every perturbation function actually changes the text,
  * oversized payloads are the size they claim,
  * no two payloads share an attack id,
plus the metadata-layer invariants (relation/oracle vocabulary, requires_baseline
agreement) and the two Unicode facts the report's headline claim rests on.

NOTE on the raw flag: the subtask wording says raw is set on "broken JSON and wrong
content type ... and nowhere else". In practice, any body that cannot be produced by
serialising {"text": "<string>"} must also be raw -- type confusion ({"text": 123}),
missing/renamed/extra fields, and deeply nested JSON. So the enforced invariant here is
"raw iff the body is not a plain string payload", and we still assert explicitly that
broken JSON and wrong content type are raw. This refinement is flagged for Ahsan.
"""

import unicodedata
from dataclasses import fields

import pytest

from contract import AttackCase, BaselineCase
from attacks import library
from attacks import encoding, perturbation
from attacks import metadata as md


BASELINES = [
    BaselineCase("b001", "I am extremely happy today", "joy", "handwritten"),
    BaselineCase("b002", "The service was disgusting and awful", "disgust", "handwritten"),
    BaselineCase("b003", "Everything feels calm and ordinary right now", "neutral", "handwritten"),
]


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts from an empty manifest so registry state can't leak between tests."""
    md.reset()
    yield
    md.reset()


def _full_suite():
    return library.build_suite(BASELINES)


# ---------------------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------------------

def test_every_payload_is_an_attackcase():
    for case in _full_suite():
        assert isinstance(case, AttackCase)
        assert isinstance(case.attack_id, str) and case.attack_id
        assert isinstance(case.category, str) and case.category
        assert isinstance(case.is_raw, bool)


def test_field_names_match_contract():
    # Guard against drift if the frozen contract ever changes underneath us.
    names = {f.name for f in fields(AttackCase)}
    assert {"attack_id", "baseline_id", "category", "original_text",
            "attacked_text", "is_raw", "raw_body", "raw_headers"} <= names


# ---------------------------------------------------------------------------------------
# Derived vs standalone
# ---------------------------------------------------------------------------------------

def test_derived_carry_baseline_id():
    for baseline in BASELINES:
        for case in library.build_derived(baseline):
            assert case.baseline_id == baseline.baseline_id


def test_standalone_have_no_baseline_id():
    for case in library.standalone_cases():
        assert case.baseline_id is None


# ---------------------------------------------------------------------------------------
# Raw flag
# ---------------------------------------------------------------------------------------

def test_raw_cases_are_well_formed():
    for case in library.standalone_cases():
        if case.is_raw:
            assert case.raw_body is not None
            assert isinstance(case.raw_headers, dict) and case.raw_headers
            assert case.attacked_text is None
        else:
            # A non-raw case is a plain string payload the runner can serialise.
            assert isinstance(case.attacked_text, str)
            assert case.raw_body is None


def test_broken_json_and_wrong_content_type_are_raw():
    by_id = {c.attack_id: c for c in library.standalone_cases()}
    assert by_id["malformed.broken_json"].is_raw is True
    assert by_id["malformed.wrong_content_type"].is_raw is True
    # wrong content type carries a non-JSON content type header
    assert by_id["malformed.wrong_content_type"].raw_headers["Content-Type"] == "text/plain"


def test_no_derived_case_is_raw():
    for baseline in BASELINES:
        for case in library.build_derived(baseline):
            assert case.is_raw is False


# ---------------------------------------------------------------------------------------
# Perturbations actually change the text
# ---------------------------------------------------------------------------------------

def test_every_perturbation_editor_changes_text():
    word = "extremely"
    for _subfamily, editor, _dose, _notes in perturbation._PERTURBATIONS:
        assert editor(word) != word, f"{editor.__name__} did not change {word!r}"


def test_perturbations_preserve_first_and_last_letter_for_char_ops():
    # TextBugger keeps first/last letters; check the char-level ops (not casing).
    word = "extremely"
    for name in ("swap_adjacent", "keyboard_typo", "delete_char", "insert_char"):
        editor = getattr(perturbation, name)
        out = editor(word)
        assert out[0] == word[0] and out[-1] == word[-1]


# ---------------------------------------------------------------------------------------
# Oversized payloads are the size they claim
# ---------------------------------------------------------------------------------------

def test_oversized_payloads_are_exact_size():
    expected = {
        "malformed.oversized_100kb": 100 * 1024,
        "malformed.oversized_1mb": 1024 * 1024,
        "malformed.oversized_10mb": 10 * 1024 * 1024,
    }
    by_id = {c.attack_id: c for c in library.standalone_cases()}
    for aid, size in expected.items():
        assert len(by_id[aid].attacked_text) == size


# ---------------------------------------------------------------------------------------
# Unique attack ids
# ---------------------------------------------------------------------------------------

def test_no_duplicate_attack_ids():
    cases = _full_suite()
    ids = [c.attack_id for c in cases]
    assert len(ids) == len(set(ids))


def test_suite_is_deterministic():
    first = {c.attack_id: c.attacked_text for c in _full_suite()}
    md.reset()
    second = {c.attack_id: c.attacked_text for c in _full_suite()}
    assert first == second


# ---------------------------------------------------------------------------------------
# Metadata layer
# ---------------------------------------------------------------------------------------

def test_every_case_has_metadata():
    cases = _full_suite()
    manifest = md.manifest()
    for case in cases:
        meta = manifest.get(case.attack_id)
        assert meta is not None, f"no metadata for {case.attack_id}"
        assert meta.family == case.category
        assert meta.relation in md.RELATIONS
        assert meta.oracle in md.ORACLES
        assert meta.validity_tier in md.VALIDITY_TIERS


def test_requires_baseline_matches_baseline_id():
    _full_suite()
    manifest = md.manifest()
    for case in _full_suite():
        meta = manifest[case.attack_id]
        assert meta.requires_baseline == (case.baseline_id is not None)


def test_metadata_rejects_bad_vocabulary():
    with pytest.raises(ValueError):
        md.AttackMetadata(
            attack_id="x", family="encoding", subfamily="y",
            relation="not_a_relation", oracle=md.ORACLE_LABEL_MATCH_BASELINE,
            source="s", validity_tier=md.TIER_GOLD,
        )


# ---------------------------------------------------------------------------------------
# The Unicode facts the report's headline rests on
# ---------------------------------------------------------------------------------------

def test_homoglyph_survives_nfkc_but_fullwidth_folds():
    homo = encoding.LATIN_TO_CONFUSABLE["a"]
    assert unicodedata.normalize("NFKC", homo) == homo   # confusable NOT folded
    fw, _ = encoding.to_fullwidth("happy")
    assert unicodedata.normalize("NFKC", fw) == "happy"  # compatibility form folded


def test_zero_width_chars_are_format_category():
    # Every zero-width char we insert must be Unicode category 'Cf' so V2's control-strip
    # (category[0] == 'C') actually removes it -- otherwise the before/after claim is wrong.
    for ch in encoding._ZERO_WIDTH:
        assert unicodedata.category(ch) == "Cf"


def test_homoglyph_case_contains_non_ascii_letter():
    cases = encoding.build_derived(BASELINES[0])
    homo = next(c for c in cases if "homoglyph" in c.attack_id)
    assert any(ord(ch) > 127 for ch in homo.attacked_text)
