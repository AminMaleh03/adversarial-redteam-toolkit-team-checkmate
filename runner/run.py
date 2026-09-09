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
from contract import AttackCase, BaselineCase, RunResult  # noqa: E402

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
# three failure kinds without guessing from free text.
ERR_CONNECTION = "connection_error"
ERR_TIMEOUT = "timeout"
ERR_TRANSPORT = "transport_error"

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


def build_token_counter() -> tuple[Callable[[str], int], int]:
    """The real tokenizer, so boundary cases land on the true token limit.

    Imported inside the function rather than at module scope: endpoint.model
    loads the whole model at import time, and the tests must not pay for that.

    truncation=False is required. Silent truncation would neutralise two whole
    attack categories, and this is the only place outside the endpoint folder
    that calls the tokenizer directly.
    """
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
    ) -> None:
        if timeout != REQUEST_TIMEOUT:
            raise ValueError(f"request timeout must be {REQUEST_TIMEOUT} seconds")
        if not math.isfinite(health_timeout) or health_timeout <= 0:
            raise ValueError("health timeout must be finite and greater than zero")
        self.base = target.rstrip("/")
        self.version = version
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

    # -- sending ------------------------------------------------------------

    def send(self, case: AttackCase | None, text: str | None) -> dict:
        """One request. No retry: a connection failure is recorded as one.

        Attack requests are never retried, because a connection-level failure
        is one of the three outcomes the analysis counts separately, and a
        retry would hide it. The health ping does retry once, for a reason
        specific to the ping -- see health_ok.
        """
        started = self.clock()
        try:
            if case is not None and case.is_raw:
                body = case.raw_body
                if isinstance(body, str):
                    body = body.encode("utf-8")
                elif body is None:
                    body = b""
                # Verbatim. These bytes may be deliberately invalid UTF-8, and
                # the headers are part of the test. Using json= here, or adding
                # a header, would repair the very thing being tested.
                response = self._async_runner.run(self._request(
                    "POST", self.predict_url, self.timeout,
                    content=body,
                    headers=dict(case.raw_headers or {}),
                ))
            else:
                response = self._async_runner.run(self._request(
                    "POST", self.predict_url, self.timeout, json={"text": text}
                ))

            latency_ms = (self.clock() - started) * 1000.0
            if response.status_code >= 500:
                self.counts["server_errors_5xx"] += 1
            return {
                "status_code": response.status_code,
                "response_body": response.text,
                "error": None,
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
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
            }

        except httpx.HTTPError as exc:
            latency_ms = (self.clock() - started) * 1000.0
            return {
                "status_code": None,
                "response_body": "",
                "error": f"{ERR_TRANSPORT}: {type(exc).__name__}: {exc}",
                "latency_ms": round(latency_ms, 2),
                "latency_band": band_latency(latency_ms, timed_out=False),
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
    parser.add_argument("--target", required=True, help="base URL of the endpoint")
    parser.add_argument("--version", required=True, choices=("v1", "v2"))
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
    args = build_parser().parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / f"results_{args.version}.jsonl"
    meta_path = out_dir / f"run_meta_{args.version}.json"
    manifest_path = out_dir / MANIFEST_NAME

    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # File order from the loader, then sorted by id. Sorting means the
    # fingerprint changes only when the content changes, not when
    # baseline.json happens to be written in a different order.
    baselines = sorted(load_baseline(), key=lambda b: b.baseline_id)

    if args.no_tokenizer:
        token_counter, max_tokens = None, None
        print("WARNING: approximate length boundaries, for testing only")
    else:
        token_counter, max_tokens = build_token_counter()

    attacks = build_suite_once(baselines, token_counter, max_tokens)

    planned_fingerprint = fingerprint_suite(baselines, attacks)
    standalone, derived = partition_attacks(attacks)

    planned_keys = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks
    ]
    kept_attacks, limit_excluded = select_attacks(attacks, args.limit)
    skip_set = set(args.skip)
    # Limit takes precedence: an attack outside the limited prefix is only
    # limit-excluded, even when its ID also appears in --skip.
    skipped_keys = [attack_key(a.attack_id) for a in kept_attacks if a.attack_id in skip_set]
    selected_keys = [baseline_key(b.baseline_id) for b in baselines] + [
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

    print(f"run       {run_id}  ({args.version})")
    print(f"target    {args.target}")
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
        target=args.target,
        version=args.version,
        writer=writer,
        predict_path=args.predict_path,
        health_path=args.health_path,
        timeout=args.timeout,
        health_timeout=args.health_timeout,
        skip=args.skip,
        on_record=progress,
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
                print(f"the endpoint at {args.target} is not answering {args.health_path}.")
                print("No cases were sent; previous run artifacts were preserved.")
                print("Start it, or check --target and --health-path.")
                return 2
            staged_manifest.replace(manifest_path)

        writer = ResultWriter(results_path)
        runner.writer = writer
        print(f"manifest  {manifest_path}  sha256 {manifest_sha[:16]}")
        try:
            runner.run(baselines, kept_attacks)
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
                    version=args.version,
                    started_at=started_at,
                    ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    is_smoke=args.limit is not None,
                    termination_reason=termination,
                    planned_fingerprint=planned_fingerprint,
                    manifest_sha256=manifest_sha,
                    manifest_path=str(manifest_path),
                    target=args.target,
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
