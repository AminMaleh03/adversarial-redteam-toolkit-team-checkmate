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

import hashlib
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
def test_review_attribution_is_honest_after_review():
    """Human review is complete; attribution must stay honest (author = AI draft, reviewer =
    the human), and no case is promoted to GOLD just because review happened."""
    prov = _load(PROVENANCE)
    assert prov["no_model_inference"] is True
    assert "not a blind" in prov["exposure_statement"].lower()
    assert "AI draft" in prov["author"]                        # author is the AI draft, not hand-written
    assert prov["review"]["reviewer"] == "Lamei (Task 4 owner)"
    assert "ChatGPT" in prov["review"]["method"] and "human" in prov["review"]["method"].lower()
    for v in prov["variants"].values():
        assert "AI draft" in v["author"]
        assert v["reviewer"] == "Lamei (Task 4 owner)"
        assert "ChatGPT" in v["review_method"]
    tiers = {v["proposed_tier"] for v in prov["variants"].values()}
    assert tiers == {"SILVER", "REVIEW"}                       # NO GOLD promotion
    # ambiguous/high-risk candidates stay visible as REVIEW, never silently scored
    for v in prov["variants"].values():
        if v["semantic_risk"] == "high":
            assert v["proposed_tier"] == "REVIEW"


def test_review_sheet_decisions_match_tiers():
    import csv
    from collections import Counter
    with (CASES_DIR / "oces_review_sheet.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 82
    for r in rows:
        assert r["reviewer"] == "Lamei (Task 4 owner)"
        expected = "APPROVE" if r["proposed_tier"] == "SILVER" else "KEEP_REVIEW"
        assert r["Lamei_decision"] == expected
    assert Counter(r["Lamei_decision"] for r in rows) == {"APPROVE": 50, "KEEP_REVIEW": 32}


def test_provenance_does_not_embed_a_freeze_commit():
    """The authoring provenance must never embed the freeze commit (a commit can't contain its
    own SHA). The freeze SHA lives only in the separate Phase-5 freeze_provenance record."""
    prov = _load(PROVENANCE)
    assert "freeze_commit" not in prov and "freeze_sha" not in prov


def test_pre_freeze_summary_is_consistent():
    s = _load(PROVENANCE)["pre_freeze_summary"]
    assert s["clean_requests"] == 41 and s["variants"] == 82
    assert s["total_additional_requests"] == 123
    assert s["family_counts"] == {"oces.distractor": 41, "oces.paraphrase": 41}
    assert s["tier_distribution"] == {"REVIEW": 32, "SILVER": 50}
    assert s["coverage_distribution"] == {"not_targeted": 82}
    assert s["all_comfortably_below_limit"] is True
    assert s["model_prediction_queries_before_freeze"] == 0
    assert s["defense_identity"]["endpoint_v2_git_blob"] == "b71787e3bf39e4062f883c9e34fae78d5b7c6263"
    assert s["defense_identity"]["foundation_commit"] == "257e15f3432aa29a3942d52b2cf3befb12ba3354"


def test_freeze_content_hashes_match_actual_files():
    import hashlib
    doc = _load(CASES_DIR / "freeze_content_hashes.json")
    assert "freeze_content_hashes.json" not in json.dumps(doc["files"])   # never hashes itself
    for rel, sha in doc["files"].items():
        actual = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        assert actual == sha, f"{rel}: hash drift ({actual} != {sha})"


def test_freeze_provenance_references_freeze_commit_and_matches_artifacts():
    """Phase-5 freeze provenance: references the freeze commit (not embedded in it), records
    zero pre-freeze inference, and its frozen-artifact hashes match the committed files.

    Two of the seven ``frozen_artifacts_sha256`` entries (``provenance.json`` and
    ``build_oces.py`` themselves) no longer match on-disk bytes as of the integration
    repair that made the generator cross-platform byte-reproducible (generator_version
    1.2.0 -> 1.2.1): both files embed that version string. That is expected and
    documented, not drift -- Freeze Commit B's own ``frozen_artifacts_sha256`` block is
    a historical record and is deliberately left unedited (see the appended
    ``integration_repair`` block in this same file), while
    ``attacks/data/oces/freeze_content_hashes.json`` is the current authoritative hash
    record. This test checks both: the five untouched files still match Freeze B
    directly (a real regression guard), and the two superseded files match the
    ``integration_repair`` block's documented new hash exactly (proving that block is
    honest about what it claims, not just present).
    """
    fp = _load(CASES_DIR / "freeze_provenance.json")
    assert fp["model_inference_before_freeze"] is False
    assert len(fp["freeze_commit"]) == 40
    assert fp["freeze_commit_utc"].endswith("Z")
    assert fp["defense_identity"]["endpoint_v2_git_blob"] == "b71787e3bf39e4062f883c9e34fae78d5b7c6263"
    assert fp["foundation_commit"] == "257e15f3432aa29a3942d52b2cf3befb12ba3354"
    assert fp["counts"]["total_additional_requests"] == 123
    assert fp["tier_distribution"] == {"SILVER": 50, "REVIEW": 32}
    assert fp["coverage_distribution"] == {"not_targeted": 82}
    assert fp["human_review"]["reviewer"] == "Lamei (Task 4 owner)"

    superseded = {"attacks/data/oces/provenance.json", "baseline/oces/build_oces.py"}
    for rel, sha in fp["frozen_artifacts_sha256"].items():
        if rel not in superseded:
            assert hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == sha, f"{rel}: drift"

    repair = fp["integration_repair"]
    assert repair["previous_generator_version"] == fp["generator_version"] == "1.2.0"
    assert repair["new_generator_version"] == "1.2.1"
    assert repair["oces_semantic_content_unchanged"] is True
    for rel in superseded:
        entry = repair["changed_files"][rel]
        assert entry["previous_sha256"] == fp["frozen_artifacts_sha256"][rel], (
            f"{rel}: integration_repair's previous_sha256 does not match Freeze B's own record"
        )
        actual = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        assert actual == entry["new_sha256"], (
            f"{rel}: current on-disk hash does not match integration_repair's documented new_sha256"
        )
        # And that documented new hash must equal the current authoritative record too.
        current = _load(FREEZE_CONTENT_HASHES)["files"][rel]
        assert actual == current, f"{rel}: freeze_content_hashes.json disagrees with the repair note"


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
# The seven artifacts the freeze record hashes (frozen_content_hashes.json's own note:
# "does not hash itself"), plus that file, plus the CSV review sheet build() also writes.
# freeze_content_hashes.json and the CSV are regenerated by build() but are not themselves
# in the frozen-seven list.
FREEZE_HASHED_ARTIFACTS = (
    EMO_SEEDS, SENT_SEEDS, EMO_CASES, SENT_CASES, PROVENANCE,
    SEEDS_DIR / "oces_content.py", Path(build_oces.__file__),
)
FREEZE_CONTENT_HASHES = CASES_DIR / "freeze_content_hashes.json"


def test_rebuild_reproduces_committed_oces_files():
    """Guarded on tokenizer availability; then rebuild UNGUARDED and diff real bytes.

    ``build_oces.build()`` writes in place, over the tracked frozen artifacts, and also
    regenerates ``freeze_content_hashes.json`` from raw on-disk bytes. Found during PR #8
    integration and fixed in the generator itself (``_write_json`` now opens with
    ``newline="\\n"``, generator version 1.2.0 -> 1.2.1; see this test module's package for
    the full integration-repair trail in ``attacks/data/oces/freeze_provenance.json``'s
    appended ``integration_repair`` block). This test now proves the fix rather than working
    around its absence: it compares ``read_bytes()``, not ``read_text()``, so it fails again
    if any writer ever reintroduces a platform-dependent line ending.

    Every byte this rebuild touches is restored in a ``finally``, so the committed freeze
    identity survives the test regardless of pass or fail, and the run order of this module
    never matters.
    """
    try:
        from transformers import AutoTokenizer
        AutoTokenizer.from_pretrained(build_oces.EMOTION_TOKENIZER[0],
                                      revision=build_oces.EMOTION_TOKENIZER[1])
        AutoTokenizer.from_pretrained(build_oces.SENTIMENT_TOKENIZER[0],
                                      revision=build_oces.SENTIMENT_TOKENIZER[1])
    except Exception as exc:                                    # noqa: BLE001 - tokenizer unavailable
        pytest.skip(f"pinned tokenizers unavailable offline: {exc}")

    # Source files (oces_content.py, build_oces.py) are read-only inputs to the rebuild, not
    # outputs of it -- back them up too, defensively, but build() never writes them.
    rebuilt_outputs = (EMO_SEEDS, SENT_SEEDS, EMO_CASES, SENT_CASES, PROVENANCE,
                        FREEZE_CONTENT_HASHES, CASES_DIR / "oces_review_sheet.csv")
    before_bytes = {p: p.read_bytes() for p in rebuilt_outputs if p.exists()}

    try:
        build_oces.build()                                      # rewrites the files in place

        # 1. True byte equality on every generated file that carries a frozen hash -- not
        #    content equality through a newline-normalising read.
        for path in (EMO_SEEDS, SENT_SEEDS, EMO_CASES, SENT_CASES, PROVENANCE):
            actual = path.read_bytes()
            assert actual == before_bytes[path], (
                f"{path.name}: rebuild produced different bytes than committed "
                f"(len {len(actual)} vs {len(before_bytes[path])}) -- check for CRLF drift"
            )
            assert b"\r\n" not in actual, f"{path.name}: rebuild wrote CRLF line endings"

        # 2. Every SHA-256 in the regenerated freeze record must match the pre-rebuild
        #    committed record exactly (the generator recomputes these from raw bytes, so a
        #    byte match above does not by itself prove the record's own hashes are right).
        before_record = json.loads(before_bytes[FREEZE_CONTENT_HASHES].decode("utf-8"))
        after_record = json.loads(FREEZE_CONTENT_HASHES.read_bytes().decode("utf-8"))
        assert before_record["files"] == after_record["files"], (
            "freeze_content_hashes.json's recorded hashes changed on rebuild"
        )

        # 3. The freeze record covers exactly the intended seven artifacts -- not five, not
        #    a subset silently short of the frozen set.
        assert set(after_record["files"]) == {
            "baseline/oces/emotion_seeds.json", "baseline/oces/sentiment_seeds.json",
            "attacks/data/oces/emotion_cases.json", "attacks/data/oces/sentiment_cases.json",
            "attacks/data/oces/provenance.json",
            "baseline/oces/oces_content.py", "baseline/oces/build_oces.py",
        }, "freeze_content_hashes.json does not cover the intended seven-artifact set"

        # 4. Cross-check the freeze record against actual on-disk bytes of every artifact,
        #    including the two source files it names but does not itself regenerate.
        for rel, expected_sha in after_record["files"].items():
            actual_sha = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
            assert actual_sha == expected_sha, f"{rel}: on-disk hash does not match the freeze record"

        # 5. No writer emitted CRLF anywhere in the regenerated set, except the CSV review
        #    sheet: csv.DictWriter's default dialect legitimately terminates rows with
        #    "\r\n" per RFC 4180, and that file already opens with newline="" (the correct
        #    idiom) and is not part of the frozen-seven hash set. Everything else here is
        #    JSON and must be pure LF.
        for path in rebuilt_outputs:
            if path.exists() and path.suffix != ".csv":
                assert b"\r\n" not in path.read_bytes(), f"{path.name}: contains CRLF bytes"
    finally:
        for path, raw in before_bytes.items():
            path.write_bytes(raw)

    # 6. Nothing rebuilt remains modified once every byte is restored.
    for path, raw in before_bytes.items():
        assert path.read_bytes() == raw, f"{path.name}: not fully restored after the test"
