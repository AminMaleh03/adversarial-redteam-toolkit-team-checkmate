"""Tests for the V4 public web deployment layer (web/app.py).

These mock run_all.run_experiment() throughout -- the point of this suite is the web
layer's own behavior (routing, job locking, progress reflection, safe failure handling),
never a real ML experiment. run_all.py's own orchestration/progress-callback behavior is
covered separately in tests/test_run_all.py.
"""

from __future__ import annotations

import hashlib
import json
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
    assert "Red Lab v6.2" in body


def test_active_pages_use_centralized_version_source_not_a_hardcoded_string(client):
    # v6.1: home, lab and generated report pages must all read the same PRODUCT_VERSION_LABEL
    # constant rather than each carrying its own copy of the string.
    from report.generate import PRODUCT_VERSION_LABEL
    assert PRODUCT_VERSION_LABEL == "Red Lab v6.2"
    home_body = client.get("/").text
    lab_body = client.get("/lab").text
    assert PRODUCT_VERSION_LABEL in home_body
    assert PRODUCT_VERSION_LABEL in lab_body
    # The archived, byte-frozen v5 report must not be affected by the active version bump.
    assert "Red Lab v5.0" not in home_body
    assert "Red Lab v5.0" not in lab_body


def test_home_navigation_has_required_links(client):
    body = client.get("/").text
    nav = body[body.index('id="primary-nav"'):body.index("</nav>")]
    assert 'href="/"' in nav  # Home
    assert 'href="#run"' in nav  # Live Demo
    assert 'href="/lab"' in nav  # Try Your Own Input (System V5.4)
    assert nav.count("<a ") >= 3


def test_home_technical_report_link_preserves_page_history(client):
    body = client.get("/").text
    if "Technical Report" not in body:
        pytest.skip("verified_full_report artifact not present in this checkout")
    idx = body.index("Technical Report")
    tag = body[body.rindex("<a", 0, idx):idx]
    assert 'target="_blank"' not in tag
    assert 'href="/verified-full/report.html"' in tag


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


# ------------------------------------------------------------------------------------------
# System V5.2: dedicated full-screen live-demo execution view.
#
# The execution state machine itself lives in web/static/app.js (vanilla JS, no test
# runner in this repo) -- these tests check the server-rendered contract app.js depends on
# (the two mutually-exclusive views, real stage data, progressbar semantics) plus, for the
# JS behavior itself, that the served script still wires up the same real endpoints and
# view-toggling logic rather than re-deriving state client-side. They deliberately avoid
# asserting exact HTML strings or CSS layout, per the V5.2 brief.
# ------------------------------------------------------------------------------------------


def test_home_initially_shows_landing_view_only(client):
    body = client.get("/").text
    assert 'id="view-home"' in body
    home_hidden = body[body.index('id="view-home"') - 40:body.index('id="view-home"')]
    assert "hidden" not in home_hidden
    exec_start = body.index('id="view-execution"')
    exec_tag = body[body.rindex("<section", 0, exec_start):body.index(">", exec_start) + 1]
    assert "hidden" in exec_tag


def _extract_json_script(body, element_id):
    start = body.index(f'id="{element_id}"')
    open_tag_end = body.index(">", start) + 1
    close = body.index("</script>", open_tag_end)
    return json.loads(body[open_tag_end:close])


def test_execution_view_descriptor_has_real_stage_labels(client):
    # v6.1 Phase 2: the stage list is generated client-side from demo-descriptors, not
    # server-rendered <li data-stage> markup -- assert against the embedded descriptor instead.
    body = client.get("/").text
    emotion = _extract_json_script(body, "demo-descriptors")["emotion.core"]
    assert emotion["kind"] == "paired"
    labels = {s["id"]: s["label"] for s in emotion["stages"]}
    assert labels["starting_v1"] == "Starting V1"
    assert labels["attacking_v1"] == "Attacking unhardened endpoint"
    assert labels["starting_v2"] == "Starting V2"
    assert labels["attacking_v2"] == "Testing hardened endpoint"
    for entry in emotion["stages"]:
        assert entry["maps_to"] in emotion["stage_order"]


