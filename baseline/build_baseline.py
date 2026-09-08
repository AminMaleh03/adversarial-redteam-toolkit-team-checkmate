"""Assembles all baseline sources into BaselineCase objects and writes baseline/baseline.json.

This is the clean baseline that every attack is measured against.

The model predicts seven labels: anger, disgust, fear, joy, neutral,
sadness, surprise. Five overlap with dair-ai/emotion and are SAMPLED
from it (anger, fear, joy, sadness, surprise). The other two, neutral
and disgust, are not in that dataset, so they are HAND WRITTEN (see
neutral.py / disgust.py) and marked source="handwritten".

The dataset's `love` label is deliberately EXCLUDED. It is dropped
because the model has no `love` label to predict at all -- a property
of the model's label set, not of how the model scores any particular
sentence. So excluding it cannot be cherry-picking: no sentence is kept
or dropped based on how it performs. (Ahsan: safe to lift into the
report.)

We do NOT load the model here and do NOT filter by confidence. Sampling
is blind to how the model scores anything, on purpose -- that is the
whole point of using a public dataset. The 0.6 threshold in the
analysis handles weak predictions later, defensibly.

Run from the repo root:  python -m baseline.build_baseline
"""

import json
import random
from collections import Counter
from pathlib import Path

from datasets import load_dataset

from contract import BaselineCase
from baseline.neutral import NEUTRAL_SENTENCES
from baseline.disgust import DISGUST_SENTENCES


# --- frozen knobs -----------------------------------------------------
# Fixed so two runs, and two people, get identical sentences.
# Reproducibility is graded. Do not change after baseline.json is committed.
SEED = 20250908
SENTENCES_PER_LABEL = 6          # 6 x 5 dataset labels = 30, + 6 neutral + 6 disgust = 42
DATASET_NAME = "dair-ai/emotion"
DATASET_CONFIG = "split"
DATASET_SPLIT = "train"

# The five labels the model and the dataset share.
OVERLAPPING_LABELS = ["anger", "fear", "joy", "sadness", "surprise"]

OUTPUT_PATH = Path(__file__).parent / "baseline.json"


# --- the two places coupled to contract.py's BaselineCase -------------
def _make_case(baseline_id, text, label, source):
    return BaselineCase(baseline_id=baseline_id, text=text, label=label, source=source)


def _to_record(case):
    return {
        "baseline_id": case.baseline_id,
        "text": case.text,
        "label": case.label,
        "source": case.source,
    }


# --- sampling ---------------------------------------------------------
def _dataset_cases(rng):
    ds = load_dataset(DATASET_NAME, DATASET_CONFIG, split=DATASET_SPLIT)

    # Map label name <-> integer id using the dataset's own ClassLabel,
    # so we don't hard-code an ordering that could drift between versions.
    label_feature = ds.features["label"]
    wanted_id_to_name = {
        label_feature.str2int(name): name for name in OVERLAPPING_LABELS
    }

    # One pass to bucket row indices by label. Ordering is deterministic
    # for a given dataset version, and the fixed seed makes the pick stable.
    buckets = {name: [] for name in OVERLAPPING_LABELS}
    for idx, label_id in enumerate(ds["label"]):
        name = wanted_id_to_name.get(label_id)
        if name is not None:
            buckets[name].append(idx)

    cases = []
    for name in OVERLAPPING_LABELS:
        indices = buckets[name]
        if len(indices) < SENTENCES_PER_LABEL:
            raise ValueError(
                f"Only {len(indices)} '{name}' rows available, "
                f"need {SENTENCES_PER_LABEL}."
            )
        chosen = sorted(rng.sample(indices, SENTENCES_PER_LABEL))
        for i, row_idx in enumerate(chosen):
            cases.append(
                _make_case(
                    baseline_id=f"dataset-{name}-{i}",
                    text=ds[row_idx]["text"],
                    label=name,           # dataset label = CONTEXT only, never
                                          # what drift is measured against
                    source="dataset",
                )
            )
    return cases


def _handwritten_cases():
    cases = []
    for i, text in enumerate(NEUTRAL_SENTENCES):
        cases.append(_make_case(f"handwritten-neutral-{i}", text, "neutral", "handwritten"))
    for i, text in enumerate(DISGUST_SENTENCES):
        cases.append(_make_case(f"handwritten-disgust-{i}", text, "disgust", "handwritten"))
    return cases


def build():
    rng = random.Random(SEED)
    return _dataset_cases(rng) + _handwritten_cases()


def main():
    cases = build()

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump([_to_record(c) for c in cases], f, ensure_ascii=False, indent=2)

    by_label = Counter(c.label for c in cases)
    by_source = Counter(c.source for c in cases)
    print(f"Wrote {len(cases)} cases to {OUTPUT_PATH}")
    print("  per label :", dict(sorted(by_label.items())))
    print("  per source:", dict(by_source))


if __name__ == "__main__":
    main()
