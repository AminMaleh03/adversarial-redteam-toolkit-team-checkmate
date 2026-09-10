"""Tests for the V4 public web deployment layer (web/app.py).

These mock run_all.run_experiment() throughout -- the point of this suite is the web
layer's own behavior (routing, job locking, progress reflection, safe failure handling),
never a real ML experiment. run_all.py's own orchestration/progress-callback behavior is
covered separately in tests/test_run_all.py.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_all  # noqa: E402
import web.app as web_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

RUN_NAME_RE = re.compile(r"^hf_demo_\d{8}_\d{6}_[0-9a-f]{6}$")


@pytest.fixture(autouse=True)
def reset_job_state():
    web_app._reset_state_for_tests()
    yield
    web_app._reset_state_for_tests()


@pytest.fixture
def client():
    return TestClient(web_app.app)


def _wait_until_not_running(client, timeout=2.0):
    deadline = time.monotonic() + timeout
    state = client.get("/api/status").json()
    while state["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        state = client.get("/api/status").json()
    return state


def test_index_returns_branded_welcome_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "Team Checkmate" in body
    assert "RED LAB" in body
    assert "Adversarial Testing Redefined" in body
    assert "Run Live Demo" in body
    assert "Run Live Attack Test" not in body  # old wording fully retired
    assert "Robustness," not in body  # marketing hero copy belongs on / only, not repeated
    assert body.count('src="data:image/png;base64,') == 2  # Team Checkmate logo + Red Lab logo


def test_home_shows_red_lab_version_label(client):
    body = client.get("/").text
    assert "Red Lab v5.0" in body


def test_home_navigation_has_required_links(client):
    body = client.get("/").text
    nav = body[body.index('id="primary-nav"'):body.index("</nav>")]
    assert 'href="/"' in nav  # Home
    assert 'href="#run"' in nav  # Live Demo
    assert nav.count("<a ") >= 2


def test_home_technical_report_link_targets_new_tab(client):
    body = client.get("/").text
    if "Technical Report" not in body:
        pytest.skip("verified_full_report artifact not present in this checkout")
    idx = body.index("Technical Report")
    tag = body[body.rindex("<a", 0, idx):idx]
    assert 'target="_blank"' in tag
    assert 'rel="noopener"' in tag


def test_home_has_mobile_menu_toggle_markup(client):
    body = client.get("/").text
    assert 'id="nav-toggle"' in body
    assert 'aria-expanded="false"' in body
    assert 'aria-controls="primary-nav"' in body


def test_home_hero_has_secondary_cta_to_technical_report_when_available(client):
    body = client.get("/").text
    if "View Technical Report" not in body:
        pytest.skip("verified_full_report artifact not present in this checkout")
    assert 'id="run"' in body


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "team-checkmate-web"}


def test_status_starts_idle(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_start_run_returns_accepted_running_state(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    release = threading.Event()

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        release.wait(timeout=5)
        report_html = tmp_path / run_name / "report" / "report.html"
        report_html.parent.mkdir(parents=True)
        report_html.write_text("<html></html>", encoding="utf-8")
        return {"report_html": report_html}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    try:
        resp = client.post("/api/run")
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "running"
        assert RUN_NAME_RE.match(body["run_name"])
    finally:
        release.set()
        _wait_until_not_running(client)


def test_second_start_during_active_run_returns_same_job_not_a_new_one(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    release = threading.Event()
    calls = []

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        calls.append(run_name)
        release.wait(timeout=5)
        report_html = tmp_path / run_name / "report" / "report.html"
        report_html.parent.mkdir(parents=True)
        report_html.write_text("<html></html>", encoding="utf-8")
        return {"report_html": report_html}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    try:
        first = client.post("/api/run").json()
        second = client.post("/api/run").json()
        assert first["run_name"] == second["run_name"]
        assert len(calls) == 1  # never a second run_experiment() call while one is active
    finally:
        release.set()
        _wait_until_not_running(client)


def test_status_reflects_real_progress_callback_stages(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    release = threading.Event()

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        progress_callback("starting_v1", "Starting V1 endpoint")
        release.wait(timeout=5)
        progress_callback("attacking_v2", "Testing hardened endpoint")
        report_html = tmp_path / run_name / "report" / "report.html"
        report_html.parent.mkdir(parents=True)
        report_html.write_text("<html></html>", encoding="utf-8")
        return {"report_html": report_html}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    client.post("/api/run")
    deadline = time.monotonic() + 2.0
    state = client.get("/api/status").json()
    while state.get("stage") != "starting_v1" and time.monotonic() < deadline:
        time.sleep(0.02)
        state = client.get("/api/status").json()
    assert state["stage"] == "starting_v1"
    assert state["stage_index"] == web_app.STAGE_ORDER.index("starting_v1")
    release.set()
    _wait_until_not_running(client)


def test_successful_job_exposes_generated_report_url(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    run_dir = tmp_path / "hf_demo_test" / "report"
    run_dir.mkdir(parents=True)
    report_html = run_dir / "report.html"
    report_html.write_text("<html></html>", encoding="utf-8")

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        return {"report_html": report_html}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    client.post("/api/run")
    state = _wait_until_not_running(client)
    assert state["status"] == "complete"
    assert state["result_url"] == "/results/hf_demo_test/report/report.html"


def test_failed_job_exposes_safe_message_not_a_traceback(monkeypatch, client):
    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        raise RuntimeError("V1 endpoint did not answer /health: connection refused at 127.0.0.1:8000")

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    client.post("/api/run")
    state = _wait_until_not_running(client)
    assert state["status"] == "failed"
    assert "127.0.0.1" not in state["error"]
    assert "Traceback" not in state["error"]
    assert state["error"]  # a concise public message is still present


def test_home_page_has_no_unverified_timing_promise(client):
    body = client.get("/").text
    assert "Takes under a minute" not in body
    assert "in one minute" not in body


def test_static_css_has_no_automatic_dark_mode_override(client):
    resp = client.get("/static/app.css")
    assert resp.status_code == 200
    assert "prefers-color-scheme" not in resp.text


def test_static_css_still_defines_red_lab_tokens(client):
    body = client.get("/static/app.css").text
    for token in ("--rl-red", "--rl-charcoal", "--rl-paper", "--rl-surface", "--rl-muted", "--rl-border"):
        assert token in body


def test_results_analysis_json_opens_inline_not_as_attachment(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    run_dir = tmp_path / "hf_demo_test" / "report"
    run_dir.mkdir(parents=True)
    (run_dir / "analysis.json").write_text('{"schema_version": 2}', encoding="utf-8")

    resp = client.get("/results/hf_demo_test/report/analysis.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json; charset=utf-8"
    assert "content-disposition" not in resp.headers
    assert resp.json() == {"schema_version": 2}


def test_results_analysis_json_blocks_path_traversal(monkeypatch, client, tmp_path):
    results_root = tmp_path / "results"
    results_root.mkdir()
    monkeypatch.setattr(run_all, "RESULTS_ROOT", results_root)
    secret = tmp_path / "secret.json"
    secret.write_text('{"leak": true}', encoding="utf-8")

    resp = client.get("/results/%2e%2e/report/analysis.json")
    assert resp.status_code == 404
    assert "leak" not in resp.text


def test_results_analysis_json_missing_run_returns_404(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    resp = client.get("/results/does-not-exist/report/analysis.json")
    assert resp.status_code == 404
    assert "content-disposition" not in resp.headers


def test_verified_full_analysis_json_opens_inline_not_as_attachment(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "VERIFIED_FULL_REPORT_DIR", tmp_path)
    (tmp_path / "analysis.json").write_text('{"ok": true}', encoding="utf-8")

    resp = client.get("/verified-full/analysis.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json; charset=utf-8"
    assert "content-disposition" not in resp.headers
    assert resp.json() == {"ok": True}


def test_new_run_allowed_after_previous_job_completes(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        report_html = tmp_path / run_name / "report" / "report.html"
        report_html.parent.mkdir(parents=True)
        report_html.write_text("<html></html>", encoding="utf-8")
        return {"report_html": report_html}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    client.post("/api/run")
    _wait_until_not_running(client)
    resp = client.post("/api/run")
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"
    _wait_until_not_running(client)