def test_execution_view_has_progressbar_accessibility_semantics(client):
    body = client.get("/").text
    idx = body.index('id="progress-bar"')
    tag = body[body.rindex("<div", 0, idx):body.index(">", idx) + 1]
    assert 'role="progressbar"' in tag
    assert 'aria-valuemin="0"' in tag
    assert 'aria-valuemax="100"' in tag
    assert 'aria-valuenow="0"' in tag


def test_execution_view_has_v1_v2_context_and_same_model_note(client):
    body = client.get("/").text
    emotion = _extract_json_script(body, "demo-descriptors")["emotion.core"]
    titles = " ".join(c["title"] for c in emotion["cards"])
    assert "V1" in titles and "Unhardened Endpoint" in titles
    assert "V2" in titles and "Hardened Endpoint" in titles
    assert emotion["same_model_note"] == "Two endpoint configurations"
    assert "Same underlying AI model" in emotion["footer_note"]


def test_sentiment_demo_descriptor_is_single_target_with_no_paired_content(client):
    # v6.1 Phase 2: sentiment.core must render a single configured-target card, no V1/V2
    # cards, no "Two endpoint configurations", and no hardening-improvement language.
    body = client.get("/").text
    sentiment = _extract_json_script(body, "demo-descriptors")["sentiment.core"]
    assert sentiment["kind"] == "single"
    assert len(sentiment["cards"]) == 1
    card = sentiment["cards"][0]
    assert card["lane"] == "target"
    assert "Sentiment" in card["title"] and "Configured Target" in card["title"]
    assert "sentiment_v1" in card["note"]
    assert sentiment["same_model_note"] is None
    blob = json.dumps(sentiment)
    for forbidden in (
        "V1 — Unhardened Endpoint", "V2 — Hardened Endpoint",
        "Two endpoint configurations", "Starting V1", "Attacking unhardened endpoint",
        "Starting V2", "Testing hardened endpoint", "Analyzing differences",
    ):
        assert forbidden not in blob


def test_execution_view_has_no_fake_cancel_button(client):
    body = client.get("/").text
    exec_section = body[body.index('id="view-execution"'):body.index("</section>", body.index('id="view-execution"'))]
    assert "cancel" not in exec_section.lower()


def test_execution_view_has_retry_and_home_on_failure(client):
    body = client.get("/").text
    failure_section = body[body.index('id="exec-failure"'):body.index("</div>", body.index('id="exec-failure"'))]
    assert 'id="retry-btn"' in failure_section
    assert "Retry Live Demo" in failure_section
    assert 'href="/"' in failure_section
    assert "Back to Red Lab" in failure_section


# ------------------------------------------------------------------------------------------
# System V5.4 final integration: native-style Back navigation + sequential-run regression.
# ------------------------------------------------------------------------------------------


def test_home_view_has_no_native_back_action(client):
    # Home is the only surface that should not show a native Back control -- scoped strictly
    # to #view-home (the execution view, sharing this same page/URL, does carry one).
    body = client.get("/").text
    home_section = body[body.index('id="view-home"'):body.index('id="view-execution"')]
    assert 'id="exec-back"' not in home_section
    assert 'class="rl-back-btn' not in home_section


def test_demo_execution_back_lives_in_outer_chrome(client):
    body = client.get("/").text
    header = body[body.index('<header'):body.index('</header>')]
    assert 'id="exec-back" class="rl-back-btn" aria-label="Back" title="Back" hidden' in header
    assert header.index('id="exec-back"') < header.index('class="masthead-inner"')


def test_app_js_back_uses_shared_history_fallback_behavior(client):
    assert '/static/chrome.js' in client.get("/").text
    js = client.get("/static/chrome.js").text
    assert 'window.history.back()' in js
    assert 'window.history.length > 1' in js
    assert 'new URL(document.referrer).origin === window.location.origin' in js
    assert 'querySelectorAll(".rl-back-btn")' in js


