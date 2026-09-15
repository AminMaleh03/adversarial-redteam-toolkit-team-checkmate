"""
Stage 3 suite/task isolation tests (owner: Lamei).

Proves that generating one task's suite never contaminates another's, that
``scoped_registry`` clears on entry and restores BOTH internal dictionaries exactly on
exit (including on nested use and on an exception), and that ``build_suite``'s new
``suite``/``task_id`` parameters keep the legacy emotion/core behaviour while validating
their inputs.

The core cross-task test is emotion/core -> sentiment/core -> emotion/core. It uses a
deterministic fake token counter (word count), so it needs no model: the emotion vs
sentiment case-count difference is driven by the baseline *text* (content-dependent
subfamilies), not by the tokenizer, so it reproduces offline. One additional test
exercises the REAL pinned sentiment tokenizer and skips cleanly if the assets are not
available offline (it loads a tokenizer only -- never model weights, never a prediction).
"""

import json
from pathlib import Path

import pytest

from contract import ContractError, SUITE_CORE, SUITE_OCES
from baseline.load import load_baseline
from attacks import library
from attacks import metadata as md

REPO = Path(__file__).resolve().parents[1]
EMOTION_BASELINE = REPO / "baseline" / "baseline.json"
SENTIMENT_BASELINE = REPO / "baseline" / "sentiment_baseline.json"


def _fake_counter(text: str) -> int:
    return len(text.split())


def _emotion_baselines():
    return sorted(load_baseline(EMOTION_BASELINE), key=lambda b: b.baseline_id)


def _sentiment_baselines():
    return sorted(load_baseline(SENTIMENT_BASELINE), key=lambda b: b.baseline_id)


def _build(baselines, task_id):
    """Build one core suite in an isolated scope; return (ids, manifest-snapshot)."""
    with md.scoped_registry():
        cases = library.build_suite(
            baselines, token_counter=_fake_counter, max_tokens=64,
            suite=SUITE_CORE, task_id=task_id,
        )
        manifest = {aid: (m.subfamily, m.suite_id, m.coverage_class)
                    for aid, m in md.manifest().items()}
    return [c.attack_id for c in cases], manifest


# --------------------------------------------------------------------- signature guards

def test_legacy_call_still_works_and_defaults_to_emotion_core():
    """The pre-Stage-3 call (no suite/task_id) must still build the emotion core suite."""
    with md.scoped_registry():
        cases = library.build_suite(
            _emotion_baselines(), token_counter=_fake_counter, max_tokens=64
        )
        suites = {m.suite_id for m in md.manifest().values()}
    assert cases
    assert suites == {SUITE_CORE}


def test_unknown_suite_and_task_fail_loud():
    with md.scoped_registry():
        with pytest.raises(ContractError):
            library.build_suite(_emotion_baselines(), suite="not-a-suite")
    with md.scoped_registry():
        with pytest.raises(ContractError):
            library.build_suite(_emotion_baselines(), task_id="not-a-task")


def test_oces_suite_is_not_generated_in_code():
    """OCES is authored as frozen data (Phase 4); build_suite must refuse to synthesise it."""
    with md.scoped_registry():
        with pytest.raises(ContractError):
            library.build_suite(
                _emotion_baselines(), task_id="emotion_7", suite=SUITE_OCES
            )


# ------------------------------------------------------------------ cross-task isolation

def test_emotion_sentiment_emotion_cycle_no_contamination():
    emo, sent = _emotion_baselines(), _sentiment_baselines()

    emo_ids_1, emo_man_1 = _build(emo, "emotion_7")
    sent_ids, sent_man = _build(sent, "sentiment_2")
    emo_ids_2, emo_man_2 = _build(emo, "emotion_7")

    # 1) the second emotion build reproduces the first EXACTLY (ids and manifest state)
    assert emo_ids_2 == emo_ids_1
    assert emo_man_2 == emo_man_1

    # 2) neither suite's ids appear in the other's manifest (no cross-task leak)
    emo_baseline_prefixes = {b.baseline_id for b in emo}
    sent_baseline_prefixes = {b.baseline_id for b in sent}
    sent_prefixes = {aid.split(".")[0] for aid in sent_man if "." in aid}
    emo_prefixes = {aid.split(".")[0] for aid in emo_man_1 if "." in aid}
    assert sent_prefixes & emo_baseline_prefixes == set()
    assert emo_prefixes & sent_baseline_prefixes == set()

    # 3) every case in each manifest is stamped for the core suite (no stale/blank suite)
    assert {s for _, s, _ in emo_man_1.values()} == {SUITE_CORE}
    assert {s for _, s, _ in sent_man.values()} == {SUITE_CORE}
    # 4) coverage was stamped for both (no None leaking through)
    assert all(cov is not None for _, _, cov in sent_man.values())
    assert all(cov is not None for _, _, cov in emo_man_1.values())


