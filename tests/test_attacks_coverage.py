"""
Stage 3 coverage-layer tests (owner: Lamei).

Covers the outcome-independent coverage declaration, its strict resolution (unknown/missing
fails loudly), per-case exception precedence, suite-registry isolation edge cases (nested +
exception exit + exact restore of BOTH dicts), and the historical overlay.

Most tests inject a deterministic fake token counter (word count) so they need no model.
"""

import json
from pathlib import Path

import pytest

from contract import AttackCase, BaselineCase, ContractError, COVERAGE_CLASSES
from attacks import library, coverage, build_coverage_map
from attacks import metadata as md

REPO = Path(__file__).resolve().parents[1]
MAP_PATH = REPO / "attacks" / "coverage_map.json"

BASELINES = [
    BaselineCase("b-anger", "I am absolutely furious right now", "anger", "handwritten"),
    BaselineCase("b-joy", "This is the happiest day of my life", "joy", "handwritten"),
]


def _fake_counter(text: str) -> int:
    return len(text.split())


def _build(**kw):
    """Build the full suite in an isolated registry and return (cases, manifest)."""
    with md.scoped_registry():
        cases = library.build_suite(BASELINES, token_counter=_fake_counter, max_tokens=64, **kw)
        return cases, md.manifest()


# ----------------------------------------------------------------------------- map integrity

def test_committed_map_matches_generator():
    committed = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    assert committed == build_coverage_map.build(), (
        "coverage_map.json is stale; re-run `python -m attacks.build_coverage_map`"
    )


def test_map_declarations_are_valid_and_construction_based():
    cmap = coverage.load_coverage_map()          # raises if any declaration is malformed
    basis = cmap["classification_basis"].lower()
    assert basis.startswith("attack construction")
    assert "never" in basis and "results" in basis   # explicitly disclaims outcome-based classing
    for sub, decl in cmap["subfamilies"].items():
        assert decl["coverage_class"] in COVERAGE_CLASSES
        if decl["coverage_class"] == "in_scope":
            assert decl["controls_targeted"], f"{sub} in_scope with no control"
        if decl["coverage_class"] in ("not_targeted", "out_of_scope"):
            assert not decl["controls_targeted"], f"{sub} {decl['coverage_class']} names controls"


def test_map_covers_both_boundary_modes():
    subs = coverage.load_coverage_map()["subfamilies"]
    for name in ("length_minus_one", "length_plus_one",          # tokenizer mode
                 "length_clearly_under", "length_clearly_over"):   # approximate mode
        assert name in subs


# ----------------------------------------------------------------------------- resolution

def test_every_generated_core_case_resolves():
    cases, man = _build()
    unmapped = [c.attack_id for c in cases if man[c.attack_id].coverage_class is None]
    assert unmapped == [], f"unmapped cases: {unmapped[:5]}"
    # and every stamped class is a valid vocabulary member
    for c in cases:
        assert man[c.attack_id].coverage_class in COVERAGE_CLASSES


def test_no_generated_subfamily_is_absent_from_map():
    _, man = _build()
    cmap = coverage.load_coverage_map()
    generated_subs = {m.subfamily for m in man.values()}
    missing = generated_subs - set(cmap["subfamilies"])
    assert missing == set(), f"generated subfamilies missing from map: {missing}"


def test_unknown_subfamily_fails_loud():
    cmap = coverage.load_coverage_map()
    with pytest.raises(ContractError):
        coverage.resolve_declaration("x.__nope__", "__nope__", cmap)


def test_missing_mapping_in_build_fails_loud():
    with md.scoped_registry():
        case = AttackCase("encoding.__bogus__", None, "encoding", None, "hi")
        meta = md.AttackMetadata(
            attack_id="encoding.__bogus__", family="encoding", subfamily="__bogus__",
            relation=md.REL_AVAILABILITY, oracle=md.ORACLE_STAY_AVAILABLE, source="s",
            validity_tier=md.TIER_GOLD,
        )
        md.register(case, meta)
        with pytest.raises(ContractError):
            coverage.stamp_manifest()


