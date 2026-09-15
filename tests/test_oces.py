"""
Tests for the frozen OCES additional evaluation (Task 4, Phase 4). Owner: Lamei.

Covers the committed seeds/cases/provenance: correct counts and label balance, deterministic
model-free seed selection, one paraphrase + one neutral distractor per seed, valid frozen
metadata (suite=oces, invariant/label-match oracle, the two OCES families only -- no
negation/directional oracle), sanitation-invariance and token-limit of every variant, honest
review status (nothing marked human-reviewed), and that every frozen case round-trips through
the real AttackCase/AttackMetadata contract and registers under an isolated oces suite.

The mechanical re-checks that need the pinned tokenizers, and the mirror-equivalence check
that needs the frozen sanitizer, are guarded: they skip only if the external asset is
genuinely unavailable, and otherwise run UNGUARDED so a real regression fails.
"""

import json
from pathlib import Path

import pytest

from contract import (
    AttackCase, OCES_FAMILIES, OCES_FAMILY_PARAPHRASE, OCES_FAMILY_DISTRACTOR, SUITE_OCES,
)
from baseline.load import load_baseline
from baseline.oces import build_oces
from attacks import metadata as md

REPO = Path(__file__).resolve().parents[1]
SEEDS_DIR = REPO / "baseline" / "oces"
CASES_DIR = REPO / "attacks" / "data" / "oces"

EMO_SEEDS = SEEDS_DIR / "emotion_seeds.json"
SENT_SEEDS = SEEDS_DIR / "sentiment_seeds.json"
EMO_CASES = CASES_DIR / "emotion_cases.json"
SENT_CASES = CASES_DIR / "sentiment_cases.json"
PROVENANCE = CASES_DIR / "provenance.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------- seeds
def test_emotion_seeds_three_per_label_over_seven_labels():
    seeds = load_baseline(EMO_SEEDS)
    assert len(seeds) == 21
    from collections import Counter
    by_label = Counter(s.label for s in seeds)
    assert set(by_label) == {"anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"}
    assert all(n == 3 for n in by_label.values())


def test_sentiment_seeds_ten_per_label():
    seeds = load_baseline(SENT_SEEDS)
    assert len(seeds) == 20
    from collections import Counter
    by_label = Counter(s.label for s in seeds)
    assert by_label == {"NEGATIVE": 10, "POSITIVE": 10}


def test_seed_selection_is_deterministic_and_matches_committed():
    emo = [s.baseline_id for s in build_oces.select_emotion_seeds()]
    sent = [s.baseline_id for s in build_oces.select_sentiment_seeds()]
    assert emo == [s.baseline_id for s in build_oces.select_emotion_seeds()]     # deterministic
    assert sent == [s.baseline_id for s in build_oces.select_sentiment_seeds()]
    assert emo == [s["baseline_id"] for s in _load(EMO_SEEDS)]                   # matches committed
    assert sent == [s["baseline_id"] for s in _load(SENT_SEEDS)]


def test_oces_clean_requests_are_clean_text_of_the_committed_baselines():
    """The OCES clean request (seed 'text') is clean_text(committed baseline); the exact raw
    source is preserved separately in provenance. The core baselines are NOT modified."""
    prov = _load(PROVENANCE)["variants"]
    raw_by_seed = {}
    for v in prov.values():
        raw_by_seed[v["seed_baseline_id"]] = (v["raw_source_text"], v["clean_request"])

    emo_base = {b.baseline_id: b.text for b in load_baseline(REPO / "baseline" / "baseline.json")}
    for s in load_baseline(EMO_SEEDS):
        raw, req = raw_by_seed[s.baseline_id]
        assert raw == emo_base[s.baseline_id]                       # raw source unchanged
        assert s.text == req == build_oces._clean_text(emo_base[s.baseline_id])
    sent_base = {b.baseline_id: b.text for b in load_baseline(REPO / "baseline" / "sentiment_baseline.json")}
    for s in load_baseline(SENT_SEEDS):
        raw, req = raw_by_seed[s.baseline_id]
        assert raw == sent_base[s.baseline_id]
        assert s.text == req == build_oces._clean_text(sent_base[s.baseline_id])