def test_same_id_and_payload_under_different_suite_is_rejected():
    """suite_id is part of a case's identity: the same attack_id/payload must not be
    accepted once as core and once as oces. Guards the cross-suite identity weakness."""
    from contract import AttackCase
    md.reset()
    case = AttackCase("dup.suite", None, "encoding", None, "same payload")
    core_meta = md.AttackMetadata(
        "dup.suite", "encoding", "sf", md.REL_AVAILABILITY, md.ORACLE_STAY_AVAILABLE,
        "s", md.TIER_GOLD, suite_id=SUITE_CORE,
    )
    oces_meta = md.AttackMetadata(
        "dup.suite", "encoding", "sf", md.REL_AVAILABILITY, md.ORACLE_STAY_AVAILABLE,
        "s", md.TIER_GOLD, suite_id=SUITE_OCES,
    )
    md.register(case, core_meta)
    with pytest.raises(ValueError):
        md.register(case, oces_meta)            # identical payload, different suite -> rejected
    md.reset()


def test_write_manifest_in_scope_contains_only_that_task(tmp_path):
    """Task 4: build AND write the manifest inside one scope; the written file describes
    only that isolated build, with suite + coverage metadata, and no cross-task leakage."""
    md.reset()
    emo, sent = _emotion_baselines(), _sentiment_baselines()
    emo_path = tmp_path / "emotion_manifest.json"
    sent_path = tmp_path / "sentiment_manifest.json"

    with md.scoped_registry():
        library.build_suite(emo, token_counter=_fake_counter, max_tokens=64,
                            suite=SUITE_CORE, task_id="emotion_7")
        library.write_manifest(str(emo_path))       # written from the SAME isolated scope
    with md.scoped_registry():
        library.build_suite(sent, token_counter=_fake_counter, max_tokens=64,
                            suite=SUITE_CORE, task_id="sentiment_2")
        library.write_manifest(str(sent_path))

    emo_man = json.loads(emo_path.read_text(encoding="utf-8"))
    sent_man = json.loads(sent_path.read_text(encoding="utf-8"))

    # each written manifest carries the suite id and a resolved coverage class for every case
    assert emo_man and sent_man
    assert all(m["suite_id"] == SUITE_CORE for m in emo_man.values())
    assert all(m["coverage_class"] is not None for m in emo_man.values())
    assert all(m["suite_id"] == SUITE_CORE for m in sent_man.values())
    assert all(m["coverage_class"] is not None for m in sent_man.values())

    # neither written file contains the other task's derived ids
    emo_prefixes = {b.baseline_id for b in emo}
    sent_prefixes = {b.baseline_id for b in sent}
    assert {a.split(".")[0] for a in sent_man if "." in a} & emo_prefixes == set()
    assert {a.split(".")[0] for a in emo_man if "." in a} & sent_prefixes == set()

    assert md.manifest() == {}                       # registry restored after both scopes
    md.reset()


def test_manifest_is_empty_after_each_scope_exits():
    """No suite state survives the scope: the process manifest returns to its prior state."""
    md.reset()
    assert md.manifest() == {}
    _build(_sentiment_baselines(), "sentiment_2")
    assert md.manifest() == {}          # sentiment build left nothing behind
    _build(_emotion_baselines(), "emotion_7")
    assert md.manifest() == {}
    md.reset()


# ------------------------------------------------------------ scoped_registry semantics

