"""The runner. Fires the suite at one endpoint version and records what came back.

    python -m runner.run --target http://127.0.0.1:8000 --version v1
    python -m runner.run --target http://127.0.0.1:8001 --version v2 --limit 20 --out results/smoke

Five files, names pinned because the analysis reads them:

    <out>/manifest.json             Lamei's pre-registered expectations, written once
    <out>/results_<version>.jsonl   one RunResult per line, appended and flushed
    <out>/run_meta_<version>.json   fingerprints, coverage, run identity

Send order, stable across runs so two runs are comparable:

    1. every clean baseline sentence        (case_type "baseline")
    2. every standalone attack             (baseline_id is None)
    3. per baseline, its derived attacks    (baseline_id set)

The line this module does not cross: it records what happened and computes
operational bookkeeping -- fingerprints, coverage, counts, timestamps -- but it
never decides whether what happened was a defect. No flip detection, no crash
rate, no severity. The analysis reads only what is written here.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import dataclasses
import copy
import hashlib
import inspect
import json
import math
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from attacks import library  # noqa: E402
from attacks.metadata import scoped_registry  # noqa: E402
from baseline.load import load_baseline  # noqa: E402
from contract import (  # noqa: E402
    SUITE_CORE,
    SUITES,
    AttackCase,
    BaselineCase,
    ContractError,
    Registry,
    RunResult,
)
from endpoint import targets as target_registry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OUT = "results"
MANIFEST_NAME = "manifest.json"        # pinned by Ahsan. Lamei's integration
                                       # notes say attack_manifest.json; if the
                                       # analysis reads that name, change it here.
SELECTION_NAME = "case_selection.json"  # snapshot of the frozen selection actually used
REQUEST_TIMEOUT = 10.0
HEALTH_TIMEOUT = 2.0                   # its own short timeout: a hung probe
                                       # must not stall the run behind it
SLOW_FROM_MS = 2_000.0                 # 2s and above is slow
BAND_NORMAL = "normal"
BAND_SLOW = "slow"
BAND_TIMEOUT = "timeout"

# Structured prefixes on RunResult.error, so the analysis can separate the
# failure kinds without guessing from free text.
ERR_CONNECTION = "connection_error"
ERR_TIMEOUT = "timeout"
ERR_TRANSPORT = "transport_error"
# The request body could not be serialised, so no bytes ever existed to send. This is
# an execution failure of ours, not a property of the endpoint, and it is recorded as
# its own kind so the analysis never reads it as "the endpoint accepted an empty body".
ERR_SERIALIZATION = "serialization_error"

TERM_COMPLETED = "completed"
TERM_LIMIT = "stopped_on_limit"
TERM_HEALTH = "stopped_on_health_failure"
TERM_ERROR = "errored"
TERM_INTERRUPTED = "interrupted"

# A tokenizer whose config omits model_max_length reports a sentinel around
# 1e19. Boundary cases built around that number would be meaningless, and the
# manifest would record them as exact, which is silently wrong.
MIN_PLAUSIBLE_MAX_TOKENS = 16
MAX_PLAUSIBLE_MAX_TOKENS = 100_000

# What a bare `--version v1|v2` has always meant, now written down rather than
# assumed. It is used ONLY to resolve that legacy flag; nothing else defaults to it,
# and an unrecognised identity never falls back to it.
LEGACY_TASK_ID = "emotion_7"


# --------------------------------------------------------------------------
# case keys
# --------------------------------------------------------------------------


def baseline_key(baseline_id: str) -> str:
    return f"baseline:{baseline_id}"


def attack_key(attack_id: str) -> str:
    return f"attack:{attack_id}"


# --------------------------------------------------------------------------
# fingerprinting
# --------------------------------------------------------------------------


def _canonical(payload: dict) -> bytes:
    """JSON with sorted keys, UTF-8, no incidental whitespace."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _encode_raw_body(body: bytes | str | None) -> dict:
    """Tag the body kind so a byte body can never collide with a string body.

    Without the tag, b'{"text":1}' and '{"text":1}' hash identically, and
    those are different tests. Bytes are base64'd because they may be
    deliberately invalid UTF-8 and so cannot go through JSON as text.
    """
    if body is None:
        return {"kind": "none"}
    if isinstance(body, bytes):
        return {"kind": "bytes", "b64": base64.b64encode(body).decode("ascii")}
    return {"kind": "str", "value": body}


def _baseline_fields(baseline: BaselineCase) -> dict:
    return {
        "kind": "baseline",
        "baseline_id": baseline.baseline_id,
        "text": baseline.text,
        "label": baseline.label,
        "source": baseline.source,
    }


def _attack_fields(case: AttackCase) -> dict:
    return {
        "kind": "attack",
        "attack_id": case.attack_id,
        "baseline_id": case.baseline_id,
        "category": case.category,
        "is_raw": bool(case.is_raw),
        "original_text": case.original_text,
        "attacked_text": case.attacked_text,
        "raw_body": _encode_raw_body(case.raw_body),
        "raw_headers": case.raw_headers,
    }


def fingerprint_suite(baselines: Sequence[BaselineCase], attacks: Sequence[AttackCase]) -> str:
    """SHA-256 of the complete built suite, in send order.

    Always computed over the *full* suite, before --limit or any skip is
    applied. That is deliberate, and it is the part that is easy to get
    backwards: the fingerprint records what we planned to send, so a limited
    run and a full run of the same suite must produce the same hash and differ
    only in their coverage numbers. A mismatch between V1 and V2 then always
    means something real is wrong, never that someone used a flag.

    Each record is hashed as canonical JSON built from a fixed field list,
    with a separator between records, rather than by concatenating field
    values: concatenation is ambiguous, since two different cases can produce
    the same joined string. Never hash a Python repr, whose formatting is not
    guaranteed stable across versions.
    """
    digest = hashlib.sha256()
    for baseline in baselines:
        digest.update(_canonical(_baseline_fields(baseline)))
        digest.update(b"\x1e")          # ASCII record separator
    for case in attacks:
        digest.update(_canonical(_attack_fields(case)))
        digest.update(b"\x1e")
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# target resolution
#
# `version` never identifies a model. `sentiment_v1` and `emotion_v1` are both
# version "v1"; a row that records only "v1" cannot say which one produced it.
# Everything below therefore resolves a real target_id from the registry and
# treats `--version` as a legacy alias for the emotion target of that version.
# --------------------------------------------------------------------------


class SelectionError(ValueError):
    """A case selection that cannot be executed exactly as frozen."""


@dataclasses.dataclass(frozen=True)
class ResolvedTarget:
    """What a run is pointed at, resolved from the registry rather than guessed."""

    target_id: str
    version: str
    task_id: str
    suite_id: str
    registry: Registry
    evaluation_id: str | None = None
    # How target_id was arrived at: "--target-id", "--version (emotion default)" or
    # "--evaluation-id". Recorded so a reader never has to guess whether an identity
    # was declared or inferred.
    resolved_from: str = ""


def emotion_target_for_version(registry: Registry, version: str) -> str:
    """The explicit emotion target a legacy ``--version`` flag means.

    Legacy calls keep working, but they stop being ambiguous at this line: the
    default is written down, resolved against the registry, and recorded on every
    row. There is no code path where an unrecognised identity quietly becomes
    emotion -- an unmatched version raises here instead.
    """
    matches = sorted(
        target_id
        for target_id, spec in registry.targets.items()
        if spec.version == version and spec.task_id == LEGACY_TASK_ID
    )
    if len(matches) != 1:
        raise ContractError(
            f"--version {version!r} does not name exactly one {LEGACY_TASK_ID} target "
            f"in the registry (found {matches}). Pass --target-id explicitly."
        )
    return matches[0]


