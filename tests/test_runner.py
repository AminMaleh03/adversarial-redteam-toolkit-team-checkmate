"""Tests for the runner.

No network and no endpoint: httpx.MockTransport stands in for Rayyan's
service, so these run in under a second and can run on every push.

Two deliberate choices about scope.

Nothing here imports attacks, baseline or endpoint. Cases are built by hand
from contract.py, so a change in Lamei's generator or Khalid's baseline cannot
turn a runner bug into a passing test, or a working runner into a failing one.
The integration between them is checked by running the thing, not by mocking
it.

The clock is injected, so latency assertions are exact rather than dependent
on how busy the machine was. The 2-second band boundary is pinned to the value.

The repo has no conftest.py or pytest.ini, so the sys.path line below is how
this file finds contract.py. Run from the repo root: python -m pytest tests/
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest

from contract import AttackCase, BaselineCase
from endpoint.targets import load_registry
from runner import run as runner_module
from runner.run import (
    BAND_NORMAL,
    BAND_SLOW,
    BAND_TIMEOUT,
    ERR_CONNECTION,
    ERR_TIMEOUT,
    TERM_HEALTH,
    EndpointDied,
    ResultWriter,
    Runner,
    attack_key,
    band_latency,
    baseline_key,
    build_meta,
    fingerprint_suite,
    parse_prediction,
    partition_attacks,
    select_attacks,
    write_meta,
)

TARGET = "http://endpoint.test"


@pytest.fixture(autouse=True)
def close_runner_clients(monkeypatch):
    """Close the per-run event loop and client, including in assertion failures."""
    created = []
    original_init = Runner.__init__

    def track(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(Runner, "__init__", track)
    yield
    for runner in reversed(created):
        runner.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class FakeClock:
    """Advances only when read, so latency is whatever the test says it is."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def predict_response(label="joy", confidence=0.94) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "label": label,
            "confidence": confidence,
            "all_scores": {
                "joy": confidence, "neutral": 0.02, "anger": 0.01, "fear": 0.01,
                "sadness": 0.01, "surprise": 0.005, "disgust": 0.005,
            },
        },
    )


def ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    return predict_response()


def make_runner(tmp_path, handler=ok_handler, clock=None, skip=(), version="v1"):
    writer = ResultWriter(Path(tmp_path) / f"results_{version}.jsonl")
    runner = Runner(
        target=TARGET,
        version=version,
        writer=writer,
        transport=httpx.MockTransport(handler),
        clock=clock or FakeClock(),
        skip=skip,
    )
    return runner, writer


def read_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def baseline(bid="b01", text="i feel great today", label="joy") -> BaselineCase:
    return BaselineCase(baseline_id=bid, text=text, label=label, source="dataset")


def attack(aid="a01", **kwargs) -> AttackCase:
    fields = dict(
        attack_id=aid,
        baseline_id=None,
        category="malformed",
        original_text=None,
        attacked_text="i feel great today",
    )
    fields.update(kwargs)
    return AttackCase(**fields)


def suite(n_baselines=2, n_standalone=3, n_derived=2):
    """A miniature of the real suite: standalone first, then derived per baseline."""
    baselines = [baseline(f"b{i:02d}", f"sentence {i}") for i in range(1, n_baselines + 1)]
    attacks = [attack(f"s.malformed.{i:02d}") for i in range(1, n_standalone + 1)]
    for base in baselines:
        for i in range(1, n_derived + 1):
            attacks.append(
                attack(
                    f"{base.baseline_id}.encoding.{i:02d}",
                    baseline_id=base.baseline_id,
                    category="encoding",
                    original_text=base.text,
                    attacked_text=base.text.upper(),
                )
            )
    return baselines, attacks


# ==========================================================================
# 1. structured payloads go as JSON, raw payloads go verbatim
# ==========================================================================