def test_scope_clears_on_entry_and_restores_both_dicts_exactly():
    md.reset()
    c1 = md.AttackMetadata("outer", "encoding", "sf", md.REL_AVAILABILITY,
                           md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD)
    from contract import AttackCase
    md.register(AttackCase("outer", None, "encoding", None, "one"), c1)
    outer_manifest = md.manifest()
    outer_fps = dict(md._FINGERPRINTS)

    with md.scoped_registry():
        assert md.manifest() == {}                      # cleared on entry
        assert md._FINGERPRINTS == {}
        md.register(AttackCase("inner", None, "encoding", None, "two"),
                    md.AttackMetadata("inner", "encoding", "sf", md.REL_AVAILABILITY,
                                      md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD))

    assert md.manifest() == outer_manifest              # restored exactly
    assert md._FINGERPRINTS == outer_fps
    md.reset()


def test_nested_scope_and_exception_exit_both_restore():
    from contract import AttackCase
    md.reset()
    md.register(AttackCase("s1", None, "encoding", None, "one"),
                md.AttackMetadata("s1", "encoding", "sf", md.REL_AVAILABILITY,
                                  md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD))
    outer_manifest, outer_fps = md.manifest(), dict(md._FINGERPRINTS)

    with md.scoped_registry():
        md.register(AttackCase("s2", None, "encoding", None, "two"),
                    md.AttackMetadata("s2", "encoding", "sf", md.REL_AVAILABILITY,
                                      md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD))
        mid_manifest, mid_fps = md.manifest(), dict(md._FINGERPRINTS)

        with pytest.raises(RuntimeError):
            with md.scoped_registry():
                assert md.manifest() == {}
                md.register(AttackCase("s3", None, "encoding", None, "three"),
                            md.AttackMetadata("s3", "encoding", "sf", md.REL_AVAILABILITY,
                                              md.ORACLE_STAY_AVAILABLE, "s", md.TIER_GOLD))
                raise RuntimeError("boom inside nested scope")
        assert md.manifest() == mid_manifest            # nested exception still restored
        assert md._FINGERPRINTS == mid_fps

    assert md.manifest() == outer_manifest              # outer restored exactly
    assert md._FINGERPRINTS == outer_fps
    md.reset()


def test_build_failure_inside_scope_leaves_no_state():
    """If a build raises mid-scope, the outer process state is untouched."""
    md.reset()
    with pytest.raises(ContractError):
        with md.scoped_registry():
            # build a partial suite, then trigger a loud failure
            library.build_suite(_emotion_baselines(), token_counter=_fake_counter,
                                max_tokens=64, suite="bogus")
    assert md.manifest() == {}
    md.reset()


# --------------------------------------------------- task-dependent counts (deterministic)

def test_tasks_produce_different_but_deterministic_counts():
    emo, sent = _emotion_baselines(), _sentiment_baselines()

    def count(baselines, task):
        with md.scoped_registry():
            return len(library.build_suite(
                baselines, token_counter=_fake_counter, max_tokens=64,
                suite=SUITE_CORE, task_id=task,
            ))

    emo_n1 = count(emo, "emotion_7")
    emo_n2 = count(emo, "emotion_7")
    sent_n1 = count(sent, "sentiment_2")
    sent_n2 = count(sent, "sentiment_2")

    assert emo_n1 == emo_n2                  # emotion deterministic
    assert sent_n1 == sent_n2                # sentiment deterministic
    assert emo_n1 != sent_n1                 # legitimately different, content-driven
    assert emo_n1 == 1886                    # preserved original emotion count


def test_sentiment_count_reproduces_with_real_pinned_tokenizer():
    """Uses the REAL pinned sentiment tokenizer (no weights, no inference).

    Only genuine unavailability of the tokenizer asset (offline / no cache) may skip -- that
    is the guarded probe. Once it loads, the suite build runs UNGUARDED, so a real generation
    regression fails the test rather than being masked as an offline skip.
    """
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(
            "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
            revision="714eb0fa89d2f80546fda750413ed43d93601a13",
        )
    except Exception as exc:                 # noqa: BLE001 - tokenizer asset genuinely unavailable
        pytest.skip(f"pinned sentiment tokenizer unavailable offline: {exc}")

    def count(text):
        return len(tok.encode(text, add_special_tokens=True, truncation=False))

    def build_n():
        with md.scoped_registry():
            return len(library.build_suite(
                _sentiment_baselines(), token_counter=count, max_tokens=512,
                suite=SUITE_CORE, task_id="sentiment_2",
            ))

    n1 = build_n()
    n2 = build_n()
    assert n1 == n2 == 1889                  # recorded actual sentiment core count
