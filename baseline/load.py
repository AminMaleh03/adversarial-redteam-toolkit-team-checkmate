"""Reads baseline.json back into BaselineCase objects for the rest of the pipeline.

The counterpart to build_baseline.py's `_to_record`: that one writes the JSON,
this one reads it. Kept here rather than in the runner so exactly one place
knows how a BaselineCase maps to a JSON record. A field change in contract.py
then breaks loudly, in this file, instead of silently half-populating cases
somewhere downstream.

Deliberately does NOT import `datasets` or rebuild anything. Loading the
committed baseline has to stay cheap and offline -- the whole point of
committing baseline.json is that nobody re-samples it.

    from baseline.load import load_baseline
    cases = load_baseline()
"""

import json
from collections import Counter
from pathlib import Path

from contract import BaselineCase

# Same file build_baseline.py writes to.
BASELINE_PATH = Path(__file__).parent / "baseline.json"


def load_baseline(path: Path | str | None = None) -> list[BaselineCase]:
    """
    Return every committed baseline sentence, in file order.

    Raises rather than repairing. A record that no longer matches
    BaselineCase, or a duplicate baseline_id, means the baseline is broken,
    and every run built on top of it would be quietly wrong.
    """
    path = BASELINE_PATH if path is None else Path(path)

    with path.open(encoding="utf-8") as f:
        records = json.load(f)

    cases = []
    for i, record in enumerate(records):
        # Unpacked wholesale, not field by field, so a missing, renamed or
        # unexpected field surfaces here as a TypeError instead of producing
        # a case that looks fine until analysis reads it.
        try:
            cases.append(BaselineCase(**record))
        except TypeError as exc:
            raise ValueError(
                f"{path.name} record {i} does not match BaselineCase: {exc}"
            ) from exc

    # Attacks derive ids as f"{baseline_id}.{category}.{subfamily}", so a
    # duplicate baseline_id would collide attack ids and overwrite results.
    duplicates = sorted(
        bid for bid, n in Counter(c.baseline_id for c in cases).items() if n > 1
    )
    if duplicates:
        raise ValueError(f"{path.name} has duplicate baseline_id values: {duplicates}")

    return cases