def test_structured_payload_is_sent_as_json(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["content"] = request.content
        seen["content_type"] = request.headers.get("content-type")
        return predict_response()

    runner, writer = make_runner(tmp_path, handler)
    runner.send_attack(attack(attacked_text="hello there"))
    writer.close()

    assert json.loads(seen["content"]) == {"text": "hello there"}
    assert "application/json" in seen["content_type"]


def test_raw_body_and_headers_are_sent_untouched(tmp_path):
    """is_raw means send verbatim: no re-serialising, no added headers."""
    broken = b'{"text": "unterminated'
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["content"] = request.content
        seen["content_type"] = request.headers.get("content-type")
        return httpx.Response(422, text="unprocessable")

    runner, writer = make_runner(tmp_path, handler)
    runner.send_attack(
        attack(
            "malformed.truncated_json",
            is_raw=True,
            raw_body=broken,
            raw_headers={"content-type": "application/json"},
            attacked_text=None,
        )
    )
    writer.close()

    assert seen["content"] == broken, "the raw body was re-encoded"
    assert seen["content_type"] == "application/json"


def test_invalid_utf8_bytes_reach_the_wire_unchanged(tmp_path):
    """malformed.malformed_utf8 carries bytes that cannot be decoded.

    Any decode/encode round trip would repair them into something valid, and
    the test would then prove nothing.
    """
    payload = b'{"text": "caf\xff\xfe broken"}'
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["content"] = request.content
        return httpx.Response(400, text="bad encoding")

    runner, writer = make_runner(tmp_path, handler)
    runner.send_attack(
        attack("malformed.malformed_utf8", is_raw=True, raw_body=payload, attacked_text=None)
    )
    writer.close()

    assert seen["content"] == payload
    with pytest.raises(UnicodeDecodeError):
        payload.decode("utf-8")          # proves the bytes really are invalid


def test_raw_body_given_as_str_is_encoded_without_json_wrapping(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        assert request.content == b"not a json object at all"
        return httpx.Response(400, text="no")

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(
        attack("schema.wrong_top_level", is_raw=True, raw_body="not a json object at all")
    )
    writer.close()
    assert result.status_code == 400


# --------------------------------------------------------------------------
# request body evidence (request_body_bytes / request_body_sha256)
# --------------------------------------------------------------------------


def test_request_body_evidence_matches_the_actual_wire_bytes_for_json(tmp_path):
    import hashlib

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["content"] = request.content
        return predict_response()

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(attack(attacked_text="héllo wörld"))
    writer.close()

    assert result.request_body_bytes == len(seen["content"])
    assert result.request_body_sha256 == hashlib.sha256(seen["content"]).hexdigest()


def test_request_body_evidence_matches_the_actual_wire_bytes_for_raw_and_malformed(tmp_path):
    import hashlib

    payload = b'{"text": "caf\xff\xfe broken"}'
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["content"] = request.content
        return httpx.Response(400, text="bad encoding")

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(
        attack("malformed.malformed_utf8", is_raw=True, raw_body=payload, attacked_text=None)
    )
    writer.close()

    assert seen["content"] == payload
    assert result.request_body_bytes == len(payload)
    assert result.request_body_sha256 == hashlib.sha256(payload).hexdigest()


def test_request_body_evidence_is_present_even_when_transport_fails(tmp_path):
    """A request whose bytes were prepared but never answered still has evidence.

    Never substitutes a character count or response length -- the byte count comes
    from the exact prepared body, captured before the (failing) send.
    """
    import hashlib

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        raise httpx.ConnectError("boom", request=request)

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(attack(attacked_text="hello there"))
    writer.close()

    expected_body = json.dumps({"text": "hello there"}, separators=(",", ":")).encode()
    # HTTPX's own json= serialization, not something we hand-roll -- confirm shape
    # rather than byte-for-byte matching our own guess of its separators.
    assert result.request_body_bytes is not None
    assert result.request_body_sha256 is not None
    assert result.error is not None and result.error.startswith("connection_error")


def test_request_body_evidence_is_none_on_serialization_failure(tmp_path):
    """If building the request itself fails, there were never any bytes to hash."""

    class Unserializable:
        def __repr__(self):
            raise RuntimeError("cannot even repr this")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    runner, writer = make_runner(tmp_path, handler)
    outcome = runner.send(None, Unserializable())
    writer.close()

    assert outcome["request_body_bytes"] is None
    assert outcome["request_body_sha256"] is None
    assert outcome["error"].startswith("serialization_error")


def test_baseline_and_attack_rows_carry_target_id_and_suite_id(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return predict_response()

    runner, writer = make_runner(tmp_path, handler)
    runner.target_id = "sentiment_v1"
    runner.suite_id = "core"
    baseline_result = runner.send_baseline(baseline())
    attack_result = runner.send_attack(attack())
    writer.close()

    assert (baseline_result.target_id, baseline_result.suite_id) == ("sentiment_v1", "core")
    assert (attack_result.target_id, attack_result.suite_id) == ("sentiment_v1", "core")


# --------------------------------------------------------------------------
# frozen case sets
# --------------------------------------------------------------------------


def _apply_split_selection(tmp_path, document, baselines, attacks):
    path = tmp_path / "split-selection.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    selection = runner_module.load_case_set(path)
    if selection.suite_id != "core":
        raise runner_module.SelectionError("selection suite does not match core")
    units = runner_module.apply_case_set(selection, baselines, attacks)
    selected_baselines = [case for case in units if isinstance(case, BaselineCase)]
    selected_attacks = [case for case in units if isinstance(case, AttackCase)]
    selected = set(selection.order)
    excluded = [baseline_key(b.baseline_id) for b in baselines
                if baseline_key(b.baseline_id) not in selected]
    excluded += [attack_key(a.attack_id) for a in attacks
                 if attack_key(a.attack_id) not in selected]
    return selected_baselines, selected_attacks, excluded


def test_apply_case_set_selects_exact_ids_in_order(tmp_path):
    baselines, attacks = suite(n_baselines=3, n_standalone=2, n_derived=2)
    case_set = {
        "case_set_id": "mini",
        "suite_id": "core",
        "baseline_ids": ["b02", "b01"],
        "standalone_attack_ids": ["s.malformed.02", "s.malformed.01"],
        "derived_attack_ids": ["b01.encoding.01", "b02.encoding.02"],
    }
    sel_b, sel_a, excluded = _apply_split_selection(tmp_path, case_set, baselines, attacks)
    assert [b.baseline_id for b in sel_b] == ["b02", "b01"]
    assert [a.attack_id for a in sel_a] == [
        "s.malformed.02", "s.malformed.01", "b01.encoding.01", "b02.encoding.02",
    ]
    excluded_baseline_keys = {key for key in excluded if key.startswith("baseline:")}
    assert excluded_baseline_keys == {"baseline:b03"}


def test_apply_case_set_rejects_unknown_ids(tmp_path):
    baselines, attacks = suite()
    case_set = {
        "case_set_id": "mini", "suite_id": "core",
        "baseline_ids": ["b01", "does-not-exist"],
        "standalone_attack_ids": ["s.malformed.01"],
        "derived_attack_ids": [],
    }
    with pytest.raises(runner_module.SelectionError, match="does not contain"):
        _apply_split_selection(tmp_path, case_set, baselines, attacks)


def test_apply_case_set_allows_standalone_only_selection_with_no_derived_attacks(tmp_path):
    baselines, attacks = suite()
    case_set = {
        "case_set_id": "mini", "suite_id": "core",
        "baseline_ids": ["b01"],
        "standalone_attack_ids": ["s.malformed.01"],
        "derived_attack_ids": [],
    }
    sel_b, sel_a, _ = _apply_split_selection(tmp_path, case_set, baselines, attacks)
    assert [a.attack_id for a in sel_a] == ["s.malformed.01"]


def test_apply_case_set_rejects_duplicates(tmp_path):
    baselines, attacks = suite()
    case_set = {
        "case_set_id": "mini", "suite_id": "core",
        "baseline_ids": ["b01", "b01"],
        "standalone_attack_ids": ["s.malformed.01"],
        "derived_attack_ids": [],
    }
    with pytest.raises(runner_module.SelectionError, match="duplicate"):
        _apply_split_selection(tmp_path, case_set, baselines, attacks)


def test_apply_case_set_rejects_empty_lists(tmp_path):
    baselines, attacks = suite()
    case_set = {
        "case_set_id": "mini", "suite_id": "core",
        "baseline_ids": [], "standalone_attack_ids": [], "derived_attack_ids": [],
    }
    with pytest.raises(runner_module.SelectionError, match="empty"):
        _apply_split_selection(tmp_path, case_set, baselines, attacks)


def test_apply_case_set_rejects_wrong_suite_id(tmp_path):
    baselines, attacks = suite()
    case_set = {
        "case_set_id": "mini", "suite_id": "oces",
        "baseline_ids": ["b01"], "standalone_attack_ids": ["s.malformed.01"],
        "derived_attack_ids": [],
    }
    with pytest.raises(runner_module.SelectionError, match="suite"):
        _apply_split_selection(tmp_path, case_set, baselines, attacks)


def test_apply_case_set_rejects_derived_attack_whose_baseline_is_not_selected(tmp_path):
    baselines, attacks = suite(n_baselines=2)
    case_set = {
        "case_set_id": "mini", "suite_id": "core",
        # b02 excluded, but a derived attack keyed off b02 is still requested.
        "baseline_ids": ["b01"],
        "standalone_attack_ids": ["s.malformed.01"],
        "derived_attack_ids": ["b02.encoding.01"],
    }
    with pytest.raises(runner_module.SelectionError, match="baseline is not selected"):
        _apply_split_selection(tmp_path, case_set, baselines, attacks)


def test_apply_case_set_rejects_id_in_both_standalone_and_derived(tmp_path):
    baselines, attacks = suite()
    case_set = {
        "case_set_id": "mini", "suite_id": "core",
        "baseline_ids": ["b01"],
        "standalone_attack_ids": ["b01.encoding.01"],
        "derived_attack_ids": ["b01.encoding.01"],
    }
    with pytest.raises(runner_module.SelectionError, match="both standalone"):
        _apply_split_selection(tmp_path, case_set, baselines, attacks)


def test_load_case_set_rejects_missing_file(tmp_path):
    with pytest.raises(runner_module.SelectionError, match="cannot read"):
        runner_module.load_case_set(tmp_path / "does-not-exist.json")


def test_load_case_set_uses_declared_id_independent_of_filename(tmp_path):
    document = {"case_set_id": "declared-id", "suite_id": "core",
                "baseline_ids": ["b01"], "attack_ids": []}
    path = tmp_path / "arbitrary-filename.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert runner_module.load_case_set(path).case_set_id == "declared-id"


def test_real_frozen_ci_core_v1_case_set_matches_the_real_emotion_suite(tmp_path):
    """Full integration check against the actual committed baseline and case set.

    Needs a real tokenizer to build boundary.length.* cases (approximate mode
    cannot compute a real token boundary), so this only runs where transformers
    is actually installed -- e.g. on a contributor's machine, not in a bare CI
    sandbox. That is itself useful signal: if this ever fails on a real machine,
    the frozen case set has gone stale against the current suite-building code
    and needs a re-freeze, not a code fix here.
    """
    pytest.importorskip("transformers")
    from baseline.load import load_baseline

    baselines = sorted(load_baseline(), key=lambda b: b.baseline_id)
    token_counter, max_tokens = runner_module.build_token_counter("emotion_v2")
    from attacks.metadata import scoped_registry
    with scoped_registry():
        attacks = runner_module.build_suite_once(baselines, token_counter, max_tokens)
    selection_path = runner_module.ROOT / "analysis/case_sets/ci_core_v1.json"
    case_set = json.loads(selection_path.read_text(encoding="utf-8"))

    sel_b, sel_a, excluded = _apply_split_selection(tmp_path, case_set, baselines, attacks)

    counts = case_set["counts"]
    assert len(sel_b) == counts["baselines"]
    assert len(sel_a) == counts["standalone_attacks"] + counts["derived_attacks"]


def test_a_raw_case_with_no_headers_adds_none_of_its_own(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen["headers"] = dict(request.headers)
        return httpx.Response(400)

    runner, writer = make_runner(tmp_path, handler)
    runner.send_attack(attack("x", is_raw=True, raw_body=b"{}", raw_headers=None))
    writer.close()
    # httpx always sets host and content-length; what matters is that we did
    # not declare a content type the case never asked for.
    assert "content-type" not in seen["headers"]


# ==========================================================================
# 2. latency, banded at both boundaries
# ==========================================================================


def test_band_boundaries_exactly():
    assert band_latency(0.0, False) == BAND_NORMAL
    assert band_latency(1_999.9, False) == BAND_NORMAL
    assert band_latency(2_000.0, False) == BAND_SLOW, "2s exactly is slow, not normal"
    assert band_latency(9_999.0, False) == BAND_SLOW
    assert band_latency(10_000.0, True) == BAND_TIMEOUT


def test_latency_is_recorded_as_a_number_and_banded(tmp_path):
    runner, writer = make_runner(tmp_path, ok_handler, clock=FakeClock(step=2.5))
    result = runner.send_attack(attack())
    writer.close()
    assert result.latency_ms == pytest.approx(2_500.0)
    assert result.latency_band == BAND_SLOW


# ==========================================================================
# 3. a timeout is recorded, not raised
# ==========================================================================


def test_a_timeout_is_recorded_as_a_timeout(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        raise httpx.ReadTimeout("too slow", request=request)

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(attack("boundary.oversized_10mb"))
    writer.close()

    assert result.latency_band == BAND_TIMEOUT
    assert result.status_code is None
    assert result.error.startswith(ERR_TIMEOUT)
    assert runner.counts["timeouts"] == 1
    assert runner.counts["connection_errors"] == 0


def test_the_three_failure_kinds_are_recorded_separately(tmp_path):
    """A 5xx, a dropped connection and a health failure are three things."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if "conn" in request.content.decode("utf-8", "replace"):
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(500, json={"detail": "Internal Server Error"})

    runner, writer = make_runner(tmp_path, handler)
    five_hundred = runner.send_attack(attack("a-500", attacked_text="normal"))
    dropped = runner.send_attack(attack("a-conn", attacked_text="conn"))
    writer.close()

    assert five_hundred.status_code == 500 and five_hundred.error is None
    assert dropped.status_code is None and dropped.error.startswith(ERR_CONNECTION)
    assert runner.counts["server_errors_5xx"] == 1
    assert runner.counts["connection_errors"] == 1
    assert runner.counts["health_failures"] == 0


def test_an_attack_connection_failure_is_not_retried_away(tmp_path):
    """The analysis counts connection failures, so hiding one would skew it."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        attempts["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(attack())
    writer.close()

    assert attempts["n"] == 1, "the attack request was retried"
    assert result.error.startswith(ERR_CONNECTION)


# ==========================================================================
# 4. the health check lands on the right request
# ==========================================================================


def test_health_result_is_attached_to_the_request_before_it(tmp_path):
    state = {"predicts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            if state["predicts"] >= 2:
                raise httpx.ConnectError("dead", request=request)
            return httpx.Response(200, json={"status": "ok"})
        state["predicts"] += 1
        return predict_response()

    runner, writer = make_runner(tmp_path, handler)
    runner.send_attack(attack("a-first"))
    with pytest.raises(EndpointDied) as died:
        runner.send_attack(attack("a-killer"))
    writer.close()

    assert died.value.result.attack_id == "a-killer"
    rows = read_rows(writer.path)
    assert [r["attack_id"] for r in rows] == ["a-first", "a-killer"]
    assert rows[0]["endpoint_alive_after"] is True
    assert rows[1]["endpoint_alive_after"] is False
    assert runner.counts["health_failures"] == 1


def test_a_socket_closed_by_a_500_is_not_a_dead_endpoint(tmp_path):
    """The trap this runner exists to avoid.

    Uvicorn answers a 500 with Connection: close, so the health ping that
    follows fails on the stale socket. Without a retry on a fresh connection
    the run would stop on the first 500 and blame an innocent payload.
    """
    state = {"health_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            state["health_calls"] += 1
            if state["health_calls"] == 1:
                raise httpx.ConnectError("stale socket", request=request)
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(500, text="Internal Server Error")

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(attack("a-500"))
    writer.close()

    assert result.endpoint_alive_after is True, "phantom service death"
    assert runner.counts["health_ping_retries"] == 1
    assert runner.counts["health_failures"] == 0


def test_preflight_refuses_to_send_against_a_dead_endpoint(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nothing listening", request=request)

    runner, writer = make_runner(tmp_path, handler)
    assert runner.preflight() is False
    writer.close()
    assert read_rows(writer.path) == []


# ==========================================================================
# 5. baselines are baselines
# ==========================================================================


def test_baselines_are_recorded_without_a_fake_attack_id(tmp_path):
    runner, writer = make_runner(tmp_path)
    result = runner.send_baseline(baseline("b07"))
    writer.close()

    assert result.case_type == "baseline"
    assert result.attack_id is None
    assert result.category is None
    assert result.baseline_id == "b07"
    assert runner.completed == [baseline_key("b07")]


def test_all_seven_scores_are_populated_on_the_row(tmp_path):
    runner, writer = make_runner(tmp_path)
    result = runner.send_baseline(baseline())
    writer.close()

    assert result.label == "joy"
    assert result.confidence == pytest.approx(0.94)
    assert result.all_scores is not None and len(result.all_scores) == 7
    assert read_rows(writer.path)[0]["all_scores"]["joy"] == pytest.approx(0.94)


def test_the_full_body_is_kept_even_when_there_is_no_prediction(tmp_path):
    """The analysis inspects 422 bodies for leaks; a status code is not enough."""
    body = {"detail": [{"loc": ["body", "text"], "msg": "Input should be a valid string"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(422, json=body)

    runner, writer = make_runner(tmp_path, handler)
    result = runner.send_attack(attack("boundary.type_int"))
    writer.close()

    assert json.loads(result.response_body) == body
    assert (result.label, result.confidence, result.all_scores) == (None, None, None)


def test_parse_prediction_reads_values_without_inventing_any():
    label, confidence, scores = parse_prediction(
        json.dumps({"label": "anger", "confidence": 0.77, "all_scores": {"anger": 0.77}})
    )
    assert (label, confidence, scores) == ("anger", 0.77, {"anger": 0.77})
    assert parse_prediction("not json") == (None, None, None)
    assert parse_prediction("[1,2,3]") == (None, None, None)
    assert parse_prediction(json.dumps({"label": 5, "confidence": True})) == (None, None, None)


# ==========================================================================
# 6. rows survive an early exit, and the meta file is still written
# ==========================================================================


def test_rows_written_before_a_death_are_on_disk_and_meta_is_written(tmp_path):
    state = {"predicts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            if state["predicts"] >= 3:
                raise httpx.ConnectError("dead", request=request)
            return httpx.Response(200, json={"status": "ok"})
        state["predicts"] += 1
        return predict_response()

    baselines, attacks = suite(n_baselines=1, n_standalone=4, n_derived=0)
    runner, writer = make_runner(tmp_path, handler)
    with pytest.raises(EndpointDied):
        runner.run(baselines, attacks)

    # Deliberately not closing the writer: the point is that the rows are
    # already flushed, not that a clean shutdown saved them.
    rows = read_rows(writer.path)
    assert len(rows) == 3, "the killer row and everything before it must be on disk"
    assert rows[-1]["endpoint_alive_after"] is False

    planned = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks
    ]
    meta = build_meta(
        run_id="r1", version="v1", started_at="t0", ended_at="t1", is_smoke=False,
        termination_reason=TERM_HEALTH, planned_fingerprint="fp", manifest_sha256="sha",
        manifest_path="results/manifest.json", target=TARGET,
        planned=planned, selected=planned, completed=runner.completed,
        skipped=runner.skipped, limit_excluded=[], limit=None,
        counts=runner.counts, suite_sizes={},
    )
    path = write_meta(Path(tmp_path) / "run_meta_v1.json", meta)
    written = json.loads(path.read_text(encoding="utf-8"))

    assert written["termination_reason"] == TERM_HEALTH
    assert written["coverage"]["completed"] == 3
    assert written["coverage"]["planned"] == 5
    assert written["coverage"]["missing"] == 2
    # The missing cases are named, so the analysis can mark them unavailable
    # rather than mistake them for resolved.
    assert written["case_ids"]["missing"] == [
        attack_key("s.malformed.03"), attack_key("s.malformed.04")
    ]


# ==========================================================================
# 7. stable order across runs
# ==========================================================================


def test_two_runs_produce_the_same_ids_in_the_same_order(tmp_path):
    baselines, attacks = suite()
    orders = []
    for index in range(2):
        runner, writer = make_runner(tmp_path / f"pass{index}")
        runner.run(baselines, attacks)
        writer.close()
        orders.append(
            [(r["case_type"], r["baseline_id"], r["attack_id"]) for r in read_rows(writer.path)]
        )

    assert orders[0] == orders[1]
    assert [r[0] for r in orders[0][:2]] == ["baseline", "baseline"]
    assert [r[2] for r in orders[0][2:5]] == [
        "s.malformed.01", "s.malformed.02", "s.malformed.03"
    ]
    assert [r[1] for r in orders[0][5:]] == ["b01", "b01", "b02", "b02"]


def test_partition_keeps_standalone_before_derived():
    _, attacks = suite()
    standalone, derived = partition_attacks(attacks)
    assert all(case.baseline_id is None for case in standalone)
    assert all(case.baseline_id is not None for case in derived)
    assert len(standalone) + len(derived) == len(attacks)


# ==========================================================================
# 8. the fingerprint is unaffected by flags
# ==========================================================================


def test_a_limited_run_and_a_full_run_share_the_planned_fingerprint():
    baselines, attacks = suite(n_baselines=2, n_standalone=5, n_derived=2)
    full = fingerprint_suite(baselines, attacks)

    kept, excluded = select_attacks(attacks, limit=2)
    # The fingerprint is computed over the complete suite either way: it
    # records what we planned to send, not what we happened to send.
    limited = fingerprint_suite(baselines, attacks)

    assert limited == full
    assert len(kept) == 2 and len(excluded) == len(attacks) - 2
    assert fingerprint_suite(baselines, kept) != full, "sanity: the subset does differ"


def test_the_fingerprint_covers_baselines_as_well_as_attacks():
    baselines, attacks = suite()
    changed = [BaselineCase("b01", "different text", "joy", "dataset")] + baselines[1:]
    assert fingerprint_suite(changed, attacks) != fingerprint_suite(baselines, attacks)


def test_the_fingerprint_changes_when_any_hashed_field_changes():
    baselines, attacks = suite(n_baselines=1, n_standalone=1, n_derived=0)
    original = fingerprint_suite(baselines, attacks)
    for field, value in (
        ("category", "encoding"),
        ("attacked_text", "something else"),
        ("is_raw", True),
        ("raw_headers", {"content-type": "text/plain"}),
    ):
        mutated = [AttackCase(**{**attacks[0].__dict__, field: value})]
        assert fingerprint_suite(baselines, mutated) != original, field


def test_bytes_in_raw_body_hash_deterministically_and_do_not_collide_with_str():
    baselines, _ = suite(n_baselines=1, n_standalone=0, n_derived=0)
    as_bytes = [attack("x", is_raw=True, raw_body=b'{"text":1}')]
    as_text = [attack("x", is_raw=True, raw_body='{"text":1}')]

    first = fingerprint_suite(baselines, as_bytes)
    second = fingerprint_suite(baselines, as_bytes)
    assert first == second, "byte bodies must hash the same on every run"
    assert first != fingerprint_suite(baselines, as_text), "bytes collided with str"


def test_invalid_utf8_bytes_can_be_fingerprinted_at_all():
    """Base64 is why this works: these bytes cannot go through JSON as text."""
    baselines, _ = suite(n_baselines=1, n_standalone=0, n_derived=0)
    cases = [attack("x", is_raw=True, raw_body=b"\xff\xfe\x00 not utf-8")]
    assert len(fingerprint_suite(baselines, cases)) == 64


def test_the_fingerprint_is_order_sensitive():
    baselines, attacks = suite(n_baselines=1, n_standalone=3, n_derived=0)
    reordered = [attacks[2], attacks[0], attacks[1]]
    assert fingerprint_suite(baselines, reordered) != fingerprint_suite(baselines, attacks)


# ==========================================================================
# 9. a skip shows up in coverage and leaves the fingerprint alone
# ==========================================================================


def test_a_skipped_case_is_never_sent_and_is_listed_as_skipped(tmp_path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        sent.append(json.loads(request.content)["text"])
        return predict_response()

    runner, writer = make_runner(tmp_path, handler, skip=("a-killer",))
    runner.run(
        [], [attack("a-safe", attacked_text="fine"), attack("a-killer", attacked_text="boom")]
    )
    writer.close()

    assert sent == ["fine"]
    assert runner.skipped == [attack_key("a-killer")]
    assert runner.completed == [attack_key("a-safe")]


def test_skipped_cases_are_excluded_from_selected_but_not_from_planned():
    baselines, attacks = suite(n_baselines=1, n_standalone=3, n_derived=0)
    planned = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks
    ]
    before = fingerprint_suite(baselines, attacks)

    skip = {"s.malformed.02"}
    selected = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks if a.attack_id not in skip
    ]
    meta = build_meta(
        run_id="r", version="v1", started_at="t0", ended_at="t1", is_smoke=False,
        termination_reason="completed", planned_fingerprint=before, manifest_sha256="sha",
        manifest_path="p", target=TARGET, planned=planned, selected=selected,
        completed=selected, skipped=[attack_key("s.malformed.02")], limit_excluded=[],
        limit=None, counts={}, suite_sizes={},
    )

    assert meta["coverage"]["planned"] == 4
    assert meta["coverage"]["selected"] == 3
    assert meta["coverage"]["skipped"] == 1
    assert meta["coverage"]["missing"] == 0
    # A skip filters what gets sent; it never touches the built suite.
    assert meta["fingerprints"]["planned_suite_sha256"] == fingerprint_suite(baselines, attacks)


# ==========================================================================
# 10 and 11. --limit touches attacks only, and planned stays whole
# ==========================================================================


def test_limit_excludes_attacks_only_and_keeps_planned_at_the_full_suite():
    """Ahsan's worked example, in code.

    --limit 20 must not report planned 20. Reporting it that way would make a
    smoke run look like complete coverage.
    """
    baselines = [baseline(f"b{i:02d}") for i in range(1, 43)]          # 42
    attacks = [attack(f"a{i:04d}") for i in range(1, 1_887)]           # 1,886
    planned = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in attacks
    ]
    kept, excluded = select_attacks(attacks, limit=20)
    selected = [baseline_key(b.baseline_id) for b in baselines] + [
        attack_key(a.attack_id) for a in kept
    ]

    meta = build_meta(
        run_id="r", version="v1", started_at="t0", ended_at="t1", is_smoke=True,
        termination_reason="stopped_on_limit", planned_fingerprint="fp",
        manifest_sha256="sha", manifest_path="p", target=TARGET,
        planned=planned, selected=selected, completed=selected, skipped=[],
        limit_excluded=excluded, limit=20, counts={}, suite_sizes={},
    )
    coverage = meta["coverage"]
    assert coverage["planned"] == 1_928
    assert coverage["limit_excluded"] == 1_866
    assert coverage["selected"] == 62
    assert coverage["completed"] == 62
    assert coverage["coverage_rate"] == pytest.approx(0.032, abs=0.001)
    assert meta["run_type"] == "smoke"


def test_a_limited_run_still_sends_every_baseline(tmp_path):
    baselines, attacks = suite(n_baselines=4, n_standalone=10, n_derived=0)
    kept, _ = select_attacks(attacks, limit=3)
    runner, writer = make_runner(tmp_path)
    runner.run(baselines, kept)
    writer.close()

    rows = read_rows(writer.path)
    sent_baselines = [r for r in rows if r["case_type"] == "baseline"]
    sent_attacks = [r for r in rows if r["case_type"] == "attack"]
    assert len(sent_baselines) == 4, "derived attacks are meaningless without their baseline"
    assert len(sent_attacks) == 3


def test_a_limit_larger_than_the_suite_excludes_nothing():
    _, attacks = suite(n_baselines=1, n_standalone=3, n_derived=0)
    kept, excluded = select_attacks(attacks, limit=999)
    assert len(kept) == len(attacks) and excluded == []


def test_no_limit_selects_everything():
    _, attacks = suite()
    kept, excluded = select_attacks(attacks, limit=None)
    assert kept == list(attacks) and excluded == []


# ==========================================================================
# 12 and 13. the output files
# ==========================================================================


def test_a_second_invocation_leaves_no_rows_from_the_first(tmp_path):
    """Two runs must never share rows in one file."""
    path = Path(tmp_path) / "results_v1.jsonl"

    first = ResultWriter(path)
    runner = Runner(target=TARGET, version="v1", writer=first,
                    transport=httpx.MockTransport(ok_handler), clock=FakeClock())
    runner.run([], [attack("a01"), attack("a02"), attack("a03")])
    first.close()
    assert len(read_rows(path)) == 3

    second = ResultWriter(path)          # same path, new invocation
    runner = Runner(target=TARGET, version="v1", writer=second,
                    transport=httpx.MockTransport(ok_handler), clock=FakeClock())
    runner.run([], [attack("a01")])
    second.close()

    rows = read_rows(path)
    assert len(rows) == 1, "rows from the previous run survived"
    assert rows[0]["attack_id"] == "a01"


def test_the_writer_creates_its_directory(tmp_path):
    path = Path(tmp_path) / "smoke" / "nested" / "results_v2.jsonl"
    writer = ResultWriter(path)
    writer.close()
    assert path.exists()


def test_the_version_comes_from_the_argument_not_the_url(tmp_path):
    runner, writer = make_runner(tmp_path, version="v2")
    result = runner.send_attack(attack())
    writer.close()
    assert result.version == "v2"
    assert read_rows(writer.path)[0]["version"] == "v2"


def test_coverage_rate_is_completed_over_planned_not_over_selected():
    meta = build_meta(
        run_id="r", version="v1", started_at="t0", ended_at="t1", is_smoke=True,
        termination_reason="stopped_on_limit", planned_fingerprint="fp",
        manifest_sha256="sha", manifest_path="p", target=TARGET,
        planned=[f"attack:a{i}" for i in range(100)],
        selected=[f"attack:a{i}" for i in range(10)],
        completed=[f"attack:a{i}" for i in range(10)],
        skipped=[], limit_excluded=[f"attack:a{i}" for i in range(10, 100)],
        limit=10, counts={}, suite_sizes={},
    )
    assert meta["coverage"]["coverage_rate"] == pytest.approx(0.1)


def test_the_manifest_hash_is_recorded_in_the_meta_file():
    meta = build_meta(
        run_id="r", version="v1", started_at="t0", ended_at="t1", is_smoke=False,
        termination_reason="completed", planned_fingerprint="fp" * 32,
        manifest_sha256="ab" * 32, manifest_path="results/manifest.json", target=TARGET,
        planned=[], selected=[], completed=[], skipped=[], limit_excluded=[],
        limit=None, counts={}, suite_sizes={},
    )
    # Identical payloads read through a different manifest would be judged
    # against different oracles, which would look fine and be wrong.
    assert meta["fingerprints"]["manifest_sha256"] == "ab" * 32
    assert meta["fingerprints"]["planned_suite_sha256"] == "fp" * 32


# ==========================================================================
# nothing hardcoded
# ==========================================================================


def test_no_address_or_port_is_hardcoded_in_the_runner():
    """A deployed endpoint has no port that tells us anything."""
    source = (Path(__file__).resolve().parent.parent / "runner" / "run.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line
        for line in source.splitlines()
        if not line.lstrip().startswith("#") and "python -m runner.run" not in line
    )
    for forbidden in ("localhost", "127.0.0.1", "0.0.0.0", ":8000", ":8001"):
        assert forbidden not in code, f"{forbidden!r} is hardcoded in runner/run.py"


def test_target_id_keeps_the_registry_configured_port():
    registry = load_registry()
    resolved = runner_module.resolve_target(
        registry, target_id="sentiment_v1", version=None, suite="core", evaluation_id=None
    )
    assert registry.target(resolved.target_id).port == 8002
    assert (resolved.version, resolved.task_id) == ("v1", "sentiment_2")


def test_legacy_target_and_version_still_parse_without_target_id():
    args = runner_module.build_parser().parse_args(
        ["--target", "http://caller-supplied.example", "--version", "v1"]
    )
    resolved = runner_module.resolve_target(
        load_registry(), target_id=args.target_id, version=args.version,
        suite=args.suite, evaluation_id=args.evaluation_id
    )
    assert args.target == "http://caller-supplied.example"
    assert resolved.target_id == "emotion_v1"


def test_target_id_conflicting_with_version_is_rejected():
    with pytest.raises(ContractError, match="conflict"):
        runner_module.resolve_target(
            load_registry(), target_id="sentiment_v1", version="v2",
            suite="core", evaluation_id=None
        )


def test_neither_target_id_nor_version_is_rejected():
    with pytest.raises(ContractError, match="required"):
        runner_module.resolve_target(
            load_registry(), target_id=None, version=None, suite="core", evaluation_id=None
        )


# CLI regressions: exercise main() so artifact and settings bugs cannot be
# hidden by calling build_meta() with manually correct inputs.
@pytest.fixture
def cli_run(monkeypatch, tmp_path):
    baselines = [baseline("b1")]
    attacks = [attack(aid) for aid in ("a1", "a2", "a3")]
    state = {"posts": 0, "health": 0, "dead_after": None, "interrupt_after": None,
             "manifest_writes": 0, "manifest_path": None, "settings": None}
    # Both doubles take *args/**kwargs: main() now passes the registry-resolved
    # baseline path to load_baseline and the suite/task_id keywords to
    # build_suite_once. The test still supplies its own hand-built cases, so no
    # assertion about behaviour is relaxed by accepting the arguments.
    monkeypatch.setattr(runner_module, "load_baseline", lambda *a, **k: baselines)
    monkeypatch.setattr(runner_module, "build_suite_once", lambda *a, **k: attacks)

    def manifest(path):
        state["manifest_writes"] += 1
        state["manifest_path"] = Path(path)
        Path(path).write_text('{"new": "manifest"}', encoding="utf-8")
    monkeypatch.setattr(runner_module.library, "write_manifest", manifest)

    def handler(request):
        if request.url.path == "/health":
            # Expectations exist before preflight, but prior published files
            # remain untouched until health succeeds.
            if state["health"] == 0:
                assert state["manifest_path"].read_text() == '{"new": "manifest"}'
            state["health"] += 1
            dead = state["dead_after"] is not None and state["posts"] >= state["dead_after"]
            return httpx.Response(503 if dead else 200)
        assert (tmp_path / "manifest.json").read_text() == '{"new": "manifest"}'
        state["posts"] += 1
        return predict_response()

    def client(runner):
        state["settings"] = (runner.timeout, runner.health_timeout)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=runner.timeout)
    monkeypatch.setattr(Runner, "_new_client", client)
    original_send = Runner.send

    def interruptible_send(runner, *args):
        if state["interrupt_after"] is not None and state["posts"] >= state["interrupt_after"]:
            raise KeyboardInterrupt()
        return original_send(runner, *args)
    monkeypatch.setattr(Runner, "send", interruptible_send)

    def invoke(*flags):
        return runner_module.main(["--target", TARGET, "--version", "v1", "--no-tokenizer",
                                   "--out", str(tmp_path), *flags])
    def meta():
        return json.loads((tmp_path / "run_meta_v1.json").read_text())
    return invoke, meta, state, tmp_path


def test_cli_early_death_records_unreached_skip(cli_run):
    invoke, meta, state, _ = cli_run
    state["dead_after"] = 1
    assert invoke("--skip", "a3") == 1
    data = meta()
    assert data["case_ids"]["skipped"] == ["attack:a3"]
    assert data["case_ids"]["missing"] == ["attack:a1", "attack:a2"]
    coverage = data["coverage"]
    assert coverage["planned"] == coverage["selected"] + coverage["skipped"] + coverage["limit_excluded"]


def test_runner_early_death_records_unreached_skip(tmp_path):
    def handler(request):
        return httpx.Response(503) if request.url.path == "/health" else predict_response()
    runner, writer = make_runner(tmp_path, handler, skip=("a3",))
    with pytest.raises(EndpointDied):
        runner.run([baseline()], [attack(aid) for aid in ("a1", "a2", "a3")])
    writer.close()
    assert runner.skipped == ["attack:a3"]


def test_cli_limit_takes_precedence_over_overlapping_skip(cli_run):
    invoke, meta, _, _ = cli_run
    assert invoke("--limit", "2", "--skip", "a2", "--skip", "a3") == 0
    data = meta()
    assert data["case_ids"]["skipped"] == ["attack:a2"]
    assert data["case_ids"]["limit_excluded"] == ["attack:a3"]
    assert data["case_ids"]["completed"] == ["baseline:b1", "attack:a1"]
    assert data["coverage"] == dict(planned=4, selected=2, completed=2, skipped=1,
                                    limit_excluded=1, deselected=0, missing=0,
                                    coverage_rate=.5)


def test_cli_metadata_records_effective_settings(cli_run):
    invoke, meta, state, _ = cli_run
    assert invoke("--timeout", "10", "--health-timeout", "0.1") == 0
    settings = meta()["runner_settings"]
    assert (settings["request_timeout_s"], settings["health_timeout_s"]) == state["settings"] == (10, .1)


@pytest.mark.parametrize("flags", [
    ("--limit", "-1"), ("--timeout", "0.25"), ("--timeout", "20"),
    ("--timeout", "nan"), ("--health-timeout", "0"), ("--health-timeout", "-1"),
    ("--health-timeout", "nan"), ("--health-timeout", "inf"),
])
def test_cli_rejects_invalid_settings_before_build_or_network(cli_run, monkeypatch, flags):
    invoke, _, state, _ = cli_run
    def unexpected_load(path=None):
        pytest.fail("invalid arguments must be rejected before loading/building the suite")
    monkeypatch.setattr(runner_module, "load_baseline", unexpected_load)
    with pytest.raises(SystemExit) as exited:
        invoke(*flags)
    assert exited.value.code == 2
    assert state["posts"] == state["health"] == state["manifest_writes"] == 0


def test_select_attacks_rejects_negative_limit():
    with pytest.raises(ValueError, match="non-negative"):
        select_attacks([attack()], -1)


def test_runner_rejects_nonstandard_request_timeout(tmp_path):
    with ResultWriter(tmp_path / "unused.jsonl") as writer:
        with pytest.raises(ValueError, match="request timeout must be"):
            Runner(TARGET, "v1", writer, timeout=.25)


@pytest.mark.parametrize("interrupt_after", [0, 1])
def test_cli_interrupt_has_honest_status_and_preserves_rows(cli_run, interrupt_after):
    invoke, meta, state, output = cli_run
    state["interrupt_after"] = interrupt_after
    assert invoke() == 130
    data = meta()
    assert data["termination_reason"] == runner_module.TERM_INTERRUPTED
    assert data["coverage"]["completed"] == interrupt_after
    assert data["coverage"]["missing"] == 4 - interrupt_after
    assert len(read_rows(output / "results_v1.jsonl")) == interrupt_after


def test_cli_failed_preflight_preserves_all_existing_artifacts(cli_run):
    invoke, _, state, output = cli_run
    assert invoke() == 0
    artifacts = [output / name for name in ("results_v1.jsonl", "run_meta_v1.json", "manifest.json")]
    previous = {path: path.read_bytes() for path in artifacts}
    state["dead_after"] = 0
    assert invoke() == 2
    assert {path: path.read_bytes() for path in artifacts} == previous
    assert not list(output.glob(".runner-*"))


def test_cli_failed_preflight_does_not_publish_a_new_run(cli_run):
    invoke, _, state, output = cli_run
    state["dead_after"] = 0
    assert invoke() == 2
    assert state["posts"] == 0
    assert list(output.iterdir()) == []


def test_cli_manifest_written_once_before_network_and_published_before_cases(cli_run):
    invoke, meta, state, output = cli_run
    assert invoke() == 0
    assert state["manifest_writes"] == 1
    assert state["posts"] == 4 and state["health"] == 5
    assert not list(output.glob(".runner-*"))
    assert meta()["fingerprints"]["manifest_sha256"] == runner_module.sha256_file(output / "manifest.json")


def test_cli_zero_limit_sends_baselines_only(cli_run):
    invoke, meta, state, _ = cli_run
    assert invoke("--limit", "0") == 0
    assert state["posts"] == 1
    assert meta()["coverage"]["limit_excluded"] == 3


def test_total_deadline_cancels_dripping_response_and_allows_next_request(tmp_path):
    """Real sockets: progress must not reset the default ten-second deadline."""
    stop = threading.Event()
    handler_done = threading.Event()
    requests = []

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(body)
            if json.loads(body)["text"] != "drip":
                response = b'{"label":"joy","confidence":0.94,"all_scores":{"joy":0.94}}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                return
            self.send_response(200)
            self.send_header("Content-Length", "120")
            self.end_headers()
            try:
                for _ in range(120):
                    if stop.wait(.1):
                        break
                    self.wfile.write(b"x")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                handler_done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with ResultWriter(tmp_path / "deadline.jsonl") as writer:
            runner = Runner(f"http://127.0.0.1:{server.server_port}", "v1", writer)
            start = time.perf_counter()
            result = runner.send(None, "drip")
            elapsed = time.perf_counter() - start
            assert result["latency_band"] == BAND_TIMEOUT
            assert result["status_code"] is None
            assert result["error"].startswith(ERR_TIMEOUT)
            assert 9.5 <= elapsed < 11.5
            assert runner.counts["timeouts"] == 1
            assert runner.send(None, "healthy")["status_code"] == 200
            assert [json.loads(body)["text"] for body in requests] == ["drip", "healthy"]
            runner.close()
            assert handler_done.wait(2), "cancelled request left its socket open"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


# ==========================================================================
# Stage 3: target identity, frozen selections and request-byte evidence
#
# One deliberate exception to the "nothing here imports attacks" rule at the top
# of this file, and it is confined to the manifest-isolation tests below. Those
# check that two builds in one process do not contaminate each other's manifest,
# which is a property of the real shared metadata registry -- a hand-built double
# would have no shared state to contaminate, so a double could only ever pass.
# ==========================================================================

import hashlib

from contract import ContractError, RunResult
from endpoint.targets import load_registry
from runner.run import (
    CaseSelection,
    SelectionError,
    apply_case_set,
    build_suite_once,
    code_provenance,
    default_send_order,
    emotion_target_for_version,
    fingerprint_selection,
    load_case_set,
    resolve_target,
)

REGISTRY = load_registry()


# --------------------------------------------------------------------------
# request-byte evidence: the sender's record of what went on the wire
# --------------------------------------------------------------------------


def capturing_handler(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        captured.append(bytes(request.content))
        return predict_response()
    return handler


@pytest.mark.parametrize("text, why", [
    ("i feel great today", "ascii"),
    ("je suis très déçu — vraiment", "unicode outside ascii"),
    ("emoji 🙂 and a tab\tand a newline\n", "characters whose byte count is not their length"),
])
def test_recorded_body_bytes_are_the_bytes_that_were_sent(tmp_path, text, why):
    captured: list = []
    runner, writer = make_runner(tmp_path, capturing_handler(captured))
    result = runner.send_baseline(baseline(text=text))
    writer.close()

    assert len(captured) == 1, why
    on_the_wire = captured[0]
    assert result.request_body_bytes == len(on_the_wire)
    assert result.request_body_sha256 == hashlib.sha256(on_the_wire).hexdigest()
    # The thing this field exists to stop being: a character count.
    assert result.request_body_bytes != len(text) or why == "ascii"
    row = read_rows(writer.path)[0]
    assert row["request_body_bytes"] == len(on_the_wire)
    assert row["request_body_sha256"] == result.request_body_sha256


def test_raw_malformed_bytes_are_measured_exactly_as_sent(tmp_path):
    """Invalid UTF-8 is measured as bytes, never decoded or repaired first."""
    captured: list = []
    payload = b'{"text": "\xff\xfe broken"'
    runner, writer = make_runner(tmp_path, capturing_handler(captured))
    result = runner.send_attack(attack(
        "malformed.invalid_utf8", is_raw=True, raw_body=payload,
        raw_headers={"Content-Type": "application/json"},
    ))
    writer.close()

    assert captured == [payload]
    assert result.request_body_bytes == len(payload)
    assert result.request_body_sha256 == hashlib.sha256(payload).hexdigest()


def test_body_evidence_survives_a_transport_failure(tmp_path):
    """A request that got no response still has a known attempted body."""
    def dead(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        raise httpx.ConnectError("refused")

    runner, writer = make_runner(tmp_path, dead)
    result = runner.send_baseline(baseline(text="i feel great today"))
    writer.close()
    assert result.status_code is None
    assert result.error.startswith(ERR_CONNECTION)
    assert result.request_body_bytes > 0
    assert len(result.request_body_sha256) == 64


def test_body_evidence_survives_a_timeout(tmp_path):
    def slow(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        raise httpx.ReadTimeout("too slow")

    runner, writer = make_runner(tmp_path, slow)
    result = runner.send_attack(attack("boundary.long"))
    writer.close()
    assert result.latency_band == BAND_TIMEOUT
    assert result.request_body_bytes > 0


def test_a_body_that_cannot_be_serialised_is_null_and_not_zero(tmp_path):
    """None means unavailable. Zero would claim an empty body reached the endpoint."""
    runner, writer = make_runner(tmp_path)

    def explode(case, text):
        raise TypeError("Object of type object is not JSON serializable")
    runner.prepare_request = explode

    result = runner.send_baseline(baseline())
    writer.close()
    assert result.request_body_bytes is None
    assert result.request_body_sha256 is None
    assert result.error.startswith(runner_module.ERR_SERIALIZATION)
    assert "No request was sent" in result.error
    assert runner.counts["serialization_errors"] == 1
    # Not counted as a transport failure: nothing reached the wire.
    assert runner.counts["connection_errors"] == 0


def test_the_request_that_was_measured_is_the_request_that_was_sent(tmp_path):
    """No re-serialisation between measuring and sending."""
    captured: list = []
    runner, writer = make_runner(tmp_path, capturing_handler(captured))
    request, body = runner.prepare_request(None, "i feel great today")
    writer.close()
    assert bytes(request.content) == body
    assert request.url.path == "/predict"


# --------------------------------------------------------------------------
# identity on the row
# --------------------------------------------------------------------------


def test_rows_carry_the_target_and_suite_that_produced_them(tmp_path):
    writer = ResultWriter(Path(tmp_path) / "results.jsonl")
    runner = Runner(TARGET, "v1", writer, transport=httpx.MockTransport(ok_handler),
                    clock=FakeClock(), target_id="sentiment_v1", suite_id="oces")
    result = runner.send_baseline(baseline())
    writer.close()
    assert (result.target_id, result.suite_id) == ("sentiment_v1", "oces")
    assert result.version == "v1"
    row = read_rows(writer.path)[0]
    assert row["target_id"] == "sentiment_v1"


def test_a_caller_that_declares_nothing_gets_blank_not_emotion(tmp_path):
    """Blank means "not declared". It must never be filled in with a guess."""
    runner, writer = make_runner(tmp_path)
    result = runner.send_baseline(baseline())
    writer.close()
    assert result.target_id == ""
    assert result.suite_id == ""


# --------------------------------------------------------------------------
# resolving a target
# --------------------------------------------------------------------------


def test_legacy_version_resolves_to_the_explicit_emotion_target():
    assert emotion_target_for_version(REGISTRY, "v1") == "emotion_v1"
    assert emotion_target_for_version(REGISTRY, "v2") == "emotion_v2"
    resolved = resolve_target(REGISTRY, target_id=None, version="v2",
                              suite="core", evaluation_id=None)
    assert (resolved.target_id, resolved.task_id) == ("emotion_v2", "emotion_7")
    assert "emotion" in resolved.resolved_from


def test_target_id_derives_the_version():
    resolved = resolve_target(REGISTRY, target_id="sentiment_v1", version=None,
                              suite="core", evaluation_id=None)
    assert (resolved.target_id, resolved.version) == ("sentiment_v1", "v1")
    assert resolved.task_id == "sentiment_2"


def test_conflicting_target_and_version_is_an_error_not_a_precedence_rule():
    with pytest.raises(ContractError, match="conflict"):
        resolve_target(REGISTRY, target_id="emotion_v2", version="v1",
                       suite="core", evaluation_id=None)
    # sentiment_v1 and emotion_v1 are BOTH version v1: agreeing on the version
    # does not make the pair unambiguous, which is why target_id is what is recorded.
    agreeing = resolve_target(REGISTRY, target_id="sentiment_v1", version="v1",
                              suite="core", evaluation_id=None)
    assert agreeing.target_id == "sentiment_v1"


def test_an_unknown_target_id_is_rejected():
    with pytest.raises(ContractError, match="unknown target_id"):
        resolve_target(REGISTRY, target_id="sentiment_v2", version=None,
                       suite="core", evaluation_id=None)


def test_a_target_outside_its_evaluation_is_rejected():
    with pytest.raises(ContractError, match="covers targets"):
        resolve_target(REGISTRY, target_id="sentiment_v1", version=None,
                       suite="core", evaluation_id="ci.emotion")


def test_an_evaluation_whose_suite_disagrees_is_rejected():
    with pytest.raises(ContractError, match="conflict"):
        resolve_target(REGISTRY, target_id="emotion_v1", version=None,
                       suite="oces", evaluation_id="emotion.core")


def test_neither_target_nor_version_is_an_error():
    with pytest.raises(ContractError, match="required"):
        resolve_target(REGISTRY, target_id=None, version=None,
                       suite="core", evaluation_id=None)


def test_there_is_no_third_suite():
    with pytest.raises(ContractError, match="unknown suite"):
        resolve_target(REGISTRY, target_id="emotion_v2", version=None,
                       suite="ci_core", evaluation_id=None)


# --------------------------------------------------------------------------
# frozen case selections
# --------------------------------------------------------------------------


def selection_document(**overrides) -> dict:
    document = {
        "case_set_id": "fx_v1",
        "selection_version": 1,
        "suite_id": "core",
        "baseline_ids": ["b01"],
        "attack_ids": ["s.malformed.01", "b01.encoding.01"],
        "order": ["baseline:b01", "attack:s.malformed.01", "attack:b01.encoding.01"],
        "exclusions": [],
    }
    document.update(overrides)
    return document


def write_selection(tmp_path, **overrides) -> Path:
    path = Path(tmp_path) / "selection.json"
    path.write_text(json.dumps(selection_document(**overrides)), encoding="utf-8")
    return path


def test_a_selection_is_read_exactly_as_frozen(tmp_path):
    selection = load_case_set(write_selection(tmp_path))
    assert selection.case_set_id == "fx_v1"
    assert selection.baseline_ids == ("b01",)
    assert selection.order[0] == "baseline:b01"
    assert len(selection.source_sha256) == 64


def test_the_order_defaults_to_the_runners_own_send_order(tmp_path):
    path = Path(tmp_path) / "no_order.json"
    document = selection_document()
    document.pop("order")
    path.write_text(json.dumps(document), encoding="utf-8")
    selection = load_case_set(path)
    assert selection.order == (
        "baseline:b01", "attack:s.malformed.01", "attack:b01.encoding.01"
    )


def test_the_frozen_ci_selection_on_disk_loads_and_keeps_its_counts():
    """The real analysis/case_sets/ci_core_v1.json, not a stand-in for it."""
    selection = load_case_set(
        Path(__file__).resolve().parent.parent / "analysis" / "case_sets" / "ci_core_v1.json"
    )
    assert selection.case_set_id == "ci_core_v1"
    assert selection.suite_id == "core"
    assert len(selection.baseline_ids) == 42
    assert len(selection.attack_ids) == 32 + 88
    assert len(selection.order) == 162
    # Standalone attacks come before derived ones, which is the send order.
    assert all(not key.startswith("dataset-") for key in selection.attack_ids[:32])
    assert all(key.startswith("dataset-") for key in selection.attack_ids[32:])
    assert selection.exclusions[0]["attack_id"] == "malformed.oversized_10mb"


@pytest.mark.parametrize("overrides, expected", [
    ({"baseline_ids": ["b01", "b01"]}, "duplicate"),
    ({"attack_ids": ["a", "a"]}, "duplicate"),
    ({"baseline_ids": [], "attack_ids": []}, "empty"),
    ({"suite_id": "ci_core"}, "suite_id"),
    ({"case_set_id": ""}, "case_set_id is required"),
    ({"order": ["baseline:b01"]}, "does not match"),
    ({"order": ["baseline:b01", "attack:s.malformed.01", "attack:nope"]}, "does not match"),
    ({"selection_version": "one"}, "selection_version"),
])
def test_a_selection_that_would_have_to_be_repaired_is_rejected(tmp_path, overrides, expected):
    with pytest.raises(SelectionError, match=expected):
        load_case_set(write_selection(tmp_path, **overrides))


def test_an_unreadable_selection_is_rejected(tmp_path):
    with pytest.raises(SelectionError, match="cannot read"):
        load_case_set(Path(tmp_path) / "absent.json")
    broken = Path(tmp_path) / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(SelectionError, match="not valid JSON"):
        load_case_set(broken)


def test_a_selection_naming_a_case_the_suite_lacks_is_an_error_not_a_skip(tmp_path):
    baselines, attacks = suite()
    selection = load_case_set(write_selection(tmp_path, attack_ids=["s.malformed.01", "ghost"],
                                              order=["baseline:b01", "attack:s.malformed.01",
                                                     "attack:ghost"]))
    with pytest.raises(SelectionError, match="does not contain"):
        apply_case_set(selection, baselines, attacks)


def test_every_selected_derived_case_must_have_its_baseline_selected(tmp_path):
    baselines, attacks = suite()
    selection = load_case_set(write_selection(
        tmp_path, baselines_ids=None, baseline_ids=["b01"],
        attack_ids=["b02.encoding.01"], order=["baseline:b01", "attack:b02.encoding.01"],
    ))
    with pytest.raises(SelectionError, match="baseline is not selected"):
        apply_case_set(selection, baselines, attacks)


def test_a_selection_is_executed_in_its_own_order(tmp_path):
    baselines, attacks = suite()
    selection = load_case_set(write_selection(
        tmp_path,
        baseline_ids=["b01", "b02"],
        attack_ids=["b02.encoding.01", "s.malformed.01"],
        order=["attack:s.malformed.01", "baseline:b02", "baseline:b01",
               "attack:b02.encoding.01"],
    ))
    units = apply_case_set(selection, baselines, attacks)
    assert [getattr(u, "attack_id", None) or u.baseline_id for u in units] == [
        "s.malformed.01", "b02", "b01", "b02.encoding.01"
    ]


def test_the_recorded_selection_hash_is_the_files_own_hash(tmp_path):
    """Matches tests/fixtures/stage3/runs/emotion_core/emotion_v1/run_meta.json."""
    fixtures = Path(__file__).resolve().parent / "fixtures" / "stage3" / "runs"
    fixture_meta = json.loads(
        (fixtures / "emotion_core" / "emotion_v1" / "run_meta.json").read_text(encoding="utf-8")
    )
    recorded = fixture_meta["fingerprints"]["selection_sha256"]
    assert recorded == runner_module.sha256_file(fixtures / "emotion_core" / "case_selection.json")
    # And a run with no selection file records null there, not a substitute.
    assert json.loads(
        (fixtures / "sentiment_core" / "sentiment_v1" / "run_meta.json").read_text(encoding="utf-8")
    )["fingerprints"]["selection_sha256"] is None


def test_the_selection_fingerprint_is_order_sensitive_and_scoped():
    keys = ["baseline:b01", "attack:a1"]
    same = fingerprint_selection(keys, case_set_id="x", suite_id="core")
    assert same == fingerprint_selection(list(keys), case_set_id="x", suite_id="core")
    assert same != fingerprint_selection(list(reversed(keys)), case_set_id="x", suite_id="core")
    assert same != fingerprint_selection(keys, case_set_id="y", suite_id="core")
    assert same != fingerprint_selection(keys, case_set_id="x", suite_id="oces")


# --------------------------------------------------------------------------
# manifest isolation between two builds in one process
# --------------------------------------------------------------------------


def test_two_builds_in_one_process_do_not_contaminate_each_others_manifests(tmp_path):
    """The failure this guards against is silent and produces a passing analysis.

    Without the isolating scope, the manifest written for the second build also
    contains every case from the first, so the analysis scores one target's results
    against an oracle set describing another target's cases.
    """
    from attacks import library as attack_library
    from attacks.metadata import scoped_registry

    first_manifest = Path(tmp_path) / "first.json"
    second_manifest = Path(tmp_path) / "second.json"

    with scoped_registry():
        attack_library.build_suite([baseline("alpha-1", "the first sentence")])
        attack_library.write_manifest(str(first_manifest))
    with scoped_registry():
        attack_library.build_suite([baseline("beta-1", "the second sentence")])
        attack_library.write_manifest(str(second_manifest))

    first = set(json.loads(first_manifest.read_text(encoding="utf-8")))
    second = set(json.loads(second_manifest.read_text(encoding="utf-8")))
    assert first and second
    assert not any(case_id.startswith("beta-1") for case_id in first)
    assert not any(case_id.startswith("alpha-1") for case_id in second)


def test_the_runner_builds_inside_the_isolating_scope():
    source = (Path(__file__).resolve().parent.parent / "runner" / "run.py").read_text(
        encoding="utf-8"
    )
    plan = source.split("def plan_run(")[1].split("\ndef ")[0]
    assert "with scoped_registry():" in plan
    build_at = plan.index("build_suite_once(")
    manifest_at = plan.index("library.write_manifest(")
    scope_at = plan.index("with scoped_registry():")
    # Build and manifest are the same isolated build, in that order.
    assert scope_at < build_at < manifest_at


# --------------------------------------------------------------------------
# the CLI, end to end against a mock transport
# --------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Like cli_run, but the caller composes the whole flag list."""
    baselines = [baseline("b01"), baseline("b02", "another clean sentence")]
    attacks = [
        attack("s.malformed.01"),
        attack("b01.encoding.01", baseline_id="b01", category="encoding",
               original_text="i feel great today", attacked_text="I FEEL GREAT TODAY"),
        attack("b02.encoding.01", baseline_id="b02", category="encoding",
               original_text="another clean sentence", attacked_text="ANOTHER CLEAN SENTENCE"),
    ]
    state = {"posts": [], "manifest_writes": 0}
    monkeypatch.setattr(runner_module, "load_baseline", lambda *a, **k: baselines)
    monkeypatch.setattr(runner_module, "build_suite_once", lambda *a, **k: attacks)

    def manifest(path):
        state["manifest_writes"] += 1
        Path(path).write_text('{"case": "manifest"}', encoding="utf-8")
    monkeypatch.setattr(runner_module.library, "write_manifest", manifest)

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        state["posts"].append(bytes(request.content))
        return predict_response()
    monkeypatch.setattr(Runner, "_new_client", lambda runner: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=runner.timeout))

    out = Path(tmp_path) / "out"

    def invoke(*flags):
        return runner_module.main(["--target", TARGET, "--out", str(out),
                                   "--no-tokenizer", *flags])
    return invoke, out, state


def test_cli_target_mode_writes_the_target_scoped_file_names(cli):
    invoke, out, _ = cli
    assert invoke("--target-id", "emotion_v2") == 0
    assert (out / "results.jsonl").is_file()
    assert (out / "run_meta.json").is_file()
    # The legacy names belong to the legacy flag, and are not written too.
    assert not (out / "results_v2.jsonl").exists()


def test_cli_legacy_mode_still_writes_the_legacy_file_names(cli):
    invoke, out, _ = cli
    assert invoke("--version", "v1") == 0
    assert (out / "results_v1.jsonl").is_file()
    assert (out / "run_meta_v1.json").is_file()


def test_cli_records_complete_identity_in_the_meta_file(cli, tmp_path, monkeypatch):
    invoke, out, _ = cli
    # baseline/sentiment_baseline.json is Lamei's and has not landed. Point the
    # runner's repository root at a temporary tree holding a stand-in, so this test
    # checks the metadata the runner writes and does not double as a claim that a
    # real sentiment baseline exists.
    fake_root = Path(tmp_path) / "root"
    (fake_root / "baseline").mkdir(parents=True)
    (fake_root / "baseline" / "sentiment_baseline.json").write_text(
        json.dumps([{"baseline_id": "s01", "text": "a fine film", "label": "POSITIVE",
                     "source": "handwritten"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner_module, "ROOT", fake_root)

    assert invoke("--target-id", "sentiment_v1", "--parent-run-id", "cafef00dbeef") == 0
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))

    assert meta["target_id"] == "sentiment_v1"
    assert meta["task_id"] == "sentiment_2"
    assert meta["suite_id"] == "core"
    assert meta["version"] == "v1"
    assert meta["evaluation_run_id"] == "cafef00dbeef"
    assert meta["run_id"] != meta["evaluation_run_id"]
    assert meta["model"]["model_id"].startswith("distilbert/")
    assert meta["model"]["labels"] == ["NEGATIVE", "POSITIVE"]
    assert len(meta["model"]["revision"]) == 40
    assert meta["baseline"]["path"] == "baseline/sentiment_baseline.json"
    assert len(meta["baseline"]["sha256"]) == 64
    # No case-set file was used, so there is no file hash to record.
    assert meta["fingerprints"]["selection_sha256"] is None
    assert len(meta["fingerprints"]["selected_order_sha256"]) == 64
    assert len(meta["fingerprints"]["results_sha256"]) == 64
    assert meta["registry"]["registry_version"]
    assert "app_commit" in meta["code_provenance"]


def test_cli_rows_carry_the_target_id(cli):
    invoke, out, _ = cli
    assert invoke("--target-id", "emotion_v2") == 0
    rows = read_rows(out / "results.jsonl")
    assert rows and all(row["target_id"] == "emotion_v2" for row in rows)
    assert all(row["suite_id"] == "core" for row in rows)
    assert all(row["request_body_bytes"] > 0 for row in rows)


def test_cli_body_hashes_match_the_captured_wire_bytes(cli):
    invoke, out, state = cli
    assert invoke("--target-id", "emotion_v2") == 0
    rows = read_rows(out / "results.jsonl")
    assert len(rows) == len(state["posts"])
    for row, sent in zip(rows, state["posts"]):
        assert row["request_body_bytes"] == len(sent)
        assert row["request_body_sha256"] == hashlib.sha256(sent).hexdigest()


def test_cli_conflicting_identity_flags_exit_two_without_sending(cli):
    invoke, out, state = cli
    assert invoke("--target-id", "emotion_v2", "--version", "v1") == 2
    assert state["posts"] == []
    assert list(out.iterdir()) == []


def test_cli_unknown_target_exits_two(cli):
    invoke, _, state = cli
    assert invoke("--target-id", "sentiment_v2") == 2
    assert state["posts"] == []


def test_cli_a_frozen_selection_cannot_be_narrowed_by_a_flag(cli, tmp_path):
    invoke, _, state = cli
    selection = write_selection(tmp_path)
    assert invoke("--target-id", "emotion_v2", "--case-set", str(selection),
                  "--limit", "1") == 2
    assert invoke("--target-id", "emotion_v2", "--case-set", str(selection),
                  "--skip", "s.malformed.01") == 2
    assert state["posts"] == []


def test_cli_runs_a_frozen_selection_in_its_order_and_records_the_rest(cli, tmp_path):
    invoke, out, state = cli
    selection = write_selection(
        tmp_path,
        baseline_ids=["b02"],
        attack_ids=["b02.encoding.01"],
        order=["attack:b02.encoding.01", "baseline:b02"],
    )
    assert invoke("--target-id", "emotion_v2", "--case-set", str(selection)) == 0

    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["case_set_id"] == "fx_v1"
    assert meta["case_set"]["sha256"] == runner_module.sha256_file(selection)
    # selection_sha256 is the selection FILE's hash, matching the shape the shared
    # fixtures record (null there for the runs that used no selection file).
    assert meta["fingerprints"]["selection_sha256"] == runner_module.sha256_file(selection)
    assert meta["fingerprints"]["selected_order_sha256"] != meta["fingerprints"]["selection_sha256"]
    assert meta["case_ids"]["selected"] == ["attack:b02.encoding.01", "baseline:b02"]
    # planned is still the whole suite -- a bounded selection does not shrink the
    # suite's identity, it records which part of it was run.
    assert meta["coverage"]["planned"] == 5
    assert meta["coverage"]["selected"] == 2
    assert meta["coverage"]["deselected"] == 3
    assert (meta["coverage"]["selected"] + meta["coverage"]["skipped"]
            + meta["coverage"]["limit_excluded"] + meta["coverage"]["deselected"]
            == meta["coverage"]["planned"])
    # and it was sent in the selection's order, not the default one
    rows = read_rows(out / "results.jsonl")
    assert [row["case_type"] for row in rows] == ["attack", "baseline"]
    assert (out / "case_selection.json").is_file()


def test_cli_a_selection_for_the_wrong_suite_exits_two(cli, tmp_path):
    invoke, _, state = cli
    selection = write_selection(tmp_path, suite_id="oces")
    assert invoke("--target-id", "emotion_v2", "--case-set", str(selection)) == 2
    assert state["posts"] == []


def test_cli_oces_without_an_evaluation_exits_two(cli):
    """The OCES seed file is an evaluation-level override; there is no task default."""
    invoke, _, state = cli
    assert invoke("--target-id", "emotion_v2", "--suite", "oces") == 2
    assert state["posts"] == []


def test_cli_an_evaluation_resolves_the_baseline_file_it_actually_uses(cli):
    invoke, out, _ = cli
    assert invoke("--target-id", "emotion_v1", "--suite", "core",
                  "--evaluation-id", "emotion.core") == 0
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["evaluation_id"] == "emotion.core"
    assert meta["baseline"]["path"] == "baseline/baseline.json"


def test_cli_a_configuration_failure_preserves_the_previous_run(cli):
    invoke, out, _ = cli
    assert invoke("--target-id", "emotion_v2") == 0
    before = {path.name: path.read_bytes() for path in out.iterdir() if path.is_file()}
    assert before

    assert invoke("--target-id", "emotion_v2", "--version", "v1") == 2
    after = {path.name: path.read_bytes() for path in out.iterdir() if path.is_file()}
    assert after == before
    assert not list(out.glob(".runner-*"))


def test_cli_two_targets_write_into_their_own_directories(cli, tmp_path, monkeypatch):
    """Two builds of one evaluation must not share a manifest or a results file."""
    invoke, out, _ = cli
    assert invoke("--target-id", "emotion_v1") == 0
    first = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))

    second_out = Path(tmp_path) / "second"

    def invoke_second(*flags):
        return runner_module.main(["--target", TARGET, "--out", str(second_out),
                                   "--no-tokenizer", *flags])
    assert invoke_second("--target-id", "emotion_v2") == 0
    second = json.loads((second_out / "run_meta.json").read_text(encoding="utf-8"))

    assert first["target_id"] != second["target_id"]
    # Identical planned cases for the paired experiment, separate evidence.
    assert first["fingerprints"]["planned_suite_sha256"] == \
        second["fingerprints"]["planned_suite_sha256"]
    assert first["fingerprints"]["results_sha256"] != first["run_id"]
    assert (out / "manifest.json").read_bytes() == (second_out / "manifest.json").read_bytes()


def test_a_missing_dependency_is_reported_not_worked_around(cli, monkeypatch):
    """A required file that is absent must stop the run, not be worked around.

    This used to rely on Lamei's sentiment baseline genuinely not existing yet. Task 4
    landed baseline/sentiment_baseline.json and Task 2 landed endpoint/sentiment_v1.py,
    so sentiment.core is now fully runnable and the original expectation became false
    on integration -- on either branch alone it still held. The behaviour under test is
    the readiness gate itself, so the absence is now injected rather than borrowed from
    whichever dependency happened to be late: require_runnable raises exactly as it
    would for a real missing file, and the run must abort before sending anything or
    publishing any output.
    """
    invoke, out, state = cli

    # Point the run at a declared baseline file that genuinely is not there. This is
    # the same condition the absent sentiment baseline used to create, and it fails at
    # the same place -- the run hashes the baseline file it is about to read, so a
    # missing dependency surfaces before a single request is sent, rather than being
    # silently substituted or skipped.
    monkeypatch.setattr(
        runner_module, "_resolve_baseline_file",
        lambda resolved: "baseline/does_not_exist_sentiment_baseline.json",
    )

    assert invoke("--target-id", "sentiment_v1") == 2
    assert state["posts"] == []
    assert list(out.iterdir()) == []


def test_sentiment_core_dependencies_are_now_actually_present(cli):
    """The counterpart to the above: with both tasks landed, readiness really passes.

    Guards the other direction -- if a future change broke the sentiment endpoint
    module path or the baseline file, the injected-failure test above would still pass
    while the real evaluation had quietly become unrunnable.
    """
    from endpoint.targets import load_registry, missing_requirements
    assert missing_requirements(load_registry(), "sentiment.core") == []


def test_a_suite_the_attack_library_cannot_build_yet_is_refused(cli):
    """Until CONTRACTS.md 4.2 lands, a non-legacy suite must fail, not mislabel.

    Building the emotion core suite and recording it as a sentiment or OCES suite
    would put the wrong cases behind the right name -- an analysis would then score
    real results against an oracle set for different cases and report nothing wrong.
    """
    import inspect as _inspect
    from attacks import library as attack_library

    if "task_id" in _inspect.signature(attack_library.build_suite).parameters:
        pytest.skip(
            "attacks.library.build_suite now accepts suite/task_id, so this guard "
            "is spent; the forwarding path is exercised by a real OCES run instead"
        )
    from attacks.metadata import scoped_registry

    # Inside the isolating scope: this really builds cases, and they must not be
    # left registered for whatever builds next in this process.
    with scoped_registry():
        # The legacy combination is unaffected and still builds.
        assert build_suite_once([baseline()], None, None) != []
        with pytest.raises(ContractError, match="does not yet accept suite/task_id"):
            build_suite_once([baseline()], None, None, suite="core", task_id="sentiment_2")
        with pytest.raises(ContractError, match="does not yet accept suite/task_id"):
            build_suite_once([baseline()], None, None, suite="oces", task_id="emotion_7")


def test_code_provenance_is_a_commit_or_an_honest_null():
    provenance = code_provenance()
    assert set(provenance) == {"app_commit", "dirty"}
    commit = provenance["app_commit"]
    assert commit is None or (len(commit) == 40 and int(commit, 16) >= 0)


def test_default_send_order_is_baselines_then_standalone_then_derived():
    baselines, attacks = suite()
    units = default_send_order(baselines, attacks)
    kinds = [type(unit).__name__ for unit in units]
    assert kinds[:len(baselines)] == ["BaselineCase"] * len(baselines)
    standalone, derived = partition_attacks(attacks)
    assert units[len(baselines):] == [*standalone, *derived]


@pytest.mark.parametrize("flags", [
    ["--evaluation-id", "ci.emotion"],
    ["--skip", "unknown-case"],
    ["--skip", "s.malformed.01", "--skip", "s.malformed.01"],
])
def test_invalid_selection_is_rejected_before_any_request(cli, flags):
    invoke, out, state = cli
    assert invoke("--target-id", "emotion_v2", *flags) == 2
    assert not state["posts"]
    assert not list(out.iterdir())


def test_cli_serialization_failure_cannot_report_success(cli, monkeypatch):
    invoke, out, state = cli
    def unencodable(self, case, text):
        raise TypeError("cannot encode payload")
    monkeypatch.setattr(Runner, "prepare_request", unencodable)
    assert invoke("--target-id", "emotion_v2") == 2
    assert not state["posts"]
    rows = read_rows(out / "results.jsonl")
    assert rows and all(row["request_body_bytes"] is None for row in rows)
    assert all(row["error"].startswith("serialization_error") for row in rows)
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["termination_reason"] == "errored"


def test_published_configuration_snapshots_match_recorded_hashes(cli, tmp_path):
    invoke, out, _ = cli
    path = write_selection(tmp_path)
    assert invoke("--target-id", "emotion_v2", "--case-set", str(path)) == 0
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert (out / "case_selection.json").read_bytes() == path.read_bytes()
    assert runner_module.sha256_file(out / "registry.json") == meta["registry"]["sha256"]
    assert runner_module.sha256_file(out / "case_selection.json") == meta["fingerprints"]["selection_sha256"]


@pytest.mark.parametrize("field", ["baseline", "attack"])
def test_duplicate_generated_ids_are_rejected(tmp_path, field):
    baselines, attacks = suite()
    if field == "baseline":
        baselines.append(baselines[0])
    else:
        attacks.append(attacks[0])
    selection = load_case_set(write_selection(tmp_path))
    with pytest.raises(SelectionError, match="duplicate"):
        apply_case_set(selection, baselines, attacks)


@pytest.mark.parametrize("overrides", [
    {"selection_version": 0}, {"selection_version": -1},
    {"standalone_attack_ids": ["different"], "derived_attack_ids": []},
])
def test_selection_rejects_invalid_version_or_conflicting_lists(tmp_path, overrides):
    with pytest.raises(SelectionError):
        load_case_set(write_selection(tmp_path, **overrides))


def _paired_plan(tmp_path, **overrides):
    args = runner_module.build_parser().parse_args([
        "--target", TARGET, "--target-id", "emotion_v1", "--no-tokenizer",
    ])
    for key, value in overrides.items():
        setattr(args, key, value)
    staging = tmp_path / ("plan-" + str(len(list(tmp_path.glob("plan-*")))))
    staging.mkdir()
    return args, staging


def test_paired_targets_reuse_one_build_and_exact_manifest(cli, tmp_path):
    _, out, state = cli
    args, staging = _paired_plan(tmp_path)
    plan = runner_module.plan_run(args, out, staging)
    assert runner_module.main([
        "--target", TARGET, "--target-id", "emotion_v2", "--no-tokenizer",
        "--out", str(out),
    ], reuse_plan=plan) == 0
    assert state["manifest_writes"] == 1
    assert (out / "manifest.json").read_bytes() == plan.manifest_bytes
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["case_ids"]["selected"] == plan.selected_keys
    assert meta["fingerprints"]["planned_suite_sha256"] == plan.planned_fingerprint


@pytest.mark.parametrize("change", ["selection", "context", "mutated_cases"])
def test_paired_plan_rejects_changed_context_or_cases(cli, tmp_path, change):
    _, out, state = cli
    args, staging = _paired_plan(tmp_path)
    plan = runner_module.plan_run(args, out, staging)
    args, staging = _paired_plan(tmp_path, target_id="emotion_v2")
    if change == "selection":
        args.limit = 1
    elif change == "context":
        args.no_tokenizer = False
    else:
        plan.baselines[0].text = "changed after planning"
    with pytest.raises((ContractError, SelectionError)):
        runner_module.plan_run(args, out, staging, reuse_plan=plan)
    assert not state["posts"]
    assert state["manifest_writes"] == 1


def test_coverage_map_is_copied_byte_for_byte_and_hashed(cli, tmp_path, monkeypatch):
    invoke, out, _ = cli
    root = tmp_path / "root"
    (root / "attacks").mkdir(parents=True)
    (root / "baseline").mkdir()
    (root / "baseline" / "baseline.json").write_bytes(b"[]")
    content = b'{ "coverage_map_version": "fixture-1" }\r\n'
    (root / "attacks" / "coverage_map.json").write_bytes(content)
    monkeypatch.setattr(runner_module, "ROOT", root)
    assert invoke("--target-id", "emotion_v2") == 0
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    assert (out / "coverage_map.json").read_bytes() == content
    assert meta["coverage_map"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert meta["fingerprints"]["coverage_map_sha256"] == meta["coverage_map"]["sha256"]
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    (root / "attacks" / "coverage_map.json").write_bytes(b"{}")
    assert invoke("--target-id", "emotion_v2") == 2
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def test_missing_declared_coverage_map_fails_readiness(cli, monkeypatch):
    invoke, out, state = cli
    monkeypatch.setattr(runner_module.library, "write_manifest", lambda path:
                        Path(path).write_text('{"a":{"coverage_map_version":"1"}}'))
    assert invoke("--target-id", "emotion_v2") == 2
    assert not state["posts"]
    assert not list(out.iterdir())


def test_wrong_tokenizer_context_is_rejected(monkeypatch):
    from endpoint import loader
    from types import SimpleNamespace
    from endpoint.targets import load_registry
    registry = load_registry()
    context = SimpleNamespace(target_id="emotion_v1", task_id="emotion_7",
                              model_spec=registry.model_for("emotion_v1"), max_tokens=512)
    monkeypatch.setattr(loader, "load_target_tokenizer", lambda *a, **k: context)
    with pytest.raises(ContractError, match="wrong tokenizer context"):
        runner_module.build_token_counter_for_target("sentiment_v1", registry)
