"""Builds the reproducible SST-2 sentiment core baseline (Task 4, second task).

This is the sentiment counterpart of build_baseline.py. It selects 42 SST-2 *validation*
sentences -- 21 NEGATIVE and 21 POSITIVE -- from the pinned dataset revision, using a fixed
seed and a deterministic, MODEL-FREE selection rule, and writes:

  * baseline/sentiment_baseline.json    -- BaselineCase records (same schema as baseline.json)
  * baseline/sentiment_provenance.json  -- everything that does NOT belong in BaselineCase:
                                           dataset identity, seed, algorithm, exclusions,
                                           deterministic replacement rule and a per-row
                                           source mapping (baseline_id -> idx / label / hash)

Two rules the foundation fixed and this file obeys (docs/stage3/MODEL_IDENTITY.md):

  1. Selection never looks at model outputs. We pick by the dataset-recorded label and by
     mechanical criteria (label balance, non-empty text, de-duplication) only. Picking the
     sentences the model gets right, or is confident on, would manufacture the very baseline
     confidence the flip oracle later depends on. NO model or tokenizer is loaded here.
  2. The validation split is NOT a proven-unseen holdout. It is a pinned, public benchmark
     split the checkpoint's authors could have used for model selection. Nothing here (or in
     the report) may claim otherwise.

Text is kept VERBATIM, including SST tokenisation artefacts (spaced punctuation, trailing
spaces), because whitespace handling is itself one of the attack families -- silently
cleaning the input would neutralise a category. The label is stored in the model's exact
casing: 0 -> "NEGATIVE", 1 -> "POSITIVE". Nothing may lowercase it or map it onto emotion
labels.

Run from the repo root:  python -m baseline.build_sentiment_baseline
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from datasets import load_dataset

from contract import BaselineCase


# --- frozen knobs ---------------------------------------------------------------------
# Fixed so two runs, and two people, reproduce byte-identical data. Do not change after
# sentiment_baseline.json is committed; a later change is a NEW version, not an edit.
#
# SEED is AUTHORED and frozen by Task 4 (Lamei), not prescribed by the foundation docs:
# docs/stage3/MODEL_IDENTITY.md requires only a fixed seed + deterministic, model-free
# selection and does not mandate a particular numeric value. This value is that frozen
# choice; the selection's validity does not depend on which fixed seed is used.
SEED = 20260915
PER_LABEL = 21                      # 21 NEGATIVE + 21 POSITIVE = 42
BUILDER_VERSION = "1.0.0"
AUTHORED_UTC = "2026-09-15"

# Pinned dataset identity (docs/stage3/MODEL_IDENTITY.md; matches the frozen provenance).
DATASET_NAME = "stanfordnlp/sst2"
DATASET_REVISION = "8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb"
DATASET_SPLIT = "validation"
DATASET_SPLIT_FILE = "data/validation-00000-of-00001.parquet"
DATASET_SPLIT_FILE_SHA256 = (
    "fb00fe008f6828f86ba2beda8415a4cf5da0c884f21c5f238c87131b5aa19529"
)
EXPECTED_ROWS = 872
# label id -> (dataset name, model label casing). The model's id2label is UPPERCASE.
LABEL_INT_TO_MODEL = {0: "NEGATIVE", 1: "POSITIVE"}
EXPECTED_LABEL_DIST = {0: 428, 1: 444}

# The sentiment model these baselines are FOR. Recorded for provenance only; NOT loaded,
# NOT used in selection. Selection is independent of any model.
SENTIMENT_MODEL_ID = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
SENTIMENT_MODEL_REVISION = "714eb0fa89d2f80546fda750413ed43d93601a13"

BASELINE_PATH = Path(__file__).parent / "sentiment_baseline.json"
PROVENANCE_PATH = Path(__file__).parent / "sentiment_provenance.json"

# The deterministic replacement rule, stated once and recorded verbatim in provenance.
REPLACEMENT_RULE = (
    "Exclusions (empty text, duplicate sentence) are computed over the whole split BEFORE "
    "selection and removed from the eligible pool. For each label, selection then walks a "
    "single fixed seeded permutation (random.Random(SEED).sample of the idx-sorted eligible "
    "pool) and takes the first PER_LABEL rows. An excluded row is therefore deterministically "
    "skipped and the next eligible row in the same permutation takes its place. No row is ever "
    "chosen, skipped or replaced on the basis of any model output (correctness, confidence, or "
    "attack success)."
)


@dataclass(frozen=True)
class _Row:
    idx: int
    sentence: str
    label: int


# --- load -----------------------------------------------------------------------------
def _load_rows() -> list[_Row]:
    ds = load_dataset(DATASET_NAME, revision=DATASET_REVISION, split=DATASET_SPLIT)
    if ds.num_rows != EXPECTED_ROWS:
        raise ValueError(
            f"{DATASET_NAME}@{DATASET_REVISION} {DATASET_SPLIT}: expected "
            f"{EXPECTED_ROWS} rows, got {ds.num_rows}"
        )
    rows = [
        _Row(idx=int(r["idx"]), sentence=r["sentence"], label=int(r["label"]))
        for r in ds
    ]
    dist = Counter(r.label for r in rows)
    if dist != Counter(EXPECTED_LABEL_DIST):
        raise ValueError(
            f"{DATASET_NAME}@{DATASET_REVISION}: label distribution {dict(dist)} does not "
            f"match the pinned {EXPECTED_LABEL_DIST}"
        )
    return rows


# --- mechanical validity + de-duplication (no model, no tokenizer) --------------------
def _partition(rows: list[_Row]) -> tuple[list[_Row], list[dict]]:
    """Split rows into (eligible, excluded). Excluded carries a reason for each drop.

    Only mechanical, model-free checks: a row is excluded if its sentence is empty after
    stripping, or if the exact sentence text has already appeared at a lower idx (keep the
    first occurrence, drop later identical ones).
    """
    eligible: list[_Row] = []
    excluded: list[dict] = []
    seen_text_to_idx: dict[str, int] = {}
    for row in sorted(rows, key=lambda r: r.idx):
        if not row.sentence.strip():
            excluded.append({"idx": row.idx, "label": row.label, "reason": "empty_text"})
            continue
        first = seen_text_to_idx.get(row.sentence)
        if first is not None:
            excluded.append({
                "idx": row.idx, "label": row.label,
                "reason": "duplicate_sentence", "duplicate_of_idx": first,
            })
            continue
        seen_text_to_idx[row.sentence] = row.idx
        eligible.append(row)
    return eligible, excluded


# --- deterministic, model-free selection ----------------------------------------------
def _select(eligible: list[_Row]) -> list[_Row]:
    rng = random.Random(SEED)
    selected: list[_Row] = []
    for label_int in (0, 1):                      # NEGATIVE then POSITIVE
        pool = sorted([r for r in eligible if r.label == label_int], key=lambda r: r.idx)
        if len(pool) < PER_LABEL:
            raise ValueError(
                f"only {len(pool)} eligible rows for label {label_int}, need {PER_LABEL}"
            )
        order = rng.sample(pool, len(pool))       # one fixed seeded permutation
        chosen: list[_Row] = []
        chosen_idx: set[int] = set()
        for row in order:                         # realises the replacement rule: skip-and-take-next
            if len(chosen) == PER_LABEL:
                break
            if row.idx in chosen_idx:
                continue
            chosen.append(row)
            chosen_idx.add(row.idx)
        selected.extend(sorted(chosen, key=lambda r: r.idx))
    return selected


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- build ----------------------------------------------------------------------------
def build() -> tuple[list[BaselineCase], list[dict], dict]:
    """Return (baseline_cases, excluded, provenance). No files are written."""
    rows = _load_rows()
    eligible, excluded = _partition(rows)
    selected = _select(eligible)

    cases: list[BaselineCase] = []
    source_mapping: dict[str, dict] = {}
    for row in selected:
        model_label = LABEL_INT_TO_MODEL[row.label]
        baseline_id = f"sst2-val-{row.idx}"
        cases.append(BaselineCase(
            baseline_id=baseline_id,
            text=row.sentence,                    # VERBATIM, artefacts preserved
            label=model_label,                    # "NEGATIVE" | "POSITIVE"
            source="dataset",
        ))
        source_mapping[baseline_id] = {
            "dataset_idx": row.idx,
            "dataset_label_int": row.label,
            "label": model_label,
            "sentence_sha256": _sha256(row.sentence),
        }

    by_label = Counter(c.label for c in cases)
    provenance = {
        "artifact": "sentiment_baseline",
        "builder_version": BUILDER_VERSION,
        "authored_utc": AUTHORED_UTC,
        "generator": "baseline/build_sentiment_baseline.py",
        "selection": {
            "seed": SEED,
            "per_label": PER_LABEL,
            "total_selected": len(cases),
            "label_balance": dict(sorted(by_label.items())),
            "order": "NEGATIVE group then POSITIVE group, each ascending by dataset idx",
            "algorithm": (
                "mechanical validity + de-dup over the whole split, then one fixed seeded "
                "permutation per label, take first PER_LABEL. Model-free and deterministic."
            ),
            "model_free": True,
            "replacement_rule": REPLACEMENT_RULE,
        },
        "dataset": {
            "repo_id": DATASET_NAME,
            "revision": DATASET_REVISION,
            "split": DATASET_SPLIT,
            "split_file": DATASET_SPLIT_FILE,
            "split_file_sha256": DATASET_SPLIT_FILE_SHA256,
            "rows": EXPECTED_ROWS,
            "schema": {"idx": "int32", "sentence": "string", "label": "int64"},
            "label_distribution": EXPECTED_LABEL_DIST,
            "label_meaning": {"0": "NEGATIVE", "1": "POSITIVE"},
            "text_policy": "verbatim; SST tokenisation artefacts (spaced punctuation, "
                           "trailing spaces) intentionally preserved",
            "holdout_claim": "none; SST-2 validation is a public benchmark split, not a "
                             "proven-unseen holdout",
        },
        "sentiment_model_the_baseline_is_for": {
            "model_id": SENTIMENT_MODEL_ID,
            "revision": SENTIMENT_MODEL_REVISION,
            "note": "recorded for provenance only; NOT loaded and NOT used in selection",
        },
        "exclusions": {
            "count": len(excluded),
            "rows": excluded,
        },
        "source_mapping": source_mapping,
    }
    return cases, excluded, provenance


def _to_record(case: BaselineCase) -> dict:
    return {
        "baseline_id": case.baseline_id,
        "text": case.text,
        "label": case.label,
        "source": case.source,
    }


def main() -> None:
    cases, excluded, provenance = build()

    with BASELINE_PATH.open("w", encoding="utf-8") as handle:
        json.dump([_to_record(c) for c in cases], handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with PROVENANCE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(provenance, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    by_label = Counter(c.label for c in cases)
    print(f"Wrote {len(cases)} sentiment baselines to {BASELINE_PATH}")
    print("  per label :", dict(sorted(by_label.items())))
    print("  exclusions:", len(excluded))
    print(f"  baseline sha256  : {_sha256(BASELINE_PATH.read_text(encoding='utf-8'))}")
    print(f"  provenance sha256: {_sha256(PROVENANCE_PATH.read_text(encoding='utf-8'))}")


if __name__ == "__main__":
    main()
