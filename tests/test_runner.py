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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest

from contract import AttackCase, BaselineCase
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