def test_all_clean_requests_are_sanitation_invariant_and_bounded():
    """CONTRACTS 6.6: every OCES original (clean request) must itself pass the input gates."""
    prov = _load(PROVENANCE)["variants"]
    seen = set()
    for v in prov.values():
        req = v["clean_request"]
        assert build_oces._clean_text(req) == req                  # sanitation-invariant
        lens = v["tokenizer_lengths"]["clean_request"]
        assert lens["emotion"] < build_oces.TOKEN_LIMIT
        assert lens["sentiment"] < build_oces.TOKEN_LIMIT
        seen.add(v["seed_baseline_id"])
    assert len(seen) == 41                                          # all 41 clean requests


# ------------------------------------------------------------------------- cases
def test_counts_and_one_paraphrase_plus_one_distractor_per_seed():
    emo, sent = _load(EMO_CASES), _load(SENT_CASES)
    assert len(emo) == 42 and len(sent) == 40
    for cases, seed_path in ((emo, EMO_SEEDS), (sent, SENT_SEEDS)):
        seed_ids = {s["baseline_id"] for s in _load(seed_path)}
        from collections import defaultdict
        fam = defaultdict(set)
        for entry in cases:
            fam[entry["case"]["baseline_id"]].add(entry["metadata"]["declared_family"])
        assert set(fam) == seed_ids
        assert all(f == {OCES_FAMILY_PARAPHRASE, OCES_FAMILY_DISTRACTOR} for f in fam.values())


def test_every_case_has_valid_frozen_metadata_and_contract_shape():
    from contract import COVERAGE_NOT_TARGETED
    for entry in _load(EMO_CASES) + _load(SENT_CASES):
        case = AttackCase(**entry["case"])                       # reconstructs / validates shape
        m = entry["metadata"]
        meta = md.AttackMetadata(**m)                            # __post_init__ validates values
        assert case.attack_id == meta.attack_id
        assert case.category == meta.family == meta.declared_family
        assert meta.declared_family in OCES_FAMILIES
        assert meta.suite_id == SUITE_OCES
        assert meta.relation == md.REL_INVARIANT                 # no directional oracle
        assert meta.oracle == md.ORACLE_LABEL_MATCH_BASELINE
        assert meta.validity_tier in md.VALIDITY_TIERS
        assert meta.semantic_risk in md.SEMANTIC_RISK
        assert case.baseline_id is not None and meta.requires_baseline is True
        assert case.is_raw is False and case.attacked_text
        # every OCES case carries an outcome-independent coverage declaration (CONTRACTS 6.5)
        assert meta.coverage_class == COVERAGE_NOT_TARGETED
        assert meta.controls_targeted == []
        assert meta.coverage_rationale and meta.coverage_map_version


def test_distractor_prefix_equals_clean_request_exactly():
    """Causal isolation: a distractor only ADDS a neutral clause; it never rewrites the
    request's casing/punctuation/tokenization."""
    prov = _load(PROVENANCE)["variants"]
    n = 0
    for entry in _load(EMO_CASES) + _load(SENT_CASES):
        if entry["metadata"]["declared_family"] != OCES_FAMILY_DISTRACTOR:
            continue
        req = entry["case"]["original_text"]
        variant = entry["case"]["attacked_text"]
        clause = prov[entry["case"]["attack_id"]]["distractor_clause"]
        assert variant == f"{req} {clause}"                     # prefix is the exact request
        n += 1
    assert n == 41                                              # one distractor per seed


def test_only_the_two_oces_families_no_negation_or_new_families():
    families = {e["metadata"]["declared_family"] for e in _load(EMO_CASES) + _load(SENT_CASES)}
    assert families == set(OCES_FAMILIES)


def test_variant_baselines_reference_real_seeds():
    seed_ids = {s["baseline_id"] for s in _load(EMO_SEEDS)} | {s["baseline_id"] for s in _load(SENT_SEEDS)}
    for entry in _load(EMO_CASES) + _load(SENT_CASES):
        assert entry["case"]["baseline_id"] in seed_ids


def test_attack_ids_unique():
    ids = [e["case"]["attack_id"] for e in _load(EMO_CASES) + _load(SENT_CASES)]
    assert len(set(ids)) == len(ids) == 82