def resolve_target(
    registry: Registry,
    *,
    target_id: str | None,
    version: str | None,
    suite: str,
    evaluation_id: str | None,
) -> ResolvedTarget:
    """Turn the CLI flags into one unambiguous target, or refuse.

    Conflicts are errors, never a precedence rule: if ``--target-id sentiment_v1``
    and ``--version v2`` disagree, silently preferring one of them would write rows
    labelled with a target that did not serve them.
    """
    if target_id is None and version is None:
        raise ContractError("one of --target-id or --version is required")
    if suite not in SUITES:
        raise ContractError(f"unknown suite {suite!r}; configured: {sorted(SUITES)}")

    if target_id is not None:
        spec = registry.target(target_id)          # raises on an unknown id
        if version is not None and spec.version != version:
            raise ContractError(
                f"--target-id {target_id!r} is version {spec.version!r}, but "
                f"--version {version!r} was also given. Drop one; they conflict."
            )
        resolved_from = "--target-id"
    else:
        target_id = emotion_target_for_version(registry, version)
        spec = registry.target(target_id)
        resolved_from = f"--version {version} (explicit {LEGACY_TASK_ID} default)"

    if evaluation_id is not None:
        evaluation = registry.evaluation(evaluation_id)   # raises on an unknown id
        if target_id not in evaluation.target_ids:
            raise ContractError(
                f"evaluation {evaluation_id!r} covers targets "
                f"{list(evaluation.target_ids)}, not {target_id!r}"
            )
        if evaluation.suite_id != suite:
            raise ContractError(
                f"evaluation {evaluation_id!r} is suite {evaluation.suite_id!r}, but "
                f"--suite {suite!r} was given. They conflict."
            )
        resolved_from = f"--evaluation-id {evaluation_id}"

    return ResolvedTarget(
        target_id=target_id,
        version=spec.version,
        task_id=spec.task_id,
        suite_id=suite,
        registry=registry,
        evaluation_id=evaluation_id,
        resolved_from=resolved_from,
    )


def build_token_counter_for_target(
    target_id: str, registry: Registry
) -> tuple[Callable[[str], int], int, dict]:
    """The pinned tokenizer for THIS target, with no model weights loaded.

    Imported inside the function for the same reason ``build_token_counter`` is, and
    for a second one that matters more here: ``endpoint.model`` is the *emotion*
    model and loads its weights at import time. Reaching it during a sentiment run
    would count sentiment text with an emotion tokenizer -- every boundary case would
    then sit on the wrong token -- and would load a model nobody asked for. This path
    touches ``endpoint.loader`` only, which reads the pinned tokenizer and config and
    no weights at all.
    """
    from endpoint.loader import load_target_tokenizer

    context = load_target_tokenizer(target_id, registry=registry)
    if (context.target_id != target_id
            or context.task_id != registry.task_for(target_id).task_id
            or context.model_spec != registry.model_for(target_id)
            or context.max_tokens != registry.model_for(target_id).max_sequence_length):
        raise ContractError(f"{target_id}: wrong tokenizer context or token limit")
    max_tokens = int(context.max_tokens)
    if not MIN_PLAUSIBLE_MAX_TOKENS <= max_tokens <= MAX_PLAUSIBLE_MAX_TOKENS:
        raise RuntimeError(
            f"{target_id}: resolved token limit {max_tokens} is not a plausible "
            "limit. Boundary cases built around it would be meaningless and the "
            "manifest would record them as exact."
        )
    return context.count_tokens, max_tokens, context.describe()


# --------------------------------------------------------------------------
# frozen case selections
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CaseSelection:
    """A frozen selection within a suite, read from a case-set file.

    The ids and their order are the contract. This object never reorders, dedupes or
    completes them -- anything that would need doing to make the file usable is
    raised instead, because a selection quietly repaired here no longer matches the
    selection the policy was frozen against.
    """

    case_set_id: str
    selection_version: int
    suite_id: str
    baseline_ids: tuple[str, ...]
    attack_ids: tuple[str, ...]
    order: tuple[str, ...]
    exclusions: tuple[dict, ...]
    source_path: str
    source_sha256: str

    def describe(self) -> dict:
        return {
            "case_set_id": self.case_set_id,
            "selection_version": self.selection_version,
            "suite_id": self.suite_id,
            "path": self.source_path,
            "sha256": self.source_sha256,
            "counts": {
                "baselines": len(self.baseline_ids),
                "attacks": len(self.attack_ids),
                "total_cases": len(self.order),
            },
            "exclusions": [dict(item) for item in self.exclusions],
        }