def test_per_case_exception_precedence():
    cmap = coverage.load_coverage_map()
    cmap["case_exceptions"]["b-anger.encoding.homoglyph.leading.d1"] = {
        "coverage_class": "mixed",
        "controls_targeted": ["normalization"],
        "coverage_rationale": "test-only exception override",
    }
    decl = coverage.resolve_declaration(
        "b-anger.encoding.homoglyph.leading.d1", "homoglyph", cmap
    )
    assert decl["coverage_class"] == "mixed"       # exception wins over subfamily (not_targeted)


# ----------------------------------------------------------------------------- metadata guards

def test_metadata_rejects_bad_coverage_fields():
    base = dict(attack_id="x", family="encoding", subfamily="y",
                relation=md.REL_INVARIANT, oracle=md.ORACLE_LABEL_MATCH_BASELINE,
                source="s", validity_tier=md.TIER_GOLD)
    for bad in ({"coverage_class": "nope"}, {"controls_targeted": ["nope"]},
                {"suite_id": "nope"}, {"declared_family": "nope"}):
        with pytest.raises(ValueError):
            md.AttackMetadata(**{**base, **bad})


# ----------------------------------------------------------------------------- no orphans

def test_no_orphan_baselines_or_dangling_derived():
    cases, _ = _build()
    baseline_ids = {b.baseline_id for b in BASELINES}
    derived = [c for c in cases if c.baseline_id is not None]
    # every derived case points at a provided baseline (no dangling reference)
    assert all(c.baseline_id in baseline_ids for c in derived)
    # every provided baseline produced at least one derived case (no orphan baseline)
    assert {c.baseline_id for c in derived} == baseline_ids


def test_duplicate_id_different_payload_rejected():
    with md.scoped_registry():
        m = md.AttackMetadata("dup", "encoding", "sf", md.REL_AVAILABILITY,
                              md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD)
        md.register(AttackCase("dup", None, "encoding", None, "a"), m)
        with pytest.raises(ValueError):
            md.register(AttackCase("dup", None, "encoding", None, "DIFFERENT"), m)


# ----------------------------------------------------------------------------- scoped_registry

def test_scoped_registry_nested_exception_and_exact_restore():
    md.reset()
    c1 = AttackCase("s1", None, "encoding", None, "one")
    m1 = md.AttackMetadata("s1", "encoding", "sf", md.REL_AVAILABILITY,
                           md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD)
    md.register(c1, m1)
    outer_manifest = md.manifest()
    outer_fps = dict(md._FINGERPRINTS)

    with md.scoped_registry():
        assert md.manifest() == {}                      # cleared on entry
        c2 = AttackCase("s2", None, "encoding", None, "two")
        md.register(c2, md.AttackMetadata("s2", "encoding", "sf", md.REL_AVAILABILITY,
                                          md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD))
        mid_manifest = md.manifest()
        mid_fps = dict(md._FINGERPRINTS)

        # nested scope that raises inside must still restore to the mid state
        with pytest.raises(RuntimeError):
            with md.scoped_registry():
                assert md.manifest() == {}
                md.register(AttackCase("s3", None, "encoding", None, "three"),
                            md.AttackMetadata("s3", "encoding", "sf", md.REL_AVAILABILITY,
                                              md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD))
                raise RuntimeError("boom inside nested scope")
        assert md.manifest() == mid_manifest            # both dicts restored to mid
        assert md._FINGERPRINTS == mid_fps

    assert md.manifest() == outer_manifest              # outer restored exactly
    assert md._FINGERPRINTS == outer_fps
    md.reset()


# ----------------------------------------------------------------------------- historical overlay

def test_historical_overlay_resolves_and_leaves_archive_untouched(tmp_path):
    archived = REPO / "artifacts" / "benchmark_v6" / "run" / "manifest.json"
    before = archived.read_bytes()
    overlay = coverage.write_historical_overlay(archived, tmp_path / "overlay.json")
    assert len(overlay["coverage_by_attack_id"]) == 1886
    assert overlay["_overlay"]["coverage_map_version"] == coverage.load_coverage_map()["coverage_map_version"]
    assert all(v["coverage_class"] in COVERAGE_CLASSES for v in overlay["coverage_by_attack_id"].values())
    assert archived.read_bytes() == before             # archived raw file never modified