# ------------------------------------------------------- mechanical (sanitation + tokens)
def test_every_variant_is_sanitation_invariant_and_under_limit_in_provenance():
    """Uses the builder's clean_text mirror (no model) + the committed token lengths."""
    prov = _load(PROVENANCE)["variants"]
    for entry in _load(EMO_CASES) + _load(SENT_CASES):
        text = entry["case"]["attacked_text"]
        assert build_oces._clean_text(text) == text            # ordinary clean English
        lens = prov[entry["case"]["attack_id"]]["tokenizer_lengths"]["variant"]
        assert lens["emotion"] < build_oces.TOKEN_LIMIT
        assert lens["sentiment"] < build_oces.TOKEN_LIMIT


def test_clean_text_mirror_matches_frozen_sanitizer():
    """The builder's clean_text mirror must equal endpoint/v2.py's frozen clean_text.

    Guarded: importing endpoint.v2 loads model weights (no prediction is run). Skips only if
    that asset is genuinely unavailable; otherwise the equivalence check runs unguarded.
    """
    try:
        from endpoint.v2 import clean_text as frozen_clean_text
    except Exception as exc:                                    # noqa: BLE001 - model asset unavailable
        pytest.skip(f"frozen sanitizer/model asset unavailable: {exc}")
    for entry in _load(EMO_CASES) + _load(SENT_CASES):
        for text in (entry["case"]["original_text"], entry["case"]["attacked_text"]):
            assert build_oces._clean_text(text) == frozen_clean_text(text)


# ------------------------------------------------------------------------- honesty / discipline
def test_no_case_is_marked_human_reviewed_and_author_is_honest():
    prov = _load(PROVENANCE)
    assert prov["review"]["reviewer"] is None
    assert prov["no_model_inference"] is True
    assert "not a blind" in prov["exposure_statement"].lower()
    assert "AI draft" in prov["author"]                        # honest authorship, not hand-written
    for v in prov["variants"].values():
        assert v["reviewer"] is None
        assert v["review_method"] == "ai_drafted_pending_human_review"
        assert "AI draft" in v["author"]
    # ambiguous/high-risk candidates stay visible as REVIEW, never silently scored
    for v in prov["variants"].values():
        if v["semantic_risk"] == "high":
            assert v["proposed_tier"] == "REVIEW"


def test_provenance_carries_no_freeze_commit_yet():
    """Phase 4 stops before the freeze commit; provenance must not fabricate one."""
    prov = _load(PROVENANCE)
    assert "freeze_commit" not in prov and "freeze_sha" not in prov


# ------------------------------------------------------------------------- isolation
def test_oces_cases_register_in_an_isolated_oces_suite():
    md.reset()
    with md.scoped_registry():
        for entry in _load(EMO_CASES) + _load(SENT_CASES):
            md.register(AttackCase(**entry["case"]), md.AttackMetadata(**entry["metadata"]))
        man = md.manifest()
        assert len(man) == 82
        assert {m.suite_id for m in man.values()} == {SUITE_OCES}
    assert md.manifest() == {}                                  # scope restored
    md.reset()


# ------------------------------------------------------------------------- rebuild parity
def test_rebuild_reproduces_committed_oces_files():
    """Guarded on tokenizer availability; then rebuild UNGUARDED and diff byte-for-byte."""
    try:
        from transformers import AutoTokenizer
        AutoTokenizer.from_pretrained(build_oces.EMOTION_TOKENIZER[0],
                                      revision=build_oces.EMOTION_TOKENIZER[1])
        AutoTokenizer.from_pretrained(build_oces.SENTIMENT_TOKENIZER[0],
                                      revision=build_oces.SENTIMENT_TOKENIZER[1])
    except Exception as exc:                                    # noqa: BLE001 - tokenizer unavailable
        pytest.skip(f"pinned tokenizers unavailable offline: {exc}")

    before = {p: p.read_text(encoding="utf-8")
              for p in (EMO_SEEDS, SENT_SEEDS, EMO_CASES, SENT_CASES, PROVENANCE)}
    build_oces.build()                                          # rewrites the files
    for path, text in before.items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} not reproduced"
