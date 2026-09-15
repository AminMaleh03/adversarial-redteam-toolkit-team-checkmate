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
import hashlib
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
from baseline.load import load_baseline  # noqa: E402
from contract import AttackCase, BaselineCase, ContractError, RunResult  # noqa: E402
from endpoint.targets import TargetConfigError, load_registry  # noqa: E402

# Model-free: endpoint.targets never imports transformers/torch, so this import is
# free even for --help and offline tests. Loaded once, lazily, the first time a CLI
# invocation actually needs it -- see resolve_target() and _find_evaluation_for().
_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


CASE_SETS_DIR = Path(__file__).resolve().parent.parent / "analysis" / "case_sets"

DEFAULT_OUT = "results"
MANIFEST_NAME = "manifest.json"        # pinned by Ahsan. Lamei's integration
                                       # notes say attack_manifest.json; if the
                                       # analysis reads that name, change it here.
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
# Building the request itself failed, before any bytes existed to hash -- distinct
# from a transport failure, which happens AFTER a real prepared body exists.
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

# Legacy --version -> registry target_id, the "explicit emotion default" that keeps
# every old `--target URL --version v1|v2` invocation working unchanged.
LEGACY_VERSION_TARGET_ID = {"v1": "emotion_v1", "v2": "emotion_v2"}


# --------------------------------------------------------------------------
# target/suite resolution (Stage 3: target-aware runs)
# --------------------------------------------------------------------------


class RunnerConfigError(ValueError):
    """Raised for a target/suite/case-set configuration the CLI must reject."""


def resolve_target(
    target: str | None,
    version: str | None,
    target_id: str | None,
    registry,
) -> tuple[str, str, str]:
    """Resolve (target_url, version, target_id) from the CLI flags actually given.

    Two, and only two, supported shapes:

      * legacy:     --target URL --version v1|v2, no --target-id.
                    target_id is derived as the "explicit emotion default"
                    (emotion_v1 / emotion_v2) -- never inferred from the URL.
      * target-aware: --target-id TARGET_ID, no --target and no --version.
                    The URL is derived from the registry's own loopback port --
                    never taken from the CLI. This is the only way an
                    arbitrary/public target could sneak in, so it is refused
                    entirely: a target-aware run only ever talks to a trusted
                    registry target on 127.0.0.1.

    Mixing the two (e.g. --target-id together with --target or --version) is a
    configuration error, not a "which one wins" situation.
    """
    if target_id is not None:
        if target is not None or version is not None:
            raise RunnerConfigError(
                "--target-id cannot be combined with --target or --version; "
                "--target-id derives both from the trusted registry."
            )
        spec = registry.target(target_id)
        resolved_url = f"http://127.0.0.1:{spec.port}"
        return resolved_url, spec.version, target_id

    if target is None or version is None:
        raise RunnerConfigError(
            "either pass --target-id, or pass both --target and --version."
        )
    return target, version, LEGACY_VERSION_TARGET_ID[version]


def _find_evaluation_for(registry, target_id: str, suite_id: str):
    """The one EvaluationSpec that runs `suite_id` against `target_id`.

    Used only to resolve the baseline file this run must use -- never to change
    which suite is executed or to introduce a third suite name. A bounded CI
    selection is still `suite_id == "core"`; there is no separate "ci" suite here.
    """
    task_id = registry.target(target_id).task_id
    matches = [
        spec
        for spec in registry.evaluations.values()
        if spec.task_id == task_id
        and spec.suite_id == suite_id
        and target_id in spec.target_ids
    ]
    if not matches:
        raise RunnerConfigError(
            f"no evaluation is configured for target {target_id!r} suite {suite_id!r}"
        )
    if len(matches) > 1:
        raise RunnerConfigError(
            f"ambiguous evaluation configuration for target {target_id!r} suite "
            f"{suite_id!r}: {[m.evaluation_id for m in matches]}"
        )
    return matches[0]


def resolve_baseline_path(registry, target_id: str, suite_id: str) -> Path:
    """The baseline file this (target, suite) run must load, per the registry.

    Core uses the task's default baseline file. OCES uses the evaluation-level
    override (a frozen seed file), never the task's core baseline -- resolving
    this correctly is what lets the recorded baseline hash mean something.
    """
    evaluation = _find_evaluation_for(registry, target_id, suite_id)
    relative = registry.baseline_file_for(evaluation.evaluation_id)
    return (Path(__file__).resolve().parent.parent / relative)


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
# building the suite
# --------------------------------------------------------------------------