def _string_list(raw, where: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise SelectionError(f"{where} must be a list of non-empty strings")
    duplicates = sorted({x for x in raw if raw.count(x) > 1})
    if duplicates:
        raise SelectionError(f"{where} contains duplicate ids: {duplicates}")
    return list(raw)


def load_case_set(path: Path | str) -> CaseSelection:
    """Read a frozen case-set file. Rejects anything it would have to guess about.

    Accepts the common selection format from CONTRACTS.md 5.2. It also accepts a file
    that splits its attacks into ``standalone_attack_ids`` and ``derived_attack_ids``
    -- the shape ``analysis/case_sets/ci_core_v1.json`` is frozen in -- by reading
    them in that order, which is the runner's own send order. `order` stays optional
    for the same reason: when it is absent the send order below is authoritative, and
    when it is present it must agree with the ids exactly.
    """
    path = Path(path)
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise SelectionError(f"cannot read case set {path}: {exc}") from exc
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"case set {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SelectionError(f"case set {path} must be a JSON object")

    case_set_id = raw.get("case_set_id")
    if not isinstance(case_set_id, str) or not case_set_id:
        raise SelectionError(f"{path}: case_set_id is required")
    suite_id = raw.get("suite_id")
    if suite_id not in SUITES:
        raise SelectionError(
            f"{path}: suite_id {suite_id!r} is not one of {sorted(SUITES)}. CI is a "
            "frozen selection of 'core', not a suite of its own."
        )
    selection_version = raw.get("selection_version", 1)
    if type(selection_version) is not int or selection_version < 1:
        raise SelectionError(f"{path}: selection_version must be a positive integer")

    baseline_ids = _string_list(raw.get("baseline_ids", []), f"{path}.baseline_ids")
    if "attack_ids" in raw:
        attack_ids = _string_list(raw["attack_ids"], f"{path}.attack_ids")
    else:
        standalone = _string_list(
            raw.get("standalone_attack_ids", []), f"{path}.standalone_attack_ids"
        )
        derived = _string_list(
            raw.get("derived_attack_ids", []), f"{path}.derived_attack_ids"
        )
        attack_ids = standalone + derived
        overlap = sorted(set(standalone) & set(derived))
        if overlap:
            raise SelectionError(
                f"{path}: {overlap} appear in both standalone_attack_ids and "
                "derived_attack_ids"
            )
    if "attack_ids" in raw and ("standalone_attack_ids" in raw or "derived_attack_ids" in raw):
        split_ids = _string_list(raw.get("standalone_attack_ids", []), "standalone_attack_ids")
        split_ids += _string_list(raw.get("derived_attack_ids", []), "derived_attack_ids")
        if split_ids != attack_ids:
            raise SelectionError(f"{path}: attack_ids conflicts with split attack lists")
    if not baseline_ids and not attack_ids:
        raise SelectionError(f"{path}: the selection is empty; there is nothing to run")

    derived_keys = [baseline_key(b) for b in baseline_ids] + [
        attack_key(a) for a in attack_ids
    ]
    declared_order = raw.get("order")
    if declared_order is None:
        order = tuple(derived_keys)
    else:
        order = tuple(_string_list(declared_order, f"{path}.order"))
        if sorted(order) != sorted(derived_keys):
            missing = sorted(set(derived_keys) - set(order))
            extra = sorted(set(order) - set(derived_keys))
            raise SelectionError(
                f"{path}: order does not match the selected ids "
                f"(missing {missing}, unexpected {extra})"
            )

    exclusions = raw.get("exclusions", [])
    if not isinstance(exclusions, list) or not all(
        isinstance(item, dict) for item in exclusions
    ):
        raise SelectionError(f"{path}.exclusions must be a list of objects")

    return CaseSelection(
        case_set_id=case_set_id,
        selection_version=selection_version,
        suite_id=suite_id,
        baseline_ids=tuple(baseline_ids),
        attack_ids=tuple(attack_ids),
        order=order,
        exclusions=tuple(dict(item) for item in exclusions),
        source_path=str(path),
        source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def apply_case_set(
    selection: CaseSelection,
    baselines: Sequence[BaselineCase],
    attacks: Sequence[AttackCase],
) -> list[BaselineCase | AttackCase]:
    """The selected cases, in the selection's order. Every id must really exist.

    An unknown id is an error and not a skip. A selection naming a case the built
    suite does not contain describes a different suite, and running the remainder
    would produce coverage numbers over a denominator nobody chose.
    """
    if len({case.baseline_id for case in baselines}) != len(baselines):
        raise SelectionError("built suite contains duplicate baseline ids")
    if len({case.attack_id for case in attacks}) != len(attacks):
        raise SelectionError("built suite contains duplicate attack ids")
    baseline_index = {case.baseline_id: case for case in baselines}
    attack_index = {case.attack_id: case for case in attacks}

    unknown_baselines = [b for b in selection.baseline_ids if b not in baseline_index]
    unknown_attacks = [a for a in selection.attack_ids if a not in attack_index]
    if unknown_baselines or unknown_attacks:
        raise SelectionError(
            f"case set {selection.case_set_id!r} selects cases this suite does not "
            f"contain: baselines {unknown_baselines}, attacks {unknown_attacks}"
        )

    selected_baselines = set(selection.baseline_ids)
    orphans = sorted(
        attack_id
        for attack_id in selection.attack_ids
        if attack_index[attack_id].baseline_id is not None
        and attack_index[attack_id].baseline_id not in selected_baselines
    )
    if orphans:
        raise SelectionError(
            f"case set {selection.case_set_id!r} selects derived attacks whose "
            f"baseline is not selected: {orphans}. A derived case with no clean "
            "result to compare against cannot be scored."
        )

    units: list[BaselineCase | AttackCase] = []
    for key in selection.order:
        kind, _, identifier = key.partition(":")
        if kind == "baseline":
            units.append(baseline_index[identifier])
        elif kind == "attack":
            units.append(attack_index[identifier])
        else:
            raise SelectionError(
                f"case set {selection.case_set_id!r}: {key!r} is not a case key; "
                "expected 'baseline:<id>' or 'attack:<id>'"
            )
    return units


def fingerprint_selection(
    selected_keys: Sequence[str], *, case_set_id: str | None, suite_id: str
) -> str:
    """SHA-256 over exactly what was selected, in order.

    Recorded as ``fingerprints.selected_order_sha256``, and distinct from both of
    its neighbours on purpose:

    - ``planned_suite_sha256`` says what the whole suite is;
    - ``selection_sha256`` is the SHA-256 of the case-selection **file**, so a
      reviewer can confirm which committed selection a run was pointed at, and is
      ``null`` when no selection file was used (see the fixture run metadata);
    - this one says what was *actually executed*, in order, which is the only one of
      the three that still exists for a run with no case-set file at all.

    The hashed document is canonical JSON, sorted keys, UTF-8, no incidental
    whitespace:

        {"case_set_id": <str|null>, "order": [<case keys, in order>],
         "suite_id": <str>}
    """
    return hashlib.sha256(
        _canonical(
            {
                "case_set_id": case_set_id,
                "suite_id": suite_id,
                "order": list(selected_keys),
            }
        )
    ).hexdigest()


def code_provenance(root: Path | None = None) -> dict:
    """The commit this run's code came from, or an honest null.

    A run that cannot say which code produced it is still a valid run; it is not a
    run anything may be compared against. Recording null says that plainly instead of
    leaving the field out and letting a reader assume a clean tree.
    """
    import subprocess

    base = Path(root) if root is not None else ROOT
    def git(*argv: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", *argv], cwd=base, capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {
        "app_commit": commit,
        "dirty": None if status is None else bool(status),
    }


# --------------------------------------------------------------------------
# building the suite
# --------------------------------------------------------------------------


def build_token_counter(target_id: str | None = None) -> tuple[Callable[[str], int], int]:
    """The real tokenizer, so boundary cases land on the true token limit.

    Imported inside the function rather than at module scope: endpoint.model
    loads the whole model at import time, and the tests must not pay for that.

    truncation=False is required. Silent truncation would neutralise two whole
    attack categories, and this is the only place outside the endpoint folder
    that calls the tokenizer directly.
    """
    if target_id is not None:
        counter, limit, _ = build_token_counter_for_target(
            target_id, target_registry.load_registry()
        )
        return counter, limit

    from endpoint.model import MAX_SEQUENCE_LENGTH, tokenizer

    max_tokens = int(MAX_SEQUENCE_LENGTH)
    if not MIN_PLAUSIBLE_MAX_TOKENS <= max_tokens <= MAX_PLAUSIBLE_MAX_TOKENS:
        raise RuntimeError(
            f"endpoint.model.MAX_SEQUENCE_LENGTH is {max_tokens}, which is not a "
            "plausible token limit. Hugging Face reports a huge sentinel when a "
            "tokenizer config omits model_max_length. Boundary cases built around "
            "that would be meaningless and the manifest would record them as exact."
        )

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    return count_tokens, max_tokens


def build_suite_once(
    baselines: Sequence[BaselineCase],
    token_counter: Callable[[str], int] | None,
    max_tokens: int | None,
    *,
    suite: str = SUITE_CORE,
    task_id: str = LEGACY_TASK_ID,
) -> list[AttackCase]:
    """Build the attack suite exactly once.

    Once matters. library.write_manifest dumps every case built so far, so a
    throwaway build -- counting cases, say -- would stamp a second entry for
    the same attack_id into the sidecar, and a build without the tokenizer
    would stamp approximate boundaries into it. The analysis would then be
    joining results against an oracle describing different cases.

    ``suite``/``task_id`` are CONTRACTS.md 4.2's keyword-only arguments with their
    legacy defaults. They are forwarded only when the installed attack library
    actually accepts them: the library is Lamei's and lands separately, so until it
    does, a request for the legacy combination behaves exactly as it always has and
    a request for anything else fails loudly instead of silently running the emotion
    core suite under a sentiment or OCES label.
    """
    kwargs: dict = {"token_counter": token_counter, "max_tokens": max_tokens}
    parameters = inspect.signature(library.build_suite).parameters
    if "suite" in parameters and "task_id" in parameters:
        kwargs["suite"] = suite
        kwargs["task_id"] = task_id
    elif suite != SUITE_CORE or task_id != LEGACY_TASK_ID:
        raise ContractError(
            f"attacks.library.build_suite does not yet accept suite/task_id, so "
            f"suite={suite!r} task_id={task_id!r} cannot be built. Building the "
            "legacy core/emotion suite and labelling it otherwise would put the "
            "wrong cases behind the right name. Waiting on CONTRACTS.md 4.2."
        )
    return library.build_suite(list(baselines), **kwargs)


def partition_attacks(
    attacks: Sequence[AttackCase],
) -> tuple[list[AttackCase], list[AttackCase]]:
    """Standalone first, then derived, each keeping the library's order."""
    standalone = [case for case in attacks if case.baseline_id is None]
    derived = [case for case in attacks if case.baseline_id is not None]
    return standalone, derived


def default_send_order(
    baselines: Sequence[BaselineCase], attacks: Sequence[AttackCase]
) -> list[BaselineCase | AttackCase]:
    """The order this runner has always used: baselines, standalone, derived.

    Stable across runs so two runs are comparable, and the order a case-set file
    with no explicit ``order`` is read in.
    """
    standalone, derived = partition_attacks(attacks)
    return [*baselines, *standalone, *derived]


# --------------------------------------------------------------------------
# recording
# --------------------------------------------------------------------------


def band_latency(latency_ms: float, timed_out: bool) -> str:
    """normal under 2s, slow from 2s up, timeout at the ceiling.

    The boundary belongs to slow: exactly 2000.0 ms is slow, not normal.
    """
    if timed_out:
        return BAND_TIMEOUT
    return BAND_SLOW if latency_ms >= SLOW_FROM_MS else BAND_NORMAL


def parse_prediction(body: str) -> tuple[str | None, float | None, dict | None]:
    """Read label, confidence and all_scores out of a response, if present.

    Every branch is a lookup, never a calculation. all_scores is recoverable
    from the body we already store, but it is a real typed field on RunResult,
    so it gets populated here rather than left for someone to re-parse.
    """
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None, None, None
    if not isinstance(payload, dict):
        return None, None, None

    label = payload.get("label")
    if not isinstance(label, str):
        label = None

    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = None
    else:
        confidence = float(confidence)

    scores = payload.get("all_scores")
    if not isinstance(scores, dict):
        scores = None

    return label, confidence, scores


class ResultWriter:
    """One JSON object per line, flushed to disk as each row completes.

    Opened with "w", so every invocation truncates its own file. Two runs must
    never share rows: if a smoke run's rows sat above a full run's, there would
    be no way to tell which run was being analysed.

    Incremental by construction rather than by remembering to flush at the end.
    If attack 43 kills the endpoint, the first 43 rows -- including the one that
    did the killing -- are already on disk.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        self.count = 0

    def write(self, result: RunResult) -> None:
        self._handle.write(json.dumps(dataclasses.asdict(result), ensure_ascii=False) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.count += 1

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> "ResultWriter":
        return self

    def __exit__(self, *_) -> None:
        self.close()


# --------------------------------------------------------------------------
# the runner
# --------------------------------------------------------------------------


class EndpointDied(Exception):
    """The health check failed after a request."""

    def __init__(self, result: RunResult, describe_text: str) -> None:
        super().__init__(describe_text)
        self.result = result
        self.describe = describe_text


def describe(result: RunResult) -> str:
    if result.case_type == "baseline":
        return f"baseline {result.baseline_id}"
    return f"attack {result.attack_id} (category {result.category}, baseline {result.baseline_id})"


class Runner:
    def __init__(
        self,
        target: str,
        version: str,
        writer: ResultWriter | None,
        predict_path: str = "/predict",
        health_path: str = "/health",
        timeout: float = REQUEST_TIMEOUT,
        health_timeout: float = HEALTH_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.perf_counter,
        skip: Sequence[str] = (),
        on_record: Callable[[RunResult], None] | None = None,
        target_id: str = "",
        suite_id: str = "",
    ) -> None:
        if timeout != REQUEST_TIMEOUT:
            raise ValueError(f"request timeout must be {REQUEST_TIMEOUT} seconds")
        if not math.isfinite(health_timeout) or health_timeout <= 0:
            raise ValueError("health timeout must be finite and greater than zero")
        self.base = target.rstrip("/")
        self.version = version
        # Recorded on every row. Blank is supported so existing callers are unchanged,
        # and means exactly "this caller did not declare an identity" -- never
        # "assume emotion". main() always supplies both for a new run.
        self.target_id = target_id
        self.suite_id = suite_id
        self.writer = writer
        self.predict_url = self.base + predict_path
        self.health_url = self.base + health_path
        self.timeout = timeout
        self.health_timeout = health_timeout
        self._transport = transport
        self.clock = clock
        self.skip = set(skip)
        self.on_record = on_record

        self.completed: list[str] = []
        self.skipped: list[str] = []
        # Operational transport counts: facts about the wire, not judgements
        # about the endpoint. The analysis decides what any of them mean.
        self.counts = {
            "timeouts": 0,
            "connection_errors": 0,
            "server_errors_5xx": 0,
            "health_ping_retries": 0,
            "health_failures": 0,
            # Bodies we failed to serialise. Counted apart from transport failures
            # because nothing reached the wire: the endpoint never saw the request.
            "serialization_errors": 0,
        }
        # One loop for the lifetime of the connection pool. The public runner
        # remains synchronous and sends exactly one request at a time.
        self._async_runner = asyncio.Runner()
        self._closed = False
        self.client = self._new_client()

    # -- connections --------------------------------------------------------

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport, follow_redirects=False
        )

    def reset_client(self) -> None:
        try:
            self._async_runner.run(self.client.aclose())
        except Exception:
            pass
        self.client = self._new_client()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._async_runner.run(self.client.aclose())
        finally:
            self._async_runner.close()
            self._closed = True

    async def _request(self, method: str, url: str, timeout: float, **kwargs) -> httpx.Response:
        # HTTPX's individual I/O timeouts reset as a response progresses. This
        # outer deadline includes connection, upload, headers and the full body.
        # Cancellation closes the in-flight response; no worker thread or retry
        # continues the attack after it has been recorded as timed out.
        async with asyncio.timeout(timeout):
            return await self.client.request(method, url, timeout=timeout, **kwargs)

    async def _send_prepared(self, request: httpx.Request) -> httpx.Response:
        """Send the exact request whose bytes were already measured."""
        async with asyncio.timeout(self.timeout):
            return await self.client.send(request, follow_redirects=False)

    # -- the bytes that actually go on the wire -----------------------------

    def prepare_request(
        self, case: AttackCase | None, text: str | None
    ) -> tuple[httpx.Request, bytes]:
        """Build the request and read back the body the client will really send.

        The body evidence has to be the *sender's* record of the bytes on the wire,
        so it is taken from the prepared request rather than recomputed from the
        text. Recomputing is how the old reports ended up guessing: a JSON body is
        not its text, ``ensure_ascii`` changes its length, and a raw body is not
        text at all. This returns the request object itself, and that same object is
        the one sent -- nothing re-serialises it in between.
        """
        if case is not None and case.is_raw:
            body = case.raw_body
            if isinstance(body, str):
                body = body.encode("utf-8")
            elif body is None:
                body = b""
            # Verbatim. These bytes may be deliberately invalid UTF-8, and the
            # headers are part of the test. Using json= here, or adding a header,
            # would repair the very thing being tested.
            request = self.client.build_request(
                "POST",
                self.predict_url,
                content=body,
                headers=dict(case.raw_headers or {}),
                timeout=self.timeout,
            )
        else:
            request = self.client.build_request(
                "POST", self.predict_url, json={"text": text}, timeout=self.timeout
            )
        return request, request.read()

    # -- sending ------------------------------------------------------------

    def send(self, case: AttackCase | None, text: str | None) -> dict:
        """One request. No retry: a connection failure is recorded as one.

        Attack requests are never retried, because a connection-level failure
        is one of the three outcomes the analysis counts separately, and a
        retry would hide it. The health ping does retry once, for a reason
        specific to the ping -- see health_ok.

        Every return carries the request-body evidence, including the failures.
        A request that got no response still has a known attempted body, and
        that is exactly the case where "how big was it really?" is asked.
        """
        started = self.clock()
        try:
            request, body = self.prepare_request(case, text)
        except Exception as exc:                      # noqa: BLE001
            # No bytes ever existed, so there is nothing to measure. Recording 0
            # here would claim we sent an empty body and the endpoint accepted it.
            latency_ms = (self.clock() - started) * 1000.0
            self.counts["serialization_errors"] += 1
            return {
                "status_code": None,
                "response_body": "",
                "error": (
                    f"{ERR_SERIALIZATION}: {type(exc).__name__}: {exc}. No request "
                    "was sent and no body bytes exist to record."
                ),
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                "request_body_bytes": None,
                "request_body_sha256": None,
            }

        evidence = {
            "request_body_bytes": len(body),
            "request_body_sha256": hashlib.sha256(body).hexdigest(),
        }

        try:
            response = self._async_runner.run(self._send_prepared(request))

            latency_ms = (self.clock() - started) * 1000.0
            if response.status_code >= 500:
                self.counts["server_errors_5xx"] += 1
            return {
                "status_code": response.status_code,
                "response_body": response.text,
                "error": None,
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                **evidence,
            }

        except (TimeoutError, httpx.TimeoutException) as exc:
            latency_ms = (self.clock() - started) * 1000.0
            self.counts["timeouts"] += 1
            return {
                "status_code": None,
                "response_body": "",
                "error": f"{ERR_TIMEOUT}: no response within {self.timeout}s ({type(exc).__name__})",
                "latency_ms": round(latency_ms, 2),
                "latency_band": BAND_TIMEOUT,
                **evidence,
            }

        except httpx.TransportError as exc:
            latency_ms = (self.clock() - started) * 1000.0
            self.counts["connection_errors"] += 1
            return {
                "status_code": None,
                "response_body": "",
                "error": f"{ERR_CONNECTION}: {type(exc).__name__}: {exc}",
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                **evidence,
            }

        except httpx.HTTPError as exc:
            latency_ms = (self.clock() - started) * 1000.0
            return {
                "status_code": None,
                "response_body": "",
                "error": f"{ERR_TRANSPORT}: {type(exc).__name__}: {exc}",
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                **evidence,
            }

    def health_ok(self) -> bool:
        """Ping health, retrying once on a fresh connection.

        The retry is here for one specific reason, and it is not leniency.
        Uvicorn answers a 500 with Connection: close, which leaves a dead
        socket in our pool, so the ping that follows a 500 can fail against a
        perfectly healthy service. Since the health check runs after every
        request and a failure stops the run, that would abandon the run on the
        first 500 and name an innocent payload as the killer. The retry dials a
        new connection; the count goes in the meta file.
        """
        for attempt in (1, 2):
            try:
                response = self._async_runner.run(self._request(
                    "GET", self.health_url, self.health_timeout
                ))
                return response.status_code == 200
            except (TimeoutError, httpx.TransportError):
                if attempt == 1:
                    self.counts["health_ping_retries"] += 1
                    self.reset_client()
                    continue
                return False
            except httpx.HTTPError:
                return False
        return False

    def preflight(self) -> bool:
        """Confirm the endpoint answers before anything is sent.

        Without this, an endpoint that was already down gets blamed on the
        first baseline, which looks like a clean sentence killing the service.
        """
        return self.health_ok()

    # -- one case -----------------------------------------------------------

    def _record(
        self,
        case_type: str,
        outcome: dict,
        key: str,
        attack_id: str | None,
        baseline_id: str | None,
        category: str | None,
    ) -> RunResult:
        label, confidence, scores = parse_prediction(outcome["response_body"])
        alive = self.health_ok()
        if not alive:
            self.counts["health_failures"] += 1

        result = RunResult(
            case_type=case_type,
            attack_id=attack_id,
            baseline_id=baseline_id,
            category=category,
            version=self.version,
            status_code=outcome["status_code"],
            response_body=outcome["response_body"],
            error=outcome["error"],
            label=label,
            confidence=confidence,
            all_scores=scores,
            latency_ms=outcome["latency_ms"],
            latency_band=outcome["latency_band"],
            endpoint_alive_after=alive,
            target_id=self.target_id,
            suite_id=self.suite_id,
            # .get, not [], so a caller that hands _record a hand-built outcome
            # gets an honest "unavailable" rather than a KeyError or a zero.
            request_body_bytes=outcome.get("request_body_bytes"),
            request_body_sha256=outcome.get("request_body_sha256"),
        )
        if self.writer is None:
            raise RuntimeError("a result writer is required before sending cases")
        self.writer.write(result)          # on disk before we act on it
        self.completed.append(key)
        if self.on_record:
            self.on_record(result)
        if not alive:
            raise EndpointDied(result, describe(result))
        return result

    def send_baseline(self, baseline: BaselineCase) -> RunResult:
        outcome = self.send(None, baseline.text)
        # A baseline is not an attack: no attack_id, and no category invented.
        return self._record(
            "baseline",
            outcome,
            baseline_key(baseline.baseline_id),
            None,
            baseline.baseline_id,
            None,
        )

    def send_attack(self, case: AttackCase) -> RunResult | None:
        if case.attack_id in self.skip:
            key = attack_key(case.attack_id)
            if key not in self.skipped:
                self.skipped.append(key)
            return None
        text = case.attacked_text if case.attacked_text is not None else case.original_text
        outcome = self.send(case, text)
        return self._record(
            "attack",
            outcome,
            attack_key(case.attack_id),
            case.attack_id,
            case.baseline_id,
            case.category,
        )

    # -- the whole suite ----------------------------------------------------

    def run(self, baselines: Sequence[BaselineCase], attacks: Sequence[AttackCase]) -> None:
        """Baselines, then standalone attacks, then derived attacks."""
        # Skips are a property of the plan, including cases never reached after
        # a health failure. main() has already applied the limit to attacks.
        self.skipped = [attack_key(case.attack_id) for case in attacks if case.attack_id in self.skip]
        self.run_ordered(default_send_order(baselines, attacks), reset_skipped=False)

    def run_ordered(
        self,
        units: Sequence[BaselineCase | AttackCase],
        *,
        reset_skipped: bool = True,
    ) -> None:
        """Send exactly these cases, in exactly this order.

        The order is the caller's, because a frozen selection's order is part of
        what was frozen: two runs that send the same cases in a different order are
        not the same experiment once state, caching or an endpoint death is involved.
        ``run`` is this function with the default order, so there is one send loop.
        """
        if reset_skipped:
            self.skipped = [
                attack_key(case.attack_id)
                for case in units
                if isinstance(case, AttackCase) and case.attack_id in self.skip
            ]
        for unit in units:
            if isinstance(unit, AttackCase):
                self.send_attack(unit)
            else:
                self.send_baseline(unit)


# --------------------------------------------------------------------------
# coverage and meta
# --------------------------------------------------------------------------


def select_attacks(
    attacks: Sequence[AttackCase], limit: int | None
) -> tuple[list[AttackCase], list[str]]:
    """Apply --limit to attacks only.

    Baselines are never limited: derived attacks are meaningless without the
    clean result to compare them against, and "first N cases" across the whole
    suite would send only baselines and no attacks at all.
    """
    if limit is None:
        return list(attacks), []
    if limit < 0:
        raise ValueError("attack limit must be non-negative")
    kept = list(attacks[:limit])
    excluded = [attack_key(case.attack_id) for case in attacks[limit:]]
    return kept, excluded


def build_meta(
    *,
    run_id: str,
    version: str,
    started_at: str,
    ended_at: str,
    is_smoke: bool,
    termination_reason: str,
    planned_fingerprint: str,
    manifest_sha256: str | None,
    manifest_path: str,
    target: str,
    planned: Sequence[str],
    selected: Sequence[str],
    completed: Sequence[str],
    skipped: Sequence[str],
    limit_excluded: Sequence[str],
    limit: int | None,
    counts: dict,
    deselected: Sequence[str] = (),
    suite_sizes: dict,
    request_timeout: float = REQUEST_TIMEOUT,
    health_timeout: float = HEALTH_TIMEOUT,
    # --- Stage 3 identity. All defaulted, so every existing call still works and
    # --- still produces exactly the file it produced before.
    target_id: str = "",
    suite_id: str = "",
    task_id: str = "",
    evaluation_id: str | None = None,
    evaluation_run_id: str | None = None,
    case_set_id: str | None = None,
    model: dict | None = None,
    baseline_source: dict | None = None,
    registry_source: dict | None = None,
    coverage_map: dict | None = None,
    case_set: dict | None = None,
    tokenizer: dict | None = None,
    selection_sha256: str | None = None,
    selected_order_sha256: str | None = None,
    results_sha256: str | None = None,
    provenance: dict | None = None,
    resolved_from: str = "",
) -> dict:
    """The meta file.

    Coverage exists because a fingerprint says both runs were *planned*
    identically and nothing about whether both *finished*. A V1 run that died
    after ten attacks shares its planned fingerprint with a complete V2 run;
    without coverage, a missing V2 result reads as "V2 fixed it", which is
    exactly backwards. The ordered id lists matter as much as the counts: the
    analysis needs to know which cases are absent, to mark them unavailable
    rather than resolved.

    planned is always the full built suite and is never reduced by any flag.
    """
    completed_set = set(completed)
    missing = [key for key in selected if key not in completed_set]
    planned_count = len(planned)
    return {
        "run_id": run_id,
        # The enclosing run this was one target of, when an orchestrator supplied
        # one. null means this invocation stood alone -- it is not the same thing as
        # run_id, and it is never filled in from it.
        "evaluation_run_id": evaluation_run_id,
        "evaluation_id": evaluation_id,
        "version": version,
        "target_id": target_id,
        "task_id": task_id,
        "suite_id": suite_id,
        "identity_resolved_from": resolved_from,
        "target": target,
        "started_at": started_at,
        "ended_at": ended_at,
        "run_type": "smoke" if is_smoke else "full",
        "limit": limit,
        "termination_reason": termination_reason,
        "model": model,
        "baseline": baseline_source,
        "registry": registry_source,
        "coverage_map": coverage_map,
        "case_set": case_set,
        "case_set_id": case_set_id,
        "tokenizer": tokenizer,
        "code_provenance": provenance,
        "fingerprints": {
            "planned_suite_sha256": planned_fingerprint,
            "manifest_sha256": manifest_sha256,
            "manifest_path": manifest_path,
            "coverage_map_sha256": coverage_map["sha256"] if coverage_map else None,
            # Of the case-selection FILE this run was pointed at; null when there
            # was none, because there is then no file whose bytes could be hashed.
            "selection_sha256": selection_sha256,
            # Of the ordered selection actually executed, and of the rows actually
            # written. null where the value is genuinely unavailable -- a run that
            # never opened a results file has no results hash, and saying 0 or ""
            # would be a claim about bytes that do not exist.
            "selected_order_sha256": selected_order_sha256,
            "results_sha256": results_sha256,
        },
        "suite": suite_sizes,
        "coverage": {
            "planned": planned_count,
            "skipped": len(skipped),
            "limit_excluded": len(limit_excluded),
            # Planned cases a frozen selection did not choose. Its own bucket
            # because it is not a skip and not a limit: nothing went wrong and no
            # flag was used, the selection simply names a part of the suite. Without
            # it, planned minus the other three buckets would not close and a reader
            # would be left to infer which of the three absorbed the difference.
            "deselected": len(deselected),
            "selected": len(selected),
            "completed": len(completed),
            "missing": len(missing),
            "coverage_rate": round(len(completed) / planned_count, 6) if planned_count else 0.0,
        },
        "case_ids": {
            "planned": list(planned),
            "selected": list(selected),
            "completed": list(completed),
            "skipped": list(skipped),
            "limit_excluded": list(limit_excluded),
            "deselected": list(deselected),
            "missing": missing,
        },
        "transport_counts": counts,
        "runner_settings": {
            "request_timeout_s": request_timeout,
            "health_timeout_s": health_timeout,
            "slow_band_from_ms": SLOW_FROM_MS,
        },
    }


def write_meta(path: Path, meta: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runner.run", description="Fire the attack suite at one endpoint version."
    )
    # No default target and no default version: the same runner has to work
    # against a deployed endpoint later with no code change, and a deployed
    # endpoint has no port that tells us which version it is.
    parser.add_argument("--target", required=True, help="base URL of the endpoint")
    # No longer `required`, because --target-id now identifies a target on its own.
    # Every existing invocation passes --version and behaves exactly as before; what
    # changed is that the emotion default it implies is now explicit and resolved
    # through the registry instead of assumed.
    parser.add_argument(
        "--version", choices=("v1", "v2"), default=None,
        help="legacy flag; implies the emotion target of that version, explicitly",
    )
    parser.add_argument(
        "--target-id", default=None, metavar="ID",
        help="registry target id (derives --version). Conflicting flags are an error.",
    )
    parser.add_argument(
        "--suite", choices=tuple(sorted(SUITES)), default=SUITE_CORE,
        help=f"which case family set to build (default {SUITE_CORE})",
    )
    parser.add_argument(
        "--case-set", default=None, metavar="PATH",
        help="a frozen selection file; its ids and order are executed exactly",
    )
    parser.add_argument(
        "--evaluation-id", default=None, metavar="ID",
        help="registry evaluation this run is one target of; resolves the baseline file",
    )
    parser.add_argument(
        "--parent-run-id", default=None, metavar="HEX",
        help="run_id of the enclosing multi-target run, recorded as evaluation_run_id",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"output directory (default {DEFAULT_OUT}; send smoke runs to {DEFAULT_OUT}/smoke)",
    )
    parser.add_argument(
        "--limit", type=nonnegative_int, default=None,
        help="send at most N attacks. All baselines are always sent.",
    )
    parser.add_argument(
        "--skip", action="append", default=[], metavar="ATTACK_ID",
        help="attack id to exclude; repeatable. For a known endpoint killer.",
    )
    parser.add_argument("--predict-path", default="/predict")
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--timeout", type=float, choices=(REQUEST_TIMEOUT,), default=REQUEST_TIMEOUT,
                        help="fixed total request deadline in seconds (10)")
    parser.add_argument("--health-timeout", type=positive_seconds, default=HEALTH_TIMEOUT)
    # Approximate boundaries produce a manifest that describes different cases
    # from the ones a real run sends, so this is not for real runs.
    parser.add_argument("--no-tokenizer", action="store_true", help=argparse.SUPPRESS)
    return parser


def _validate_flag_combinations(args: argparse.Namespace) -> None:
    """Refuse combinations whose result nobody could predict from the flags.

    --limit and --skip against a frozen selection are the ones that matter. A
    selection is frozen so a policy can name exactly what was scored; quietly
    dropping cases from it would leave a run that still claims the frozen
    case_set_id while having executed something else.
    """
    if args.case_set is not None:
        if args.limit is not None:
            raise ContractError(
                "--limit cannot be combined with --case-set: a frozen selection "
                "already states exactly which cases run."
            )
        if args.skip:
            raise ContractError(
                "--skip cannot be combined with --case-set: dropping a case from a "
                "frozen selection would leave the run claiming a selection it did "
                "not execute. Change the case set, or run without one."
            )


@dataclasses.dataclass
class RunPlan:
    """Everything resolved before a single byte goes on the wire.

    Building this is the readiness phase. It loads the registry, resolves the
    target, reads the baseline the *evaluation* points at, builds the suite inside
    an isolated metadata scope and writes the manifest from that same build. If any
    of it fails, nothing in the output directory has been touched yet and the
    previous successful run is still the published one.
    """

    resolved: ResolvedTarget
    baselines: list[BaselineCase]
    attacks: list[AttackCase]
    planned_fingerprint: str
    planned_keys: list[str]
    units: list[BaselineCase | AttackCase]
    selected_keys: list[str]
    skipped_keys: list[str]
    limit_excluded: list[str]
    deselected: list[str]
    selection: CaseSelection | None
    selection_sha256: str | None
    selected_order_sha256: str
    baseline_source: dict
    model: dict
    registry_source: dict
    tokenizer: dict
    suite_sizes: dict
    build_identity: dict = dataclasses.field(default_factory=dict)
    manifest_bytes: bytes = b""
    coverage_map_bytes: bytes | None = None
    coverage_map: dict | None = None


def _resolve_baseline_file(resolved: ResolvedTarget) -> str:
    """The repo-relative baseline file this run must actually read.

    Always through the registry, and through ``baseline_file_for`` when there is an
    evaluation, because an evaluation-level override is the only way an OCES run
    finds its frozen seed file. Recording the core baseline's hash for an OCES run
    would claim the run used data it did not use.
    """
    registry = resolved.registry
    if resolved.evaluation_id is not None:
        return registry.baseline_file_for(resolved.evaluation_id)
    if resolved.suite_id != SUITE_CORE:
        raise ContractError(
            f"--suite {resolved.suite_id} has no baseline file of its own; pass "
            "--evaluation-id so the evaluation's seed-file override resolves. "
            "Falling back to the task default would run the wrong seeds."
        )
    return registry.task_for(resolved.target_id).baseline_file


def plan_run(
    args: argparse.Namespace, out_dir: Path, staging: Path, *,
    reuse_plan: RunPlan | None = None,
) -> RunPlan:
    """Resolve, load, build and register expectations. Sends nothing."""
    _validate_flag_combinations(args)

    registry = target_registry.load_registry()
    resolved = resolve_target(
        registry,
        target_id=args.target_id,
        version=args.version,
        suite=args.suite,
        evaluation_id=args.evaluation_id,
    )
    if resolved.evaluation_id is not None:
        declared_selection = registry.evaluation(resolved.evaluation_id).case_set_id
        if declared_selection is not None and args.case_set is None:
            raise SelectionError(
                f"evaluation {resolved.evaluation_id!r} requires --case-set {declared_selection!r}"
            )
        # Existence of the module and baseline file, checked immediately before
        # execution rather than at registry load -- see endpoint/targets.py.
        target_registry.require_runnable(registry, resolved.evaluation_id)

    baseline_rel = _resolve_baseline_file(resolved)
    baseline_path = ROOT / baseline_rel
    # File order from the loader, then sorted by id. Sorting means the
    # fingerprint changes only when the content changes, not when the baseline
    # file happens to be written in a different order.
    baselines = sorted(load_baseline(baseline_path), key=lambda b: b.baseline_id)

    registry_bytes = Path(registry.source_path).read_bytes()
    if hashlib.sha256(registry_bytes).hexdigest() != registry.source_sha256:
        raise ContractError("registry changed during planning")
    (staging / "registry.json").write_bytes(registry_bytes)

    build_identity = {
        "task_id": resolved.task_id,
        "suite_id": resolved.suite_id,
        "model": dataclasses.asdict(registry.model_for(resolved.target_id)),
        "baseline_path": baseline_rel,
        "baseline_sha256": sha256_file(baseline_path),
        "approximate": args.no_tokenizer,
        "registry_sha256": registry.source_sha256,
    }
    if reuse_plan is not None:
        if build_identity != reuse_plan.build_identity:
            raise ContractError("reused plan has a different task, suite, model, baseline or tokenizer context")
        if fingerprint_suite(reuse_plan.baselines, reuse_plan.attacks) != reuse_plan.planned_fingerprint:
            raise ContractError("reused plan cases changed after planning")
        baselines = copy.deepcopy(reuse_plan.baselines)
        token_counter = None  # the reused suite is already built
        max_tokens = reuse_plan.suite_sizes["max_tokens"]
        tokenizer_meta = copy.deepcopy(reuse_plan.tokenizer)
        if "target_id" in tokenizer_meta:
            tokenizer_meta["target_id"] = resolved.target_id
    elif args.no_tokenizer:
        token_counter, max_tokens = None, None
        tokenizer_meta = {
            "source": "approximate",
            "max_tokens": None,
            "weights_loaded": False,
            "note": "--no-tokenizer: length boundaries are approximate, testing only",
        }
        print("WARNING: approximate length boundaries, for testing only")
    else:
        token_counter, max_tokens, tokenizer_meta = build_token_counter_for_target(
            resolved.target_id, registry
        )
        tokenizer_meta = {"source": "tokenizer", **tokenizer_meta}

    # One isolated build per task/suite. Clearing the shared metadata registry first
    # is the point: without it, a suite built here would inherit every case already
    # registered in this process, and the manifest written from this build would
    # describe cases from another one.
    if reuse_plan is None:
        with scoped_registry():
            attacks = build_suite_once(
                baselines, token_counter, max_tokens,
                suite=resolved.suite_id, task_id=resolved.task_id,
            )
            library.write_manifest(str(staging / MANIFEST_NAME))
        manifest_bytes = (staging / MANIFEST_NAME).read_bytes()
        map_path = ROOT / "attacks" / "coverage_map.json"
        coverage_map_bytes = map_path.read_bytes() if map_path.is_file() else None
    else:
        attacks = copy.deepcopy(reuse_plan.attacks)
        manifest_bytes = reuse_plan.manifest_bytes
        coverage_map_bytes = reuse_plan.coverage_map_bytes
        (staging / MANIFEST_NAME).write_bytes(manifest_bytes)

    manifest = json.loads(manifest_bytes)
    versions = {row["coverage_map_version"] for row in manifest.values()
                if isinstance(row, dict) and row.get("coverage_map_version")}
    coverage_map = None
    if coverage_map_bytes is not None:
        map_data = json.loads(coverage_map_bytes)
        map_version = map_data.get("coverage_map_version")
        if not isinstance(map_version, str) or not map_version:
            raise ContractError("coverage map has no valid coverage_map_version")
        if versions and versions != {map_version}:
            raise ContractError("manifest and coverage map versions disagree")
        (staging / "coverage_map.json").write_bytes(coverage_map_bytes)
        coverage_map = {"path": "coverage_map.json", "version": map_version,
                        "sha256": hashlib.sha256(coverage_map_bytes).hexdigest()}
    elif versions:
        raise ContractError("manifest declares coverage but its coverage map is missing")

    planned_fingerprint = fingerprint_suite(baselines, attacks)
    standalone, derived = partition_attacks(attacks)
    planned_keys = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks
    ]

    if len(set(planned_keys)) != len(planned_keys):
        raise SelectionError("built suite contains duplicate case ids")
    known_attacks = {case.attack_id for case in attacks}
    if len(set(args.skip)) != len(args.skip) or set(args.skip) - known_attacks:
        raise SelectionError("--skip contains duplicate or unknown attack ids")

    selection: CaseSelection | None = None
    if args.case_set is not None:
        selection = load_case_set(args.case_set)
        if selection.suite_id != resolved.suite_id:
            raise SelectionError(
                f"case set {selection.case_set_id!r} is suite "
                f"{selection.suite_id!r}, but --suite {resolved.suite_id!r} was "
                "given. They conflict."
            )
        if resolved.evaluation_id is not None:
            declared = registry.evaluation(resolved.evaluation_id).case_set_id
            if declared is not None and declared != selection.case_set_id:
                raise SelectionError(
                    f"evaluation {resolved.evaluation_id!r} declares case set "
                    f"{declared!r}, but {selection.case_set_id!r} was supplied."
                )
        units = apply_case_set(selection, baselines, attacks)
        selected_keys = list(selection.order)
        skipped_keys = []
        limit_excluded = []
    else:
        kept_attacks, limit_excluded = select_attacks(attacks, args.limit)
        skip_set = set(args.skip)
        # Limit takes precedence: an attack outside the limited prefix is only
        # limit-excluded, even when its ID also appears in --skip.
        skipped_keys = [
            attack_key(a.attack_id) for a in kept_attacks if a.attack_id in skip_set
        ]
        selected_keys = [baseline_key(b.baseline_id) for b in baselines] + [
            attack_key(a.attack_id) for a in kept_attacks if a.attack_id not in skip_set
        ]
        units = default_send_order(baselines, kept_attacks)

    accounted = set(selected_keys) | set(skipped_keys) | set(limit_excluded)
    deselected = [key for key in planned_keys if key not in accounted]

    if reuse_plan is not None and (
            selected_keys != reuse_plan.selected_keys
            or skipped_keys != reuse_plan.skipped_keys
            or limit_excluded != reuse_plan.limit_excluded
            or (selection.source_sha256 if selection else None) != reuse_plan.selection_sha256):
        raise SelectionError("paired runs must use the identical selection and order")
    model_spec = registry.model_for(resolved.target_id)
    return RunPlan(
        resolved=resolved,
        build_identity=build_identity,
        manifest_bytes=manifest_bytes,
        coverage_map_bytes=coverage_map_bytes,
        coverage_map=coverage_map,
        baselines=baselines,
        attacks=attacks,
        planned_fingerprint=planned_fingerprint,
        planned_keys=planned_keys,
        units=units,
        selected_keys=selected_keys,
        skipped_keys=skipped_keys,
        limit_excluded=limit_excluded,
        deselected=deselected,
        selection=selection,
        # The file's own bytes, or null when this run used no selection file.
        selection_sha256=selection.source_sha256 if selection else None,
        selected_order_sha256=fingerprint_selection(
            selected_keys,
            case_set_id=selection.case_set_id if selection else None,
            suite_id=resolved.suite_id,
        ),
        baseline_source={
            "path": baseline_rel,
            "sha256": sha256_file(baseline_path),
        },
        model={
            "model_id": model_spec.model_id,
            "revision": model_spec.revision,
            "tokenizer_id": model_spec.tokenizer_id,
            "tokenizer_revision": model_spec.tokenizer_revision,
            "labels": list(model_spec.labels),
            "max_sequence_length": model_spec.max_sequence_length,
        },
        registry_source={
            "registry_version": registry.registry_version,
            "path": str(Path(registry.source_path).name),
            "sha256": registry.source_sha256,
        },
        tokenizer=tokenizer_meta,
        suite_sizes={
            "baselines": len(baselines),
            "attacks": len(attacks),
            "standalone_attacks": len(standalone),
            "derived_attacks": len(derived),
            "total_cases": len(baselines) + len(attacks),
            "boundary_source": "approximate" if args.no_tokenizer else "tokenizer",
            "max_tokens": max_tokens,
        },
    )


def main(
    argv: Sequence[str] | None = None, *, reuse_plan: RunPlan | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Legacy file names stay legacy. A run that names its target uses the
    # target-scoped names the Stage 3 layout expects
    # (tests/fixtures/stage3/runs/<evaluation>/<target_id>/), so two targets of one
    # evaluation write into their own directories without a version suffix
    # colliding -- sentiment_v1 and emotion_v1 are both "v1".
    target_scoped = args.target_id is not None
    results_path = out_dir / ("results.jsonl" if target_scoped else f"results_{args.version}.jsonl")
    meta_path = out_dir / ("run_meta.json" if target_scoped else f"run_meta_{args.version}.json")
    manifest_path = out_dir / MANIFEST_NAME
    selection_path = out_dir / SELECTION_NAME

    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    print(f"run       {run_id}")
    exit_code = 0
    writer = None
    manifest_sha = None
    runner = None
    termination = TERM_ERROR
    plan = None

    try:
        # Everything up to and including the preflight happens against a staging
        # directory inside the output directory. Nothing already published is
        # replaced until the endpoint has answered, so a readiness failure never
        # destroys the previous successful run's evidence.
        with tempfile.TemporaryDirectory(prefix=".runner-", dir=out_dir) as staging_name:
            staging = Path(staging_name)
            try:
                plan = plan_run(args, out_dir, staging, reuse_plan=reuse_plan)
            except (ContractError, ValueError, OSError) as exc:
                print(f"\nconfiguration error: {exc}", file=sys.stderr)
                print("No cases were sent; previous run artifacts were preserved.",
                      file=sys.stderr)
                return 2

            resolved = plan.resolved
            sizes = plan.suite_sizes
            print(f"target    {resolved.target_id} ({resolved.version}, task "
                  f"{resolved.task_id}, suite {resolved.suite_id}) via {resolved.resolved_from}")
            print(f"url       {args.target}")
            print(f"baseline  {plan.baseline_source['path']}  "
                  f"sha256 {plan.baseline_source['sha256'][:16]}")
            print(f"suite     {sizes['baselines']} baselines + {sizes['attacks']} attacks "
                  f"= {sizes['total_cases']} planned")
            print(f"sending   {len(plan.selected_keys)} cases"
                  + (f" (--limit {args.limit})" if args.limit is not None else "")
                  + (f", skipping {len(args.skip)}" if args.skip else "")
                  + (f" (case set {plan.selection.case_set_id})" if plan.selection else ""))
            print(f"planned   fingerprint {plan.planned_fingerprint[:16]}")
            print(f"selection fingerprint {plan.selected_order_sha256[:16]}"
                  + (f"  (case set file {plan.selection_sha256[:16]})"
                     if plan.selection_sha256 else ""))
            print(f"out       {results_path}")
            print()

            def progress(result: RunResult) -> None:
                status = result.status_code if result.status_code is not None else "no response"
                print(f"  {describe(result):<64} {str(status):>12} {result.latency_ms:>9.1f} ms "
                      f"{result.latency_band}", flush=True)

            runner = Runner(
                target=args.target,
                version=resolved.version,
                writer=None,
                predict_path=args.predict_path,
                health_path=args.health_path,
                timeout=args.timeout,
                health_timeout=args.health_timeout,
                skip=args.skip,
                on_record=progress,
                target_id=resolved.target_id,
                suite_id=resolved.suite_id,
            )
            runner.skipped = plan.skipped_keys

            staged_manifest = staging / MANIFEST_NAME
            manifest_sha = sha256_file(staged_manifest)
            if plan.selection is not None:
                selection_bytes = Path(plan.selection.source_path).read_bytes()
                if hashlib.sha256(selection_bytes).hexdigest() != plan.selection.source_sha256:
                    print("case selection changed during planning; no cases sent", file=sys.stderr)
                    return 2
                (staging / SELECTION_NAME).write_bytes(selection_bytes)
            if not runner.preflight():
                print(f"the endpoint at {args.target} is not answering {args.health_path}.")
                print("No cases were sent; previous run artifacts were preserved.")
                print("Start it, or check --target and --health-path.")
                return 2
            staged_manifest.replace(manifest_path)
            (staging / "registry.json").replace(out_dir / "registry.json")
            if plan.coverage_map is not None:
                (staging / "coverage_map.json").replace(out_dir / "coverage_map.json")
            else:
                (out_dir / "coverage_map.json").unlink(missing_ok=True)
            if plan.selection is not None:
                (staging / SELECTION_NAME).replace(selection_path)
            else:
                selection_path.unlink(missing_ok=True)

        writer = ResultWriter(results_path)
        runner.writer = writer
        print(f"manifest  {manifest_path}  sha256 {manifest_sha[:16]}")
        try:
            runner.run_ordered(plan.units, reset_skipped=False)
            if runner.counts["serialization_errors"]:
                termination = TERM_ERROR
                exit_code = 2
            else:
                termination = TERM_LIMIT if args.limit is not None else TERM_COMPLETED
        except EndpointDied as died:
            termination = TERM_HEALTH
            exit_code = 1
            print()
            print("=" * 72)
            print("THE ENDPOINT STOPPED ANSWERING /health")
            print(f"  killed by: {died.describe}")
            print(f"  status returned: {died.result.status_code}")
            print(f"  recorded as the last row in {results_path}")
            print()
            print("  Stopping here: everything after a dead endpoint is a")
            print("  connection error carrying no information.")
            if died.result.attack_id:
                print(f"  Re-run with --skip {died.result.attack_id} for a complete run.")
            else:
                print(f"  This was a clean baseline ({died.result.baseline_id}), not an")
                print("  attack, so there is nothing to skip. Restart the endpoint.")
            print("=" * 72)
    except KeyboardInterrupt:
        termination = TERM_INTERRUPTED
        exit_code = 130
        print("\nRun interrupted; completed rows have been preserved.", file=sys.stderr)
    except Exception as exc:                      # noqa: BLE001
        termination = TERM_ERROR
        exit_code = 3
        print(f"\nthe run errored: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    finally:
        try:
            if runner is not None:
                runner.close()
        finally:
            # A preflight failure has no new result file and must not replace
            # the metadata describing the previous invocation.
            if writer is not None and plan is not None:
                writer.close()
                resolved = plan.resolved
                meta = build_meta(
                    run_id=run_id,
                    version=resolved.version,
                    started_at=started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    is_smoke=args.limit is not None,
                    termination_reason=termination,
                    planned_fingerprint=plan.planned_fingerprint,
                    manifest_sha256=manifest_sha,
                    manifest_path=str(manifest_path),
                    target=args.target,
                    planned=plan.planned_keys,
                    selected=plan.selected_keys,
                    completed=runner.completed,
                    skipped=plan.skipped_keys,
                    limit_excluded=plan.limit_excluded,
                    deselected=plan.deselected,
                    limit=args.limit,
                    counts=runner.counts,
                    suite_sizes=plan.suite_sizes,
                    request_timeout=runner.timeout,
                    health_timeout=runner.health_timeout,
                    target_id=resolved.target_id,
                    suite_id=resolved.suite_id,
                    task_id=resolved.task_id,
                    evaluation_id=resolved.evaluation_id,
                    evaluation_run_id=args.parent_run_id,
                    case_set_id=plan.selection.case_set_id if plan.selection else None,
                    model=plan.model,
                    baseline_source=plan.baseline_source,
                    registry_source=plan.registry_source,
                    coverage_map=plan.coverage_map,
                    case_set=plan.selection.describe() if plan.selection else None,
                    tokenizer=plan.tokenizer,
                    selection_sha256=plan.selection_sha256,
                    selected_order_sha256=plan.selected_order_sha256,
                    results_sha256=sha256_file(results_path) if results_path.exists() else None,
                    provenance=code_provenance(),
                    resolved_from=resolved.resolved_from,
                )
                write_meta(meta_path, meta)
                coverage = meta["coverage"]
                print()
                print(f"recorded  {writer.count} rows to {results_path}")
                print(f"coverage  {coverage['completed']}/{coverage['planned']} "
                      f"(rate {coverage['coverage_rate']:.4f}), {coverage['missing']} missing, "
                      f"{coverage['skipped']} skipped, {coverage['limit_excluded']} limit-excluded, "
                      f"{coverage['deselected']} not selected")
                print(f"meta      {meta_path}  termination {termination}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
