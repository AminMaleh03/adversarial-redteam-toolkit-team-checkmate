"""
Tests for the attack library (owner: Lamei).

Covers the subtask requirements plus the hardening-pass points: exact N-1/N/N+1 boundaries
with a deterministic fake counter, measured token counts stored in metadata, boundary loop
protection, genuine leading/middle/trailing position variants, dose accounting, provenance
presence, the Unicode facts every sanitizer claim rests on, fingerprint-based duplicate-id
detection, correct oracles (no label oracle on an over-limit rejection case), and per-family
case-count floors so a module cannot silently stop generating.

NOTE on the raw flag: any body that cannot be produced by serialising {"text": "<string>"}
must be raw (type confusion, missing/renamed/extra fields, nested JSON, wrong content type).
The enforced invariant is "raw iff not a plain string payload"; broken JSON and wrong content
type are additionally asserted raw. Flagged for Ahsan in the PR.
"""

import json
import unicodedata
from dataclasses import fields

import pytest

from contract import AttackCase, BaselineCase
from attacks import library, boundary, encoding, perturbation
from attacks import metadata as md


BASELINES = [
    BaselineCase("b001", "I am extremely happy today", "joy", "handwritten"),
    BaselineCase("b002", "The service was disgusting and awful", "disgust", "handwritten"),
    BaselineCase("b003", "Everything feels calm and ordinary right now", "neutral", "handwritten"),
]


@pytest.fixture(autouse=True)
def _clean_registry():
    md.reset()
    yield
    md.reset()


def _full_suite():
    return library.build_suite(BASELINES)


# --------------------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------------------

def test_every_payload_is_an_attackcase():
    for case in _full_suite():
        assert isinstance(case, AttackCase)
        assert isinstance(case.attack_id, str) and case.attack_id
        assert isinstance(case.category, str) and case.category
        assert isinstance(case.is_raw, bool)


def test_field_names_match_contract():
    names = {f.name for f in fields(AttackCase)}
    assert {"attack_id", "baseline_id", "category", "original_text",
            "attacked_text", "is_raw", "raw_body", "raw_headers"} <= names


# --------------------------------------------------------------------------------------
# Derived vs standalone, raw flag
# --------------------------------------------------------------------------------------

def test_derived_carry_baseline_id_and_standalone_do_not():
    for baseline in BASELINES:
        for case in library.build_derived(baseline):
            assert case.baseline_id == baseline.baseline_id
    for case in library.standalone_cases():
        assert case.baseline_id is None


def test_raw_cases_are_well_formed():
    for case in library.standalone_cases():
        if case.is_raw:
            assert case.raw_body is not None
            assert isinstance(case.raw_headers, dict) and case.raw_headers
            assert case.attacked_text is None
        else:
            assert isinstance(case.attacked_text, str)
            assert case.raw_body is None


def test_broken_json_and_wrong_content_type_are_raw():
    by_id = {c.attack_id: c for c in library.standalone_cases()}
    assert by_id["malformed.broken_json"].is_raw is True
    assert by_id["malformed.wrong_content_type"].is_raw is True
    assert by_id["malformed.wrong_content_type"].raw_headers["Content-Type"] == "text/plain"


def test_no_derived_case_is_raw():
    for baseline in BASELINES:
        for case in library.build_derived(baseline):
            assert case.is_raw is False


def test_structured_cases_json_serialize():
    for case in _full_suite():
        if not case.is_raw:
            json.dumps({"text": case.attacked_text})  # must not raise


# --------------------------------------------------------------------------------------
# Perturbations
# --------------------------------------------------------------------------------------

def test_every_perturbation_editor_changes_text():
    word = "extremely"
    for row in perturbation._PERTURBATIONS:
        editor = row[1]
        assert editor(word) != word, f"{editor.__name__} did not change {word!r}"


def test_char_ops_preserve_first_and_last_letter():
    word = "extremely"
    for name in ("swap_adjacent", "keyboard_typo", "delete_char", "insert_char"):
        out = getattr(perturbation, name)(word)
        assert out[0] == word[0] and out[-1] == word[-1]


def test_word_split_inserts_a_space():
    assert " " in perturbation.word_split("extremely")


