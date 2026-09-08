"""
Tests for the baseline component (owner: Khalid).

Two things are covered, and they fail for different reasons:

1. baseline/load.py -- the loader contract. It must return real BaselineCase
   objects, round-trip the committed file exactly, and REFUSE broken data
   rather than pass a half-populated case downstream.

2. baseline/baseline.json -- the committed artifact itself. It is checked into
   git precisely so every teammate's run is comparable, so its shape, label
   coverage and id conventions are pinned here. A failure in this group means
   the baseline changed; that is either a bug or a deliberate change that the
   whole team needs to know about, because it invalidates comparisons against
   any run made before it.

Deliberately does NOT call build_baseline.build(): that downloads dair-ai/emotion
and needs a network. The committed JSON is the thing every run actually uses, so
the committed JSON is what these tests check.

Run from the repo root (venv active):
    python -m pytest tests/test_baseline.py -v
"""

import json
from dataclasses import fields

import pytest

from contract import BaselineCase
from baseline.load import BASELINE_PATH, load_baseline
from baseline.build_baseline import (
    OVERLAPPING_LABELS,
    SENTENCES_PER_LABEL,
    _to_record,
)
from baseline.neutral import NEUTRAL_SENTENCES
from baseline.disgust import DISGUST_SENTENCES


# The seven labels j-hartmann/emotion-english-distilroberta-base predicts.
MODEL_LABELS = {"anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"}

# The two labels dair-ai/emotion has no equivalent for, hence hand-written.
HANDWRITTEN_LABELS = {"neutral", "disgust"}

VALID_RECORD = {
    "baseline_id": "handwritten-joy-0",
    "text": "I am extremely happy today",
    "label": "joy",
    "source": "handwritten",
}


@pytest.fixture(scope="module")
def cases():
    return load_baseline()


@pytest.fixture(scope="module")
def raw_records():
    with BASELINE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _write(tmp_path, records):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


# --- the loader contract ---------------------------------------------
def test_loads_baselinecase_objects(cases):
    assert cases
    assert all(isinstance(case, BaselineCase) for case in cases)


def test_default_path_is_the_committed_file():
    assert BASELINE_PATH.exists()
    assert BASELINE_PATH.name == "baseline.json"


def test_round_trips_the_file_exactly(cases, raw_records):
    # Order matters: attack ids are derived per baseline, so a reordered
    # load would silently reshuffle which attack belongs to which sentence.
    assert [c.baseline_id for c in cases] == [r["baseline_id"] for r in raw_records]
    assert [c.text for c in cases] == [r["text"] for r in raw_records]
    assert [c.label for c in cases] == [r["label"] for r in raw_records]
    assert [c.source for c in cases] == [r["source"] for r in raw_records]


def test_accepts_str_and_path(cases):
    assert load_baseline(str(BASELINE_PATH)) == cases
    assert load_baseline(BASELINE_PATH) == cases


def test_to_record_and_load_are_inverses(tmp_path, cases):
    # _to_record writes the JSON, load_baseline reads it. If these two ever
    # disagree about the field mapping the baseline silently corrupts, so
    # pin the round trip rather than trusting they stay in sync.
    path = _write(tmp_path, [_to_record(c) for c in cases])
    assert load_baseline(path) == cases


# --- the loader refuses broken data ----------------------------------
def test_rejects_unexpected_field(tmp_path):
    path = _write(tmp_path, [VALID_RECORD | {"confidence": 0.9}])
    with pytest.raises(ValueError, match="does not match BaselineCase"):
        load_baseline(path)


def test_rejects_missing_field(tmp_path):
    incomplete = {k: v for k, v in VALID_RECORD.items() if k != "source"}
    path = _write(tmp_path, [incomplete])
    with pytest.raises(ValueError, match="does not match BaselineCase"):
        load_baseline(path)


def test_error_names_the_offending_record(tmp_path):
    path = _write(tmp_path, [VALID_RECORD, VALID_RECORD | {"bogus": 1}])
    with pytest.raises(ValueError, match="record 1"):
        load_baseline(path)


def test_rejects_duplicate_baseline_id(tmp_path):
    # Attacks build ids as f"{baseline_id}.{category}.{subfamily}", so a
    # duplicate here would collide attack ids and overwrite results.
    path = _write(tmp_path, [VALID_RECORD, dict(VALID_RECORD, text="different")])
    with pytest.raises(ValueError, match="duplicate baseline_id"):
        load_baseline(path)


def test_empty_file_loads_as_empty_list(tmp_path):
    assert load_baseline(_write(tmp_path, [])) == []


# --- the committed artifact ------------------------------------------
def test_records_match_contract_fields_exactly(raw_records):
    expected = {f.name for f in fields(BaselineCase)}
    for record in raw_records:
        assert set(record.keys()) == expected


def test_expected_size_and_shape(cases):
    # Pinned on purpose. baseline.json is committed so every teammate runs the
    # same sentences; if this fails the baseline was changed and every earlier
    # run is no longer comparable. Update the numbers only alongside that call.
    expected = SENTENCES_PER_LABEL * len(MODEL_LABELS)
    assert len(cases) == expected == 42


def test_every_model_label_is_covered_equally(cases):
    by_label = {}
    for case in cases:
        by_label.setdefault(case.label, []).append(case)
    assert set(by_label) == MODEL_LABELS
    assert all(len(v) == SENTENCES_PER_LABEL for v in by_label.values())


def test_baseline_ids_are_unique(cases):
    ids = [c.baseline_id for c in cases]
    assert len(set(ids)) == len(ids)


def test_sources_are_valid_and_split_as_designed(cases):
    assert {c.source for c in cases} == {"dataset", "handwritten"}
    # dair-ai/emotion has no neutral or disgust label, so exactly those two
    # are hand-written and the five overlapping labels come from the dataset.
    assert {c.label for c in cases if c.source == "handwritten"} == HANDWRITTEN_LABELS
    assert {c.label for c in cases if c.source == "dataset"} == set(OVERLAPPING_LABELS)


def test_ids_follow_the_source_label_convention(cases):
    for case in cases:
        assert case.baseline_id.startswith(f"{case.source}-{case.label}-")


def test_no_case_has_empty_text(cases):
    for case in cases:
        assert isinstance(case.text, str)
        assert case.text.strip()


def test_no_duplicate_sentences(cases):
    texts = [c.text for c in cases]
    assert len(set(texts)) == len(texts)


def test_handwritten_sentences_match_their_source_modules(cases):
    # Guards the easy mistake: editing neutral.py or disgust.py and forgetting
    # to re-run build_baseline, leaving the committed JSON stale.
    by_id = {c.baseline_id: c for c in cases}
    for label, sentences in (("neutral", NEUTRAL_SENTENCES), ("disgust", DISGUST_SENTENCES)):
        assert len(sentences) == SENTENCES_PER_LABEL
        for i, text in enumerate(sentences):
            assert by_id[f"handwritten-{label}-{i}"].text == text
