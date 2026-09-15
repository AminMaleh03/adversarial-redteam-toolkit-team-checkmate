"""
Tests for the frozen-OCES RUNTIME loader (``attacks/oces.py``) and its wiring into
``attacks.library.build_suite(suite="oces")``.

This is distinct from ``tests/test_oces.py``, which covers the frozen DATA itself (Task 4,
Lamei's authoring correctness). This module covers the loader that makes that frozen data
actually executable: hash verification and fail-closed behaviour, deterministic ordering,
task-specific filtering, baseline-set consistency, and real registration/manifest wiring
through the same ``build_suite`` entry point the core suite uses.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from contract import ContractError, SUITE_OCES
from baseline.load import load_baseline
from attacks import library, oces as oces_loader
from attacks.metadata import manifest, reset, scoped_registry

REPO = Path(__file__).resolve().parents[1]
HASH_MANIFEST = REPO / "attacks" / "data" / "oces" / "freeze_content_hashes.json"

EMOTION_SEEDS_PATH = "baseline/oces/emotion_seeds.json"
SENTIMENT_SEEDS_PATH = "baseline/oces/sentiment_seeds.json"


def _emotion_seeds():
    return sorted(load_baseline(EMOTION_SEEDS_PATH), key=lambda b: b.baseline_id)


def _sentiment_seeds():
    return sorted(load_baseline(SENTIMENT_SEEDS_PATH), key=lambda b: b.baseline_id)


def setup_function(_function):
    reset()


def teardown_function(_function):
    reset()


# --------------------------------------------------------------------------- hash integrity


def test_frozen_hash_manifest_declares_exactly_seven_files():
    doc = json.loads(HASH_MANIFEST.read_text(encoding="utf-8"))
    assert len(doc["files"]) == 7
    assert doc["generator_version"] == "1.2.1"


def test_all_seven_frozen_hashes_verify_against_committed_bytes():
    # Exercises the loader's own verification path, not a re-implementation of it.
    oces_loader._verify_frozen_hashes()


def _mirror_all_seven_frozen_files(tmp_path):
    """Copy every file the hash manifest lists, plus the manifest itself, preserving paths."""
    doc = json.loads(HASH_MANIFEST.read_text(encoding="utf-8"))
    for rel in list(doc["files"]) + ["attacks/data/oces/freeze_content_hashes.json"]:
        source = REPO / rel
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
    shadow_manifest = tmp_path / "attacks" / "data" / "oces" / "freeze_content_hashes.json"
    return shadow_manifest


def test_tampered_case_file_is_rejected(tmp_path, monkeypatch):
    shadow_manifest = _mirror_all_seven_frozen_files(tmp_path)
    tampered = tmp_path / "attacks" / "data" / "oces" / "emotion_cases.json"
    tampered.write_bytes(tampered.read_bytes().replace(b"furious", b"TAMPERED"))

    monkeypatch.setattr(oces_loader, "HASH_MANIFEST_PATH", shadow_manifest)
    monkeypatch.setattr(oces_loader, "REPO_ROOT", tmp_path)
    with pytest.raises(ContractError, match="does not match its frozen SHA-256"):
        oces_loader._verify_frozen_hashes()


def test_missing_frozen_artifact_is_rejected(tmp_path, monkeypatch):
    shadow_manifest = _mirror_all_seven_frozen_files(tmp_path)
    (tmp_path / "attacks" / "data" / "oces" / "emotion_cases.json").unlink()

    monkeypatch.setattr(oces_loader, "HASH_MANIFEST_PATH", shadow_manifest)
    monkeypatch.setattr(oces_loader, "REPO_ROOT", tmp_path)
    with pytest.raises(ContractError, match="missing or unreadable"):
        oces_loader._verify_frozen_hashes()


def test_wrong_generator_version_is_rejected(tmp_path, monkeypatch):
    shadow_manifest = _mirror_all_seven_frozen_files(tmp_path)
    doc = json.loads(shadow_manifest.read_text(encoding="utf-8"))
    doc["generator_version"] = "9.9.9"
    shadow_manifest.write_text(json.dumps(doc), encoding="utf-8")

    monkeypatch.setattr(oces_loader, "HASH_MANIFEST_PATH", shadow_manifest)
    monkeypatch.setattr(oces_loader, "REPO_ROOT", tmp_path)
    with pytest.raises(ContractError, match="generator_version"):
        oces_loader._verify_frozen_hashes()


# ---------------------------------------------------------------------- successful loading


def test_load_suite_emotion_counts_order_and_families():
    seeds = _emotion_seeds()
    with scoped_registry():
        cases = library.build_suite(seeds, suite=SUITE_OCES, task_id="emotion_7")
        assert len(cases) == 42
        m = manifest()
        assert {m[c.attack_id].suite_id for c in cases} == {"oces"}
        assert {m[c.attack_id].declared_family for c in cases} == {"oces.paraphrase", "oces.distractor"}
        assert all(c.baseline_id is not None for c in cases)


def test_load_suite_sentiment_counts_and_single_target_shape():
    seeds = _sentiment_seeds()
    with scoped_registry():
        cases = library.build_suite(seeds, suite=SUITE_OCES, task_id="sentiment_2")
        assert len(cases) == 40


def test_load_suite_is_deterministic_across_repeated_calls():
    seeds = _emotion_seeds()
    with scoped_registry():
        first = [c.attack_id for c in library.build_suite(seeds, suite=SUITE_OCES, task_id="emotion_7")]
    with scoped_registry():
        second = [c.attack_id for c in library.build_suite(seeds, suite=SUITE_OCES, task_id="emotion_7")]
    assert first == second


def test_zero_gold_cases_and_documented_tier_totals():
    tiers = {}
    with scoped_registry():
        for seeds, task_id in ((_emotion_seeds(), "emotion_7"), (_sentiment_seeds(), "sentiment_2")):
            cases = library.build_suite(seeds, suite=SUITE_OCES, task_id=task_id)
            m = manifest()
            for case in cases:
                tier = m[case.attack_id].validity_tier
                tiers[tier] = tiers.get(tier, 0) + 1
    assert tiers.get("GOLD", 0) == 0
    assert tiers == {"REVIEW": 32, "SILVER": 50}


def test_coverage_is_carried_from_frozen_metadata_not_restamped():
    seeds = _emotion_seeds()
    with scoped_registry():
        cases = library.build_suite(seeds, suite=SUITE_OCES, task_id="emotion_7")
        m = manifest()
        for case in cases:
            meta = m[case.attack_id]
            assert meta.coverage_class == "not_targeted"
            assert meta.controls_targeted == []
            assert meta.coverage_map_version == "1.0.0"


# ------------------------------------------------------------------------- fail-closed cases


def test_emotion_seeds_cannot_load_sentiment_task():
    seeds = _emotion_seeds()
    with scoped_registry():
        with pytest.raises(ContractError, match="not in the supplied seed set"):
            library.build_suite(seeds, suite=SUITE_OCES, task_id="sentiment_2")


def test_sentiment_seeds_cannot_load_emotion_task():
    seeds = _sentiment_seeds()
    with scoped_registry():
        with pytest.raises(ContractError, match="not in the supplied seed set"):
            library.build_suite(seeds, suite=SUITE_OCES, task_id="emotion_7")


def test_unknown_task_id_for_oces_is_rejected():
    with pytest.raises(ContractError):
        oces_loader.load_suite([], task_id="not_a_real_task")


def test_build_suite_still_rejects_unknown_suite_id():
    with pytest.raises(ContractError, match="unknown suite"):
        library.build_suite(_emotion_seeds(), suite="not_a_real_suite", task_id="emotion_7")


# --------------------------------------------------------------------------- registry isolation


def test_oces_suite_isolated_from_core_suite_in_same_process():
    seeds = _emotion_seeds()
    with scoped_registry():
        library.build_suite(seeds, suite=SUITE_OCES, task_id="emotion_7")
        core_baselines = sorted(load_baseline("baseline/baseline.json"), key=lambda b: b.baseline_id)
        library.build_suite(core_baselines, token_counter=None, max_tokens=None)
        m = manifest()
        suites_present = {meta.suite_id for meta in m.values()}
        assert suites_present == {"oces", "core"}
