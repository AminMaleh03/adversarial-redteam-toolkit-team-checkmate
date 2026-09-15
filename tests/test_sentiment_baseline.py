"""
Tests for the SST-2 sentiment core baseline (owner: Lamei, Task 4).

Two groups, failing for different reasons:

1. The committed artifacts -- baseline/sentiment_baseline.json and
   baseline/sentiment_provenance.json. They are committed so every teammate's run is
   comparable, so their shape, label balance, id convention, verbatim text and provenance
   are pinned here. A failure means the sentiment baseline changed: a bug, or a deliberate
   new version the whole team must know about.

2. The builder invariants -- from build_sentiment_baseline (constants, selection rule),
   without downloading the dataset. One network-guarded test rebuilds from the pinned
   revision and asserts it reproduces the committed file byte-for-byte; it skips cleanly
   offline. No model or tokenizer is loaded anywhere here; selection is model-free.
"""

import hashlib
import json
from pathlib import Path

import pytest

from contract import BaselineCase
from baseline.load import load_baseline
from baseline import build_sentiment_baseline as bsb

REPO = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO / "baseline" / "sentiment_baseline.json"
PROVENANCE_PATH = REPO / "baseline" / "sentiment_provenance.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- committed artifact
def test_baseline_loads_as_baselinecases():
    cases = load_baseline(BASELINE_PATH)
    assert len(cases) == 42
    assert all(isinstance(c, BaselineCase) for c in cases)


def test_exactly_21_negative_and_21_positive_uppercase():
    cases = load_baseline(BASELINE_PATH)
    labels = [c.label for c in cases]
    assert labels.count("NEGATIVE") == 21
    assert labels.count("POSITIVE") == 21
    # labels are the model's exact casing; nothing lowercased or emotion-mapped
    assert set(labels) == {"NEGATIVE", "POSITIVE"}


def test_ids_encode_exact_sst2_row_and_are_unique():
    cases = load_baseline(BASELINE_PATH)
    ids = [c.baseline_id for c in cases]
    assert len(set(ids)) == 42
    for c in cases:
        assert c.baseline_id.startswith("sst2-val-")
        assert c.baseline_id.split("-")[-1].isdigit()
    assert all(c.source == "dataset" for c in cases)


def test_deterministic_file_order():
    """NEGATIVE group then POSITIVE group, each ascending by dataset idx."""
    cases = load_baseline(BASELINE_PATH)
    neg = [c for c in cases if c.label == "NEGATIVE"]
    pos = [c for c in cases if c.label == "POSITIVE"]
    assert cases == neg + pos                      # groups are contiguous, negatives first
    neg_idx = [int(c.baseline_id.split("-")[-1]) for c in neg]
    pos_idx = [int(c.baseline_id.split("-")[-1]) for c in pos]
    assert neg_idx == sorted(neg_idx)
    assert pos_idx == sorted(pos_idx)


def test_text_is_nonempty_and_kept_verbatim():
    """SST artefacts (spaced punctuation / trailing space) are preserved, not cleaned."""
    cases = load_baseline(BASELINE_PATH)
    assert all(c.text.strip() for c in cases)
    # at least one row keeps a trailing space or spaced punctuation (proves no cleaning)
    assert any(c.text != c.text.strip() or " ." in c.text or " 's" in c.text for c in cases)


# ----------------------------------------------------------------- provenance
def test_provenance_pins_dataset_and_is_model_free():
    prov = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    ds = prov["dataset"]
    assert ds["repo_id"] == "stanfordnlp/sst2"
    assert ds["revision"] == "8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb"
    assert ds["split"] == "validation"
    assert len(ds["split_file_sha256"]) == 64
    assert prov["selection"]["model_free"] is True
    assert prov["selection"]["seed"] == bsb.SEED
    assert prov["selection"]["per_label"] == 21
    # honest holdout wording
    assert "not a proven-unseen holdout" in ds["holdout_claim"]
    # the model it is FOR is recorded but explicitly not used
    assert "NOT loaded" in prov["sentiment_model_the_baseline_is_for"]["note"]


def test_provenance_source_mapping_matches_baseline_rows():
    cases = load_baseline(BASELINE_PATH)
    prov = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    mapping = prov["source_mapping"]
    assert set(mapping) == {c.baseline_id for c in cases}
    for c in cases:
        entry = mapping[c.baseline_id]
        assert entry["label"] == c.label
        assert entry["dataset_label_int"] == (0 if c.label == "NEGATIVE" else 1)
        assert entry["dataset_idx"] == int(c.baseline_id.split("-")[-1])
        # sentence hash pins the exact verbatim text
        assert entry["sentence_sha256"] == hashlib.sha256(c.text.encode("utf-8")).hexdigest()


def test_provenance_records_exclusions_and_replacement_rule():
    prov = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert "exclusions" in prov and "count" in prov["exclusions"]
    assert isinstance(prov["exclusions"]["rows"], list)
    rule = prov["selection"]["replacement_rule"]
    assert "no row is ever chosen" in rule.lower()
    assert "model output" in rule.lower()


# ----------------------------------------------------------------- builder invariants
def test_builder_constants_are_frozen():
    assert bsb.PER_LABEL == 21
    assert bsb.DATASET_REVISION == "8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb"
    assert bsb.DATASET_SPLIT == "validation"
    assert bsb.LABEL_INT_TO_MODEL == {0: "NEGATIVE", 1: "POSITIVE"}


def test_rebuild_reproduces_committed_files(tmp_path):
    """Rebuild from the pinned revision and diff against the committed files.

    Only genuine unavailability of the external dataset (offline / no cache) may skip: we
    probe that first. Once the dataset is reachable, build() runs UNGUARDED, so a real
    builder or validation regression (wrong row count, wrong labels, selection/provenance
    mismatch, ...) fails the test instead of being masked as an "offline" skip.
    """
    try:
        from datasets import load_dataset
        load_dataset(bsb.DATASET_NAME, revision=bsb.DATASET_REVISION, split=bsb.DATASET_SPLIT)
    except Exception as exc:                        # noqa: BLE001 - dataset genuinely unavailable
        pytest.skip(f"pinned SST-2 dataset unavailable offline: {exc}")

    cases, excluded, provenance = bsb.build()       # unguarded: any failure here is a real bug

    # Re-serialise exactly as main() writes the files, and assert byte-for-byte parity with
    # the committed artifacts (this also normalises int-vs-string JSON key coercion).
    rebuilt_baseline = (
        json.dumps([bsb._to_record(c) for c in cases], ensure_ascii=False, indent=2) + "\n"
    )
    rebuilt_provenance = json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    assert rebuilt_baseline == BASELINE_PATH.read_text(encoding="utf-8")
    assert rebuilt_provenance == PROVENANCE_PATH.read_text(encoding="utf-8")