def build_token_counter(target_id: str = "emotion_v2") -> tuple[Callable[[str], int], int]:
    """The real tokenizer for `target_id`, so boundary cases land on the true token limit.

    Imported inside the function rather than at module scope: loading a tokenizer
    (and, for the legacy emotion path, a whole model) is not free, and callers that
    only need --help or offline tests must not pay for it.

    Emotion targets keep using the existing, unchanged `endpoint.model` import --
    zero behavior change to a path this task must leave untouched. Every other
    target (sentiment_v1, and any future registry target) loads its tokenizer
    through the registry via `endpoint.loader.load_tokenizer_for_target`, which
    loads ONLY the tokenizer, never the full model -- counting tokens for a
    sentiment run must not accidentally load sentiment weights here, any more than
    it may accidentally load the emotion model's.

    truncation=False is required. Silent truncation would neutralise two whole
    attack categories, and this is the only place outside the endpoint folder
    that calls the tokenizer directly.
    """
    if target_id in LEGACY_VERSION_TARGET_ID.values():
        from endpoint.model import MAX_SEQUENCE_LENGTH, tokenizer

        max_tokens = int(MAX_SEQUENCE_LENGTH)
    else:
        from endpoint.loader import load_tokenizer_for_target

        tokenizer, max_tokens = load_tokenizer_for_target(target_id)
        max_tokens = int(max_tokens)

    if not MIN_PLAUSIBLE_MAX_TOKENS <= max_tokens <= MAX_PLAUSIBLE_MAX_TOKENS:
        raise RuntimeError(
            f"target {target_id!r}'s max_sequence_length is {max_tokens}, which is "
            "not a plausible token limit. Hugging Face reports a huge sentinel when "
            "a tokenizer config omits model_max_length. Boundary cases built around "
            "that would be meaningless and the manifest would record them as exact."
        )

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    return count_tokens, max_tokens


def build_suite_once(
    baselines: Sequence[BaselineCase],
    token_counter: Callable[[str], int] | None,
    max_tokens: int | None,
) -> list[AttackCase]:
    """Build the attack suite exactly once.

    Once matters. library.write_manifest dumps every case built so far, so a
    throwaway build -- counting cases, say -- would stamp a second entry for
    the same attack_id into the sidecar, and a build without the tokenizer
    would stamp approximate boundaries into it. The analysis would then be
    joining results against an oracle describing different cases.
    """
    return library.build_suite(
        list(baselines), token_counter=token_counter, max_tokens=max_tokens
    )


def partition_attacks(
    attacks: Sequence[AttackCase],
) -> tuple[list[AttackCase], list[AttackCase]]:
    """Standalone first, then derived, each keeping the library's order."""
    standalone = [case for case in attacks if case.baseline_id is None]
    derived = [case for case in attacks if case.baseline_id is not None]
    return standalone, derived


# --------------------------------------------------------------------------
# frozen case sets (e.g. CI's ci_core_v1)
# --------------------------------------------------------------------------


def load_case_set(case_set_id: str, directory: Path = CASE_SETS_DIR) -> dict:
    """Read a frozen selection like analysis/case_sets/ci_core_v1.json.

    Only reads and returns the raw dict -- ownership of the file's content is
    Khalid's (analysis/case_sets/**); this module only ever consumes it.
    """
    path = directory / f"{case_set_id}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RunnerConfigError(f"case set {case_set_id!r} not found at {path}") from None
    except json.JSONDecodeError as exc:
        raise RunnerConfigError(f"case set {case_set_id!r} at {path} is not valid JSON: {exc}") from None
    if raw.get("case_set_id") != case_set_id:
        raise RunnerConfigError(
            f"case set file {path} declares case_set_id "
            f"{raw.get('case_set_id')!r}, expected {case_set_id!r}"
        )
    return raw