def test_no_accidental_noop_derived_cases():
    for baseline in BASELINES:
        for case in library.build_derived(baseline):
            assert case.attacked_text != case.original_text


# --------------------------------------------------------------------------------------
# Oversized
# --------------------------------------------------------------------------------------

def test_oversized_payloads_are_exact_text_value_size():
    expected = {
        "malformed.oversized_100kb": 100 * 1024,
        "malformed.oversized_1mb": 1024 * 1024,
        "malformed.oversized_10mb": 10 * 1024 * 1024,
    }
    by_id = {c.attack_id: c for c in library.standalone_cases()}
    for aid, size in expected.items():
        assert len(by_id[aid].attacked_text) == size
        assert "TEXT-VALUE" in md.metadata_for(aid).notes  # honest about body-size nuance


# --------------------------------------------------------------------------------------
# Nested JSON depth ladder
# --------------------------------------------------------------------------------------

def test_nested_json_depth_ladder_present_and_parseable():
    by_id = {c.attack_id: c for c in library.standalone_cases()}
    for depth in (32, 128, 512, 1024, 2000):
        aid = f"malformed.deeply_nested_json_d{depth}"
        assert aid in by_id and by_id[aid].is_raw
    # a shallow one must be genuinely valid JSON
    shallow = by_id["malformed.deeply_nested_json_d32"].raw_body
    assert json.loads(shallow)["text"]["a"]["a"]  # nests as intended


# --------------------------------------------------------------------------------------
# Unique ids + determinism + fingerprint dedup
# --------------------------------------------------------------------------------------

def test_no_duplicate_attack_ids():
    ids = [c.attack_id for c in _full_suite()]
    assert len(ids) == len(set(ids))


def test_suite_is_deterministic():
    first = {c.attack_id: c.attacked_text for c in _full_suite()}
    md.reset()
    second = {c.attack_id: c.attacked_text for c in _full_suite()}
    assert first == second


def test_duplicate_id_with_different_payload_is_rejected():
    c1 = AttackCase("dup.x", None, "encoding", None, "hello")
    meta = md.AttackMetadata("dup.x", "encoding", "sf", md.REL_AVAILABILITY,
                             md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD)
    md.register(c1, meta)
    c2 = AttackCase("dup.x", None, "encoding", None, "DIFFERENT")
    with pytest.raises(ValueError):
        md.register(c2, meta)


# --------------------------------------------------------------------------------------
# Boundary: exact N-1/N/N+1 with a fake counter, measured stored, loop protection
# --------------------------------------------------------------------------------------

def _word_counter(text: str) -> int:
    return len(text.split())


def test_boundary_exact_n_minus_one_n_n_plus_one():
    md.reset()
    boundary.standalone(token_counter=_word_counter, max_tokens=10)
    m = md.manifest()
    assert m["boundary.length.minus_one"].boundary_measured == 9
    assert m["boundary.length.at_limit"].boundary_measured == 10
    assert m["boundary.length.plus_one"].boundary_measured > 10
    assert m["boundary.length.minus_one"].boundary_source == "tokenizer"
    assert m["boundary.length.plus_one"].expected_sanitizer_behavior == md.SAN_V2_REJECTS_LENGTH


def test_boundary_approximate_mode_when_no_counter():
    md.reset()
    boundary.standalone()
    m = md.manifest()
    assert m["boundary.length.clearly_under"].boundary_source == "approximate_word_estimate"


def test_boundary_generation_is_bounded_with_pathological_counter():
    # A counter that never exceeds the target would loop forever without the guard.
    md.reset()
    cases = boundary.standalone(token_counter=lambda t: 0, max_tokens=10)
    assert cases  # returned instead of hanging


# --------------------------------------------------------------------------------------
# Encoding: position variants + dose accounting + Unicode facts
# --------------------------------------------------------------------------------------

def test_homoglyph_positions_touch_different_regions():
    md.reset()
    b = BaselineCase("bx", "operations analysis reconsideration procedures", "neutral", "hw")
    cases = {c.attack_id: c for c in encoding.build_derived(b)}
    lead = cases["bx.encoding.homoglyph.leading.d1"].attacked_text
    trail = cases["bx.encoding.homoglyph.trailing.d1"].attacked_text
    lead_pos = next(i for i, ch in enumerate(lead) if ord(ch) > 127)
    trail_pos = next(i for i, ch in enumerate(trail) if ord(ch) > 127)
    assert lead_pos < trail_pos