def test_home_page_links_to_v54_live_red_team_lab(client):
    # System V5.4: "Try Your Own Input" now exists, as a link to the dedicated /lab page --
    # the home page itself still carries no <textarea> or inline Lab form (brief section 4:
    # "Do NOT place the entire textarea/form directly in the homepage hero").
    body = client.get("/").text
    assert "Try Your Own Input" in body
    assert 'href="/lab"' in body
    assert "<textarea" not in body


def test_app_js_still_uses_the_existing_run_and_status_endpoints(client):
    js = client.get("/static/app.js").text
    assert '"/api/run"' in js
    assert '"/api/status"' in js
    # No second source of truth for the run's own runner/scoring/report logic client-side.
    assert "run_experiment" not in js
    assert "analysis" not in js.lower()


def test_app_js_switches_view_on_run_and_reattach(client):
    js = client.get("/static/app.js").text
    assert "activateExecutionView" in js
    assert "viewHome.hidden = true" in js
    assert "viewExecution.hidden = false" in js
    # Reattachment: only a currently-running job pulls a fresh visitor into the execution
    # view; complete/failed/idle states leave the landing page as the default (System V4/V5.2).
    assert 'state.status === "running"' in js


def test_app_js_uses_backend_result_url_for_completion_redirect(client):
    js = client.get("/static/app.js").text
    assert "state.result_url" in js
    assert "window.location.replace(state.result_url)" in js
    assert "COMPLETE_REDIRECT_DELAY_MS" not in js


def test_app_js_has_no_cancel_handler(client):
    js = client.get("/static/app.js").text
    assert "cancel" not in js.lower()


def test_static_css_guarantees_hidden_attribute_wins_the_cascade(client):
    # The actual root cause of the V5.2 "execution view visible on home" bug: an author rule
    # with a `display` value (`.execution-view { display: flex }`) has the same specificity
    # as the UA stylesheet's `[hidden] { display: none }` and wins the cascade regardless of
    # source order. This global, `!important` safeguard is the fix -- assert it stays present.
    css = client.get("/static/app.css").text
    assert "[hidden]" in css
    assert "display: none !important" in css


def test_home_nav_marks_home_as_current_page(client):
    body = client.get("/").text
    nav = body[body.index('id="primary-nav"'):body.index("</nav>")]
    assert 'aria-current="page"' in nav


def test_home_page_has_no_container_internals_wording(client):
    body = client.get("/").text
    assert "inside this container" not in body


def test_app_js_completion_replaces_transient_execution(client):
    body = client.get("/").text
    js = client.get("/static/app.js").text
    # Exactly one exec-heading element server-side -- no separate, smaller completion element.
    assert body.count('id="exec-heading"') == 1
    assert 'execHeading.textContent = "Experiment complete"' not in js
    assert "window.location.replace(state.result_url)" in js


def test_app_js_nav_live_demo_reuses_start_run_not_duplicated(client):
    js = client.get("/static/app.js").text
    assert "goToLiveDemo" in js
    assert "else startRun()" in js
    assert "navLiveDemo.addEventListener" in js
    assert "event.preventDefault()" in js


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "team-checkmate-web"}