def _reject_bad_id_list(ids: object, where: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise RunnerConfigError(f"case set {where} must be a list of strings")
    if not ids and not allow_empty:
        raise RunnerConfigError(f"case set {where} must not be empty")
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in ids:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise RunnerConfigError(f"case set {where} has duplicate ids: {sorted(set(duplicates))}")
    return ids


def apply_case_set(
    case_set: dict,
    suite_id: str,
    baselines: Sequence[BaselineCase],
    attacks: Sequence[AttackCase],
) -> tuple[list[BaselineCase], list[AttackCase], list[str]]:
    """Restrict the built suite to exactly a frozen selection, in its exact order.

    Reject unknown, duplicate, empty, incomplete or conflicting selections outright
    rather than silently dropping anything -- a case set naming an id the built suite
    doesn't have is a configuration bug (stale freeze, wrong baseline file, wrong
    suite), not something to skip quietly.

    Returns (selected_baselines, selected_attacks, excluded_keys). excluded_keys
    covers every planned case NOT in the selection, in planned order -- this is what
    main() folds into limit_excluded-style bookkeeping for a bounded run.
    """
    declared_suite = case_set.get("suite_id")
    if declared_suite != suite_id:
        raise RunnerConfigError(
            f"case set {case_set.get('case_set_id')!r} is for suite "
            f"{declared_suite!r}, not the requested suite {suite_id!r}"
        )

    baseline_ids = _reject_bad_id_list(case_set.get("baseline_ids"), "baseline_ids")
    standalone_ids = _reject_bad_id_list(
        case_set.get("standalone_attack_ids"), "standalone_attack_ids", allow_empty=True
    )
    derived_ids = _reject_bad_id_list(
        case_set.get("derived_attack_ids"), "derived_attack_ids", allow_empty=True
    )
    if not standalone_ids and not derived_ids:
        raise RunnerConfigError(
            "case set selects no attacks at all (standalone_attack_ids and "
            "derived_attack_ids are both empty)"
        )

    attack_ids = standalone_ids + derived_ids
    overlap = set(standalone_ids) & set(derived_ids)
    if overlap:
        raise RunnerConfigError(
            f"case set lists {sorted(overlap)} in both standalone_attack_ids and "
            "derived_attack_ids"
        )

    baseline_by_id = {b.baseline_id: b for b in baselines}
    attack_by_id = {a.attack_id: a for a in attacks}

    missing_baselines = [bid for bid in baseline_ids if bid not in baseline_by_id]
    if missing_baselines:
        raise RunnerConfigError(
            f"case set references baseline ids not present in the built suite: "
            f"{missing_baselines}"
        )
    missing_attacks = [aid for aid in attack_ids if aid not in attack_by_id]
    if missing_attacks:
        raise RunnerConfigError(
            f"case set references attack ids not present in the built suite: "
            f"{missing_attacks}"
        )

    selected_baselines = [baseline_by_id[bid] for bid in baseline_ids]
    selected_attacks = [attack_by_id[aid] for aid in attack_ids]

    selected_baseline_id_set = set(baseline_ids)
    orphaned = [
        case.attack_id
        for case in selected_attacks
        if case.baseline_id is not None and case.baseline_id not in selected_baseline_id_set
    ]
    if orphaned:
        raise RunnerConfigError(
            f"case set selects derived attacks whose baseline is not itself "
            f"selected: {orphaned}"
        )

    selected_attack_id_set = set(attack_ids)
    excluded_keys = [
        baseline_key(b.baseline_id) for b in baselines if b.baseline_id not in selected_baseline_id_set
    ] + [
        attack_key(a.attack_id) for a in attacks if a.attack_id not in selected_attack_id_set
    ]
    return selected_baselines, selected_attacks, excluded_keys


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
        # New Stage 3 identity, stamped on every row. Blank stays supported (an
        # existing direct `Runner(...)` construction, e.g. in older tests, still
        # works and produces historical-style blank fields) -- a real CLI run
        # always sets both explicitly. See RunResult.target_id/suite_id in
        # contract.py: blank means historical, never an inferred emotion default.
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

    async def _send_prepared(self, request: httpx.Request, timeout: float) -> httpx.Response:
        """Send an already-built request. Same outer-deadline reasoning as _request.

        HTTPX's per-request timeout lives on the request itself (set at build time,
        via extensions), not as a `send()` keyword -- `AsyncClient.send()` takes no
        `timeout` argument. `asyncio.timeout` is still the real outer deadline here;
        this just has to match HTTPX's own expectations for where timeout is set.
        """
        async with asyncio.timeout(timeout):
            return await self.client.send(request)

    # -- sending ------------------------------------------------------------

    def _build_request(self, case: AttackCase | None, text: str | None) -> httpx.Request:
        """Build the exact request HTTPX will send, without sending it.

        For a raw case, the body is used verbatim -- these bytes may be
        deliberately invalid UTF-8, and the headers are part of the test. Using
        json= here, or adding a header, would repair the very thing being tested.
        For an ordinary case, HTTPX's own json= serialization produces the body;
        this is intentionally not hand-rolled with json.dumps, so the bytes we
        hash are the exact bytes HTTPX itself would put on the wire.

        No network I/O happens here -- building a request is synchronous and
        local. A failure in this method means serialization itself failed,
        before any prepared body existed to capture.
        """
        if case is not None and case.is_raw:
            body = case.raw_body
            if isinstance(body, str):
                body = body.encode("utf-8")
            elif body is None:
                body = b""
            return self.client.build_request(
                "POST", self.predict_url, content=body, headers=dict(case.raw_headers or {}),
                timeout=self.timeout,
            )
        return self.client.build_request(
            "POST", self.predict_url, json={"text": text}, timeout=self.timeout
        )

    def send(self, case: AttackCase | None, text: str | None) -> dict:
        """One request. No retry: a connection failure is recorded as one.

        Attack requests are never retried, because a connection-level failure
        is one of the three outcomes the analysis counts separately, and a
        retry would hide it. The health ping does retry once, for a reason
        specific to the ping -- see health_ok.

        Body evidence (request_body_bytes / request_body_sha256) is captured
        from the ACTUAL prepared request -- never recomputed independently, and
        never substituted with a character count. It is present in every
        returned outcome that reaches the try block below, including ones where
        the transport subsequently fails: a request that got no response still
        has a known attempted body. Only a serialization failure (caught before
        the try block) leaves both fields None, because no bytes ever existed.
        """
        started = self.clock()
        try:
            request = self._build_request(case, text)
        except Exception as exc:                      # noqa: BLE001
            latency_ms = (self.clock() - started) * 1000.0
            return {
                "status_code": None,
                "response_body": "",
                "error": f"{ERR_SERIALIZATION}: {type(exc).__name__}: {exc}",
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                "request_body_bytes": None,
                "request_body_sha256": None,
            }

        prepared_body = request.content
        request_body_bytes = len(prepared_body)
        request_body_sha256 = hashlib.sha256(prepared_body).hexdigest()

        try:
            response = self._async_runner.run(self._send_prepared(request, self.timeout))

            latency_ms = (self.clock() - started) * 1000.0
            if response.status_code >= 500:
                self.counts["server_errors_5xx"] += 1
            return {
                "status_code": response.status_code,
                "response_body": response.text,
                "error": None,
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                "request_body_bytes": request_body_bytes,
                "request_body_sha256": request_body_sha256,
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
                "request_body_bytes": request_body_bytes,
                "request_body_sha256": request_body_sha256,
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
                "request_body_bytes": request_body_bytes,
                "request_body_sha256": request_body_sha256,
            }

        except httpx.HTTPError as exc:
            latency_ms = (self.clock() - started) * 1000.0
            return {
                "status_code": None,
                "response_body": "",
                "error": f"{ERR_TRANSPORT}: {type(exc).__name__}: {exc}",
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
                "request_body_bytes": request_body_bytes,
                "request_body_sha256": request_body_sha256,
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
        for baseline in baselines:
            self.send_baseline(baseline)
        standalone, derived = partition_attacks(attacks)
        for case in standalone:
            self.send_attack(case)
        for case in derived:
            self.send_attack(case)


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
    suite_sizes: dict,
    request_timeout: float = REQUEST_TIMEOUT,
    health_timeout: float = HEALTH_TIMEOUT,
    target_id: str = "",
    suite_id: str = "",
    case_set_id: str | None = None,
    baseline_file: str = "",
    baseline_file_sha256: str | None = None,
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
        "version": version,
        "target_id": target_id,
        "suite_id": suite_id,
        "case_set_id": case_set_id,
        "target": target,
        "started_at": started_at,
        "ended_at": ended_at,
        "run_type": "smoke" if is_smoke else "full",
        "limit": limit,
        "termination_reason": termination_reason,
        "fingerprints": {
            "planned_suite_sha256": planned_fingerprint,
            "manifest_sha256": manifest_sha256,
            "manifest_path": manifest_path,
            "baseline_file": baseline_file,
            "baseline_file_sha256": baseline_file_sha256,
        },
        "suite": suite_sizes,
        "coverage": {
            "planned": planned_count,
            "skipped": len(skipped),
            "limit_excluded": len(limit_excluded),
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
    #
    # --target/--version stay optional at the argparse level (not required=True
    # any more) because they are now one of two valid shapes, the other being
    # --target-id alone -- see resolve_target(). Which shape was actually given
    # is validated after parsing, in main(), so the error message can name the
    # real problem (missing one of a pair, or a conflicting combination)
    # instead of argparse's generic "required" message.
    parser.add_argument("--target", default=None, help="base URL of the endpoint (legacy mode)")
    parser.add_argument("--version", default=None, choices=("v1", "v2"), help="(legacy mode)")
    parser.add_argument(
        "--target-id",
        default=None,
        choices=sorted(_registry().targets),
        help="a trusted registry target; derives --target and --version. "
        "Cannot be combined with --target or --version.",
    )
    parser.add_argument(
        "--suite", choices=("core", "oces"), default="core",
        help="which suite to run (default core). oces is not runnable until its "
        "case/rule freeze lands.",
    )
    parser.add_argument(
        "--case-set", default=None, metavar="CASE_SET_ID",
        help="restrict the run to a frozen selection from analysis/case_sets/. "
        "Cannot be combined with --limit.",
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    registry = _registry()

    # --- resolve which target/version/suite this invocation actually means,
    # and reject any invalid or conflicting combination -- all before any file
    # or network access, same as the existing type-level CLI validation above.
    try:
        target, version, target_id = resolve_target(args.target, args.version, args.target_id, registry)
    except (RunnerConfigError, ContractError) as exc:
        parser.error(str(exc))

    if args.suite == "oces":
        parser.error(
            "--suite oces is not runnable yet: OCES case/rule generation has not "
            "landed. See docs/stage3/tasks/task_2_rayyan.md."
        )
    if args.case_set is not None and args.limit is not None:
        parser.error("--case-set cannot be combined with --limit; the case set is the selection.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / f"results_{version}.jsonl"
    meta_path = out_dir / f"run_meta_{version}.json"
    manifest_path = out_dir / MANIFEST_NAME

    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Baseline file resolved through the registry for every target, including the
    # legacy emotion ones -- it resolves to the exact same file they always used,
    # so this is not a behavior change, just a single code path for both.
    try:
        baseline_path = resolve_baseline_path(registry, target_id, args.suite)
    except (RunnerConfigError, ContractError) as exc:
        parser.error(str(exc))
    try:
        # File order from the loader, then sorted by id. Sorting means the
        # fingerprint changes only when the content changes, not when the
        # baseline file happens to be written in a different order.
        baselines = sorted(load_baseline(baseline_path), key=lambda b: b.baseline_id)
    except FileNotFoundError:
        print(
            f"cannot run target {target_id!r} suite {args.suite!r}: baseline file "
            f"not found at {baseline_path}. This evaluation's baseline has not been "
            "produced yet.",
            file=sys.stderr,
        )
        return 2
    baseline_file_sha256 = sha256_file(baseline_path)

    if args.no_tokenizer:
        token_counter, max_tokens = None, None
        print("WARNING: approximate length boundaries, for testing only")
    else:
        token_counter, max_tokens = build_token_counter(target_id)

    attacks = build_suite_once(baselines, token_counter, max_tokens)

    planned_fingerprint = fingerprint_suite(baselines, attacks)
    standalone, derived = partition_attacks(attacks)

    planned_keys = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks
    ]

    if args.case_set is not None:
        case_set = load_case_set(args.case_set)
        try:
            run_baselines, kept_attacks, limit_excluded = apply_case_set(
                case_set, args.suite, baselines, attacks
            )
        except RunnerConfigError as exc:
            parser.error(str(exc))
    else:
        run_baselines = baselines
        kept_attacks, limit_excluded = select_attacks(attacks, args.limit)

    skip_set = set(args.skip)
    # Limit/case-set takes precedence: a case outside the selected set is only
    # limit-excluded, even when its ID also appears in --skip.
    skipped_keys = [attack_key(a.attack_id) for a in kept_attacks if a.attack_id in skip_set]
    selected_keys = [baseline_key(b.baseline_id) for b in run_baselines] + [
        attack_key(a.attack_id) for a in kept_attacks if a.attack_id not in skip_set
    ]

    suite_sizes = {
        "baselines": len(baselines),
        "attacks": len(attacks),
        "standalone_attacks": len(standalone),
        "derived_attacks": len(derived),
        "total_cases": len(baselines) + len(attacks),
        "boundary_source": "approximate" if token_counter is None else "tokenizer",
        "max_tokens": max_tokens,
    }

    print(f"run       {run_id}  ({version})  target_id={target_id}  suite={args.suite}"
          + (f"  case_set={args.case_set}" if args.case_set else ""))
    print(f"target    {target}")
    print(f"suite     {suite_sizes['baselines']} baselines + {suite_sizes['attacks']} attacks "
          f"= {suite_sizes['total_cases']} planned")
    print(f"sending   {len(selected_keys)} cases"
          + (f" (--limit {args.limit})" if args.limit is not None else "")
          + (f", skipping {len(args.skip)}" if args.skip else ""))
    print(f"planned   fingerprint {planned_fingerprint[:16]}")
    print(f"out       {results_path}")
    print()

    def progress(result: RunResult) -> None:
        status = result.status_code if result.status_code is not None else "no response"
        print(f"  {describe(result):<64} {str(status):>12} {result.latency_ms:>9.1f} ms "
              f"{result.latency_band}", flush=True)

    # Success is assigned only after the selected plan actually finishes.
    termination = TERM_ERROR
    exit_code = 0
    writer = None
    manifest_sha = None
    runner = Runner(
        target=target,
        version=version,
        writer=writer,
        predict_path=args.predict_path,
        health_path=args.health_path,
        timeout=args.timeout,
        health_timeout=args.health_timeout,
        skip=args.skip,
        on_record=progress,
        target_id=target_id,
        suite_id=args.suite,
    )
    runner.skipped = skipped_keys

    try:
        # Register expectations once, before even the preflight health request.
        # Stage them in this output directory so a failed preflight cannot
        # replace an earlier run's manifest, results or metadata. Publication
        # happens before the first prediction, preserving the oracle boundary.
        with tempfile.TemporaryDirectory(prefix=".runner-", dir=out_dir) as staging:
            staged_manifest = Path(staging) / MANIFEST_NAME
            library.write_manifest(str(staged_manifest))
            manifest_sha = sha256_file(staged_manifest)
            if not runner.preflight():
                print(f"the endpoint at {target} is not answering {args.health_path}.")
                print("No cases were sent; previous run artifacts were preserved.")
                print("Start it, or check --target and --health-path.")
                return 2
            staged_manifest.replace(manifest_path)

        writer = ResultWriter(results_path)
        runner.writer = writer
        print(f"manifest  {manifest_path}  sha256 {manifest_sha[:16]}")
        try:
            runner.run(run_baselines, kept_attacks)
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
            runner.close()
        finally:
            # A preflight failure has no new result file and must not replace
            # the metadata describing the previous invocation.
            if writer is not None:
                writer.close()
                meta = build_meta(
                    run_id=run_id,
                    version=version,
                    started_at=started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    is_smoke=args.limit is not None,
                    termination_reason=termination,
                    planned_fingerprint=planned_fingerprint,
                    manifest_sha256=manifest_sha,
                    manifest_path=str(manifest_path),
                    target=target,
                    planned=planned_keys,
                    selected=selected_keys,
                    completed=runner.completed,
                    skipped=skipped_keys,
                    limit_excluded=limit_excluded,
                    limit=args.limit,
                    counts=runner.counts,
                    suite_sizes=suite_sizes,
                    request_timeout=runner.timeout,
                    health_timeout=runner.health_timeout,
                    target_id=target_id,
                    suite_id=args.suite,
                    case_set_id=args.case_set,
                    baseline_file=str(baseline_path),
                    baseline_file_sha256=baseline_file_sha256,
                )
                write_meta(meta_path, meta)
                coverage = meta["coverage"]
                print()
                print(f"recorded  {writer.count} rows to {results_path}")
                print(f"coverage  {coverage['completed']}/{coverage['planned']} "
                      f"(rate {coverage['coverage_rate']:.4f}), {coverage['missing']} missing, "
                      f"{coverage['skipped']} skipped, {coverage['limit_excluded']} limit-excluded")
                print(f"meta      {meta_path}  termination {termination}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())