def test_dose_records_chars_actually_applied():
    md.reset()
    b = BaselineCase("bx", "operations analysis reconsideration procedures", "neutral", "hw")
    encoding.build_derived(b)
    meta = md.metadata_for("bx.encoding.homoglyph.leading.d3")
    # dose stored equals the number of substituted (non-ascii) characters
    text = {c.attack_id: c for c in encoding.build_derived(b)}["bx.encoding.homoglyph.leading.d3"].attacked_text
    assert meta.dose == sum(1 for ch in text if ord(ch) > 127)


def test_homoglyph_survives_nfkc_but_fullwidth_folds():
    assert unicodedata.normalize("NFKC", encoding.LATIN_TO_CONFUSABLE["a"]) == encoding.LATIN_TO_CONFUSABLE["a"]
    fw, _ = encoding.to_fullwidth("happy")
    assert unicodedata.normalize("NFKC", fw) == "happy"


def test_zero_width_chars_are_format_category():
    for ch in encoding._ZERO_WIDTH:
        assert unicodedata.category(ch) == "Cf"


def test_control_constants_have_expected_codepoints():
    assert [ord(c) for c in encoding._ZERO_WIDTH] == [0x200B, 0x200C, 0x200D, 0x2060]
    assert ord(encoding._RLO) == 0x202E and ord(encoding._PDF) == 0x202C
    assert ord(encoding._BACKSPACE) == 0x08 and ord(encoding._NULL) == 0x00


# --------------------------------------------------------------------------------------
# Metadata: vocabulary, provenance, requires_baseline, oracle correctness
# --------------------------------------------------------------------------------------

def test_every_case_has_valid_metadata():
    for case in _full_suite():
        meta = md.metadata_for(case.attack_id)
        assert meta is not None, f"no metadata for {case.attack_id}"
        assert meta.family == case.category
        assert meta.relation in md.RELATIONS
        assert meta.oracle in md.ORACLES
        assert meta.validity_tier in md.VALIDITY_TIERS
        assert meta.source
        assert meta.requires_baseline == (case.baseline_id is not None)


def test_uts39_cases_carry_source_version_and_url():
    md.reset()
    encoding.build_derived(BASELINES[0])
    meta = md.metadata_for("b001.encoding.homoglyph.leading.d1")
    assert meta.source_version and meta.source_url


def test_metadata_rejects_bad_vocabulary():
    for bad in ({"relation": "nope"}, {"position": "sideways"}, {"boundary_source": "vibes"}):
        kwargs = dict(attack_id="x", family="encoding", subfamily="y",
                      relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
                      source="s", validity_tier=md.TIER_GOLD)
        kwargs.update(bad)
        with pytest.raises(ValueError):
            md.AttackMetadata(**kwargs)


def test_over_limit_truncation_is_not_a_label_oracle():
    md.reset()
    library.build_derived(BASELINES[0])
    over = md.metadata_for("b001.truncation.signal_start_over_limit")
    assert over.oracle == md.ORACLE_GRACEFUL_OR_TRUNCATE
    assert over.relation == md.REL_BOUNDARY
    short = md.metadata_for("b001.truncation.signal_start_short")
    assert short.oracle == md.ORACLE_LABEL_MATCH_BASELINE


# --------------------------------------------------------------------------------------
# Per-family case-count floors (a module must not silently stop generating)
# --------------------------------------------------------------------------------------

def test_standalone_family_counts():
    from collections import Counter
    counts = Counter(c.category for c in library.standalone_cases())
    assert counts["malformed"] == 13   # 5 schema + 5 nesting + 3 oversized
    assert counts["boundary"] == 11    # 3 strings + 5 type-confusion + 3 length
    assert counts["encoding"] == 1     # null byte


def test_derived_family_floors():
    from collections import Counter
    counts = Counter(c.category for c in library.build_derived(BASELINES[0]))
    assert counts["encoding"] >= 12
    assert counts["perturbation"] >= 6
    assert counts["whitespace"] >= 5
    assert counts["truncation"] >= 4