def test_status_starts_idle(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_targets_api_exposes_only_trusted_core_choices(client):
    body = client.get("/api/targets").json()
    assert [item["target_id"] for item in body["targets"]] == [
        "emotion_v1", "emotion_v2", "sentiment_v1",
    ]
    assert [item["evaluation_id"] for item in body["evaluations"]] == [
        "emotion.core", "sentiment.core",
    ]
    assert all("url" not in item for item in body["targets"])


def test_unknown_target_uses_frozen_422_shape(client):
    response = client.post("/api/run", json={"target_id": "gpt_v9"})
    assert response.status_code == 422
    assert response.json() == {
        "detail": [{
            "loc": ["body", "target_id"],
            "msg": "unknown target_id 'gpt_v9'; configured: ['emotion_v1', 'emotion_v2', 'sentiment_v1']",
            "type": "value_error.unknown_target",
        }]
    }


def test_sentiment_demo_carries_identity_and_calls_selected_evaluation(monkeypatch, client, tmp_path):
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    called = {}

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **kwargs):
        called.update(mode=mode, **kwargs)
        report = tmp_path / run_name / "report"
        report.mkdir(parents=True)
        (report / "report.html").write_text("ok", encoding="utf-8")
        (report / "analysis.json").write_text("{}", encoding="utf-8")
        return {"report_html": report / "report.html", "analysis_json": report / "analysis.json"}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    started = client.post("/api/run", json={"evaluation_id": "sentiment.core"})
    assert started.status_code == 202
    body = started.json()
    assert body["run_id"] and body["evaluation_id"] == "sentiment.core"
    assert body["target_ids"] == ["sentiment_v1"]
    final = _wait_until_not_running(client)
    assert final["state"] == "complete"
    assert final["report_url"].endswith("/report/report.html")
    assert called["mode"] == "demo"
    assert called["evaluation_ids"] == ["sentiment.core"]


def test_frontend_discards_stale_run_or_evaluation_status(client):
    js = client.get("/static/app.js").text
    assert "state.run_id !== activeRunId" in js
    assert "state.evaluation_id !== activeEvaluationId" in js
    assert 'body: JSON.stringify({ evaluation_id: activeEvaluationId, mode: "demo" })' in js


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


def test_second_start_during_active_run_returns_contract_busy(monkeypatch, client, tmp_path):
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
        second_response = client.post("/api/run")
        second = second_response.json()
        assert second_response.status_code == 409
        assert second == {"detail": "A run is already in progress.", "run_id": first["run_id"]}
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
    paired_stage_order = web_app._demo_descriptor("emotion.core", [])["stage_order"]
    assert state["stage_index"] == paired_stage_order.index("starting_v1")
    release.set()
    _wait_until_not_running(client)


def test_sentiment_status_uses_single_target_stage_alias_not_paired(monkeypatch, client, tmp_path):
    # v6.1 Phase 2: the raw orchestration stage for a single-target run ("starting_sentiment_v1")
    # must resolve into the single-target descriptor's own stage id, never the paired "starting_v1".
    monkeypatch.setattr(run_all, "RESULTS_ROOT", tmp_path)
    release = threading.Event()

    def fake_run_experiment(mode, run_name=None, progress_callback=None, **_):
        progress_callback("starting_sentiment_v1", "Starting sentiment endpoint")
        release.wait(timeout=5)
        report_html = tmp_path / run_name / "report" / "report.html"
        report_html.parent.mkdir(parents=True)
        report_html.write_text("<html></html>", encoding="utf-8")
        return {"report_html": report_html}

    monkeypatch.setattr(run_all, "run_experiment", fake_run_experiment)
    client.post("/api/run", json={"evaluation_id": "sentiment.core"})
    deadline = time.monotonic() + 2.0
    state = client.get("/api/status").json()
    while state.get("stage") != "starting_target" and time.monotonic() < deadline:
        time.sleep(0.02)
        state = client.get("/api/status").json()
    assert state["stage"] == "starting_target"
    single_stage_order = web_app._demo_descriptor("sentiment.core", ["sentiment_v1"])["stage_order"]
    assert state["stage_index"] == single_stage_order.index("starting_target")
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


def test_static_css_masthead_tokens_match_report_stylesheet(client):
    # System V5.4 navbar unification: the web app and the report stylesheet must share the
    # same masthead height/width/padding tokens (see report/style.css's mirrored block).
    app_css = client.get("/static/app.css").text
    report_css = (ROOT / "report" / "style.css").read_text(encoding="utf-8")
    assert "--rl-nav-height: 84px" in app_css
    assert "--rl-nav-height: 84px" in report_css
    assert "--rl-masthead-width: 1160px" in app_css
    assert "--rl-masthead-width: 1160px" in report_css
    assert "--rl-masthead-pad-x: 32px" in app_css
    assert "--rl-masthead-pad-x: 32px" in report_css


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


# ------------------------------------------------------------------------------------------
# System V5.5 release-candidate polish: design-contract checks.
# ------------------------------------------------------------------------------------------


def test_home_page_has_landing_background_canvas_and_particles_script(client):
    body = client.get("/").text
    assert 'id="rl-bg-canvas"' in body
    assert '<script src="/static/particles.js">' in body
    # The canvas lives inside #view-home only -- never inside the execution view.
    home_section = body[body.index('id="view-home"'):body.index('id="view-execution"')]
    assert 'id="rl-bg-canvas"' in home_section


def test_particles_script_respects_reduced_motion_and_is_self_contained(client):
    js = client.get("/static/particles.js").text
    assert "prefers-reduced-motion" in js
    # Never runs its animation loop (requestAnimationFrame) when reduced motion is on --
    # only the one-shot static render path does.
    assert "requestAnimationFrame" in js
    assert "draw(0)" in js
    assert "!media.matches" in js
    # No dependency on app.js/lab.js globals -- fully self-contained (brief: no new library).
    assert "getElementById(\"rl-bg-canvas\")" in js


def test_app_css_reduced_motion_keeps_static_texture_without_animation():
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "animation: none !important" in css
    assert "transition: none !important" in css
    assert "#rl-bg-canvas { display: none; }" not in css


def test_app_css_masthead_has_frosted_backdrop_filter():
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert "backdrop-filter: blur" in css
    assert "@supports (backdrop-filter: blur(1px))" in css  # graceful fallback, not required


def test_back_buttons_share_circular_component_with_accessible_label(client):
    for path in ("/", "/lab"):
        body = client.get(path).text
        header = body[body.index('<header'):body.index('</header>')]
        assert 'class="rl-back-btn" aria-label="Back" title="Back"' in header
        assert header.index('class="rl-back-btn"') < header.index('class="masthead-inner"')


def test_app_css_rl_back_btn_is_circular_and_focus_visible():
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    rule = css[css.index(".rl-back-btn {"):css.index(".rl-back-btn {") + 600]
    assert "border-radius: 50%" in rule
    assert "width: 40px" in rule and "height: 40px" in rule
    assert ":focus-visible" in css.split(".rl-back-btn {", 1)[1][:700]


def test_version_card_v1_v2_are_distinguished_by_text_and_color_not_color_alone():
    # v6.1 Phase 2: the V1/V2 card titles now come from the paired descriptor (web/app.py),
    # not static template text -- the template only carries an empty skeleton container.
    emotion = web_app._demo_descriptor("emotion.core", ["emotion_v1", "emotion_v2"])
    titles = " ".join(c["title"] for c in emotion["cards"])
    assert "Unhardened Endpoint" in titles
    assert "Hardened Endpoint" in titles
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".version-card.v1 { border-left-color: var(--rl-danger)" in css
    assert ".version-card.v2 { border-left-color: var(--rl-success)" in css


def test_verified_full_served_bytes_match_recorded_evidence_hashes(client):
    """The served evidence must hash to the values recorded in export_meta.json.

    A deployment snapshot that normalises line endings changes analysis.json's bytes
    without changing its content, which silently invalidates the published SHA-256.
    """
    meta_path = run_all.VERIFIED_FULL_REPORT_DIR / "export_meta.json"
    if not meta_path.exists():
        pytest.skip("verified_full_report artifact not present in this checkout")
    recorded = json.loads(meta_path.read_text(encoding="utf-8"))["files"]

    for name in ("analysis.json", "report.pdf"):
        resp = client.get(f"/verified-full/{name}")
        assert resp.status_code == 200
        assert hashlib.sha256(resp.content).hexdigest() == recorded[name], name
