"""Tests for the Live Red-Team Lab / "Try Your Own Input" feature (web/lab.py, System V5.4).

Mocking boundary mirrors tests/test_web.py: concurrency/security tests monkeypatch
web.lab.run_custom_lab() itself (the same level test_web.py mocks run_all.run_experiment at),
never spawning real V1/V2 subprocesses. Pipeline/metrics/privacy tests call run_custom_lab()
directly with run_all.start_endpoint and web.lab.send_case monkeypatched to canned,
deterministic RunResult fixtures -- no real network calls anywhere in this file.
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
import web.lab as lab_module  # noqa: E402
from attacks import metadata as attack_metadata  # noqa: E402
from baseline.load import load_baseline  # noqa: E402
from contract import AttackCase, BaselineCase, RunResult  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")


@pytest.fixture(autouse=True)
def reset_job_state():
    web_app._reset_state_for_tests()
    lab_module._reset_state_for_tests()
    yield
    web_app._reset_state_for_tests()
    lab_module._reset_state_for_tests()


@pytest.fixture
def client():
    return TestClient(web_app.app)


def _wait_until_lab_not_running(client, timeout=2.0):
    deadline = time.monotonic() + timeout
    job_id = lab_module._lab_state.get("job_id")
    if not job_id:
        return {"status": "idle"}
    state = client.get(f"/api/lab/status/{job_id}").json()
    while state.get("status") == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        state = client.get(f"/api/lab/status/{job_id}").json()
    return state


def _fake_run_result(*, version, case, label="joy", confidence=0.9, status_code=200,
                     all_scores=None) -> RunResult:
    scores = all_scores or {
        "anger": 0.02, "disgust": 0.02, "fear": 0.02, "joy": confidence,
        "neutral": max(0.0, 1 - confidence - 0.08), "sadness": 0.02, "surprise": 0.02,
    }
    return RunResult(
        case_type="baseline" if case is None else "attack",
        attack_id=None if case is None else case.attack_id,
        baseline_id="lab.fixture",
        category=None if case is None else case.category,
        version=version, status_code=status_code, response_body="{}", error=None,
        label=label, confidence=confidence, all_scores=scores,
        latency_ms=12.0, latency_band="normal", endpoint_alive_after=True,
    )


# ------------------------------------------------------------------------------------------
# /lab route + form
# ------------------------------------------------------------------------------------------


def test_lab_route_returns_200_with_labelled_textarea(client):
    resp = client.get("/lab")
    assert resp.status_code == 200
    body = resp.text
    assert '<textarea id="lab-text"' in body
    assert 'for="lab-text"' in body
    assert f'maxlength="{lab_module.MAX_INPUT_CHARS}"' in body
    assert "Live Red-Team Lab" in body


def test_lab_page_states_same_underlying_model(client):
    body = client.get("/lab").text
    assert "Same underlying AI model" in body


def test_lab_page_has_ephemeral_disclaimer(client):
    body = client.get("/lab").text
    assert "session-only" in body


def test_home_page_advertises_try_your_own_input(client):
    body = client.get("/").text
    assert "Try Your Own Input" in body
    assert 'href="/lab"' in body


# ------------------------------------------------------------------------------------------
# Server-side input validation
# ------------------------------------------------------------------------------------------


def test_empty_input_rejected(client):
    resp = client.post("/api/lab/run", json={"text": ""})
    assert resp.status_code == 422


def test_whitespace_only_input_rejected(client):
    resp = client.post("/api/lab/run", json={"text": "   \n\t  "})
    assert resp.status_code == 422


def test_oversized_input_rejected(client):
    resp = client.post("/api/lab/run", json={"text": "a" * (lab_module.MAX_INPUT_CHARS + 1)})
    assert resp.status_code == 422


def test_missing_text_field_rejected(client):
    resp = client.post("/api/lab/run", json={})
    assert resp.status_code == 422


def test_non_string_text_rejected(client):
    resp = client.post("/api/lab/run", json={"text": 12345})
    assert resp.status_code == 422


# ------------------------------------------------------------------------------------------
# lab.js source-level safety: no raw innerHTML of user-influenced text
# ------------------------------------------------------------------------------------------


def test_lab_js_only_sets_innerhtml_for_the_two_trusted_diff_fields(client):
    js = client.get("/static/lab.js").text
    innerhtml_targets = re.findall(r"(\w+)\.innerHTML\s*=\s*variant\.(\w+)", js)
    assert innerhtml_targets, "expected at least one trusted innerHTML assignment"
    for _element, field in innerhtml_targets:
        assert field in ("diff_original_html", "diff_attacked_html")
    # every other textual field must be assigned via textContent somewhere in the file
    assert ".textContent" in js
    assert "sessionStorage.setItem" in js
    assert "localStorage.setItem" not in js  # per-tab only (brief section 10)
    assert "localStorage.getItem" not in js


# ------------------------------------------------------------------------------------------
# Job id security (brief sections 8-10)
# ------------------------------------------------------------------------------------------


def test_job_id_is_unpredictable_token(monkeypatch, client, tmp_path):
    release = threading.Event()

    def fake_run_custom_lab(job_id, text, progress_callback):
        release.wait(timeout=5)
        return {"original_text": text, "v1_clean": {}, "v2_clean": {}, "variants": [], "summary": {}}

    monkeypatch.setattr(lab_module, "run_custom_lab", fake_run_custom_lab)
    try:
        resp = client.post("/api/lab/run", json={"text": "hello there"})
        assert resp.status_code == 202
        body = resp.json()
        assert JOB_ID_RE.match(body["job_id"])
    finally:
        release.set()
        _wait_until_lab_not_running(client)


def test_status_requires_matching_job_id_and_never_leaks_another_jobs_text(monkeypatch, client):
    release = threading.Event()
    secret_text = "this is the private judge input"

    def fake_run_custom_lab(job_id, text, progress_callback):
        release.wait(timeout=5)
        return {"original_text": text, "v1_clean": {}, "v2_clean": {}, "variants": [], "summary": {}}

    monkeypatch.setattr(lab_module, "run_custom_lab", fake_run_custom_lab)
    try:
        started = client.post("/api/lab/run", json={"text": secret_text}).json()
        real_job_id = started["job_id"]

        wrong = client.get("/api/lab/status/not-a-real-job-id")
        assert wrong.status_code == 404
        assert secret_text not in wrong.text

        correct = client.get(f"/api/lab/status/{real_job_id}")
        assert correct.status_code == 200
        assert correct.json()["status"] == "running"
    finally:
        release.set()
        _wait_until_lab_not_running(client)


def test_invalid_status_id_returns_generic_not_found_when_idle(client):
    resp = client.get("/api/lab/status/nothing-has-ever-run")
    assert resp.status_code == 404
    assert resp.json() == {"status": "not_found"}


# ------------------------------------------------------------------------------------------
# Shared global job lock (brief section 9)
# ------------------------------------------------------------------------------------------


def test_second_lab_submission_while_active_returns_busy_without_leaking_data(monkeypatch, client):
    release = threading.Event()
    secret_text = "first judge's private sentence"

    def fake_run_custom_lab(job_id, text, progress_callback):
        release.wait(timeout=5)
        return {"original_text": text, "v1_clean": {}, "v2_clean": {}, "variants": [], "summary": {}}

    monkeypatch.setattr(lab_module, "run_custom_lab", fake_run_custom_lab)
    try:
        first = client.post("/api/lab/run", json={"text": secret_text})
        assert first.status_code == 202
        second = client.post("/api/lab/run", json={"text": "someone else's sentence"})
        assert second.status_code == 409
        assert second.json() == {"status": "busy"}
        assert secret_text not in second.text
    finally:
        release.set()
        _wait_until_lab_not_running(client)


def test_lab_run_busy_while_demo_running(monkeypatch, client):
    web_app._job_state.update(status="running")
    try:
        resp = client.post("/api/lab/run", json={"text": "hello"})
        assert resp.status_code == 409
        assert resp.json() == {"status": "busy"}
    finally:
        web_app._reset_state_for_tests()


def test_demo_run_busy_while_lab_running(client):
    lab_module._lab_state.update(status="running", job_id="fixture-job")
    try:
        resp = client.post("/api/run")
        assert resp.status_code == 409
        assert resp.json() == {"status": "busy"}
    finally:
        lab_module._reset_state_for_tests()


def test_demo_vs_demo_busy_behavior_unaffected(monkeypatch, client, tmp_path):
    # Regression guard: the pre-existing demo-vs-demo reattachment behavior (202 + same
    # run_name) must be untouched by the shared-lock change.
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
        assert len(calls) == 1
    finally:
        release.set()


# ------------------------------------------------------------------------------------------
# Attack selection (brief section 13)
# ------------------------------------------------------------------------------------------

_DISALLOWED_SUBFAMILY_MARKERS = ("type_confusion", "oversized", "deeply_nested", "over_limit")


def test_custom_lab_attacks_selection_is_deterministic():
    baseline_a = lab_module.build_lab_baseline("I am so happy about this result today", "jobA")
    baseline_b = lab_module.build_lab_baseline("I am so happy about this result today", "jobA")
    ids_a = [case.attack_id for case, _label, _desc in lab_module.select_lab_variants(baseline_a)]
    ids_b = [case.attack_id for case, _label, _desc in lab_module.select_lab_variants(baseline_b)]
    assert ids_a == ids_b
    assert 6 <= len(ids_a) <= 10


def test_custom_lab_attacks_excludes_resource_heavy_and_is_raw_cases():
    for family, subfamily, _dose, _position, _label, _desc in lab_module.CUSTOM_LAB_ATTACKS:
        assert family not in ("malformed", "boundary")
        for marker in _DISALLOWED_SUBFAMILY_MARKERS:
            assert marker not in subfamily


def test_custom_lab_attacks_genuinely_derive_from_arbitrary_text():
    baseline = lab_module.build_lab_baseline(
        "The quick fox jumped over something unusual near the old bridge", "jobC",
    )
    variants = lab_module.select_lab_variants(baseline)
    assert variants
    for case, _label, _desc in variants:
        assert case.original_text == baseline.text
        assert case.attacked_text != baseline.text
        assert case.baseline_id == baseline.baseline_id


def test_custom_lab_attacks_short_input_still_yields_variants():
    baseline = lab_module.build_lab_baseline("I am glad", "jobD")
    variants = lab_module.select_lab_variants(baseline)
    assert len(variants) >= 6  # truncation.signal_head_only needs >=4 words and may be absent


# ------------------------------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------------------------------


def test_total_variation_distance_identity_is_zero():
    p = {"joy": 0.7, "anger": 0.3}
    assert lab_module.total_variation_distance(p, dict(p)) == 0.0


def test_total_variation_distance_matches_formula():
    p = {"joy": 0.6, "anger": 0.4}
    q = {"joy": 0.2, "anger": 0.8}
    expected = 0.5 * (abs(0.6 - 0.2) + abs(0.4 - 0.8))
    assert lab_module.total_variation_distance(p, q) == round(expected, 6)


def test_total_variation_distance_range_is_zero_to_one():
    p = {"joy": 1.0}
    q = {"anger": 1.0}
    result = lab_module.total_variation_distance(p, q)
    assert 0.0 <= result <= 1.0


def test_total_variation_distance_none_when_missing_prediction():
    assert lab_module.total_variation_distance(None, {"joy": 1.0}) is None
    assert lab_module.total_variation_distance({"joy": 1.0}, None) is None


def test_label_flipped_none_when_missing_prediction():
    clean = _fake_run_result(version="v1", case=None, label=None)
    attacked = _fake_run_result(version="v1", case=None, label="joy")
    assert lab_module.label_flipped(clean, attacked) is None


# ------------------------------------------------------------------------------------------
# Diagnosis (brief section 17) -- one fixture per rule
# ------------------------------------------------------------------------------------------

_FIXTURE_CASE = AttackCase(attack_id="lab.fixture.perturbation.keyboard_typo",
                           baseline_id="lab.fixture", category="perturbation",
                           original_text="I am happy", attacked_text="I am hsppy")


def test_diagnosis_mitigated_by_v2():
    v1_clean = _fake_run_result(version="v1", case=None, label="joy")
    v1_attacked = _fake_run_result(version="v1", case=_FIXTURE_CASE, label="anger")  # flipped
    v2_clean = _fake_run_result(version="v2", case=None, label="joy")
    v2_attacked = _fake_run_result(version="v2", case=_FIXTURE_CASE, label="joy")  # no flip
    code, remediation = lab_module.diagnose(v1_clean, v1_attacked, v2_clean, v2_attacked)
    assert code == "MITIGATED_BY_V2"
    assert remediation == lab_module.REMEDIATION["MITIGATED_BY_V2"]


def test_diagnosis_persists_after_hardening():
    v1_clean = _fake_run_result(version="v1", case=None, label="joy")
    v1_attacked = _fake_run_result(version="v1", case=_FIXTURE_CASE, label="anger")
    v2_clean = _fake_run_result(version="v2", case=None, label="joy")
    v2_attacked = _fake_run_result(version="v2", case=_FIXTURE_CASE, label="anger")
    code, _ = lab_module.diagnose(v1_clean, v1_attacked, v2_clean, v2_attacked)
    assert code == "PERSISTS_AFTER_HARDENING"


def test_diagnosis_no_material_effect():
    v1_clean = _fake_run_result(version="v1", case=None, label="joy")
    v1_attacked = _fake_run_result(version="v1", case=_FIXTURE_CASE, label="joy")
    v2_clean = _fake_run_result(version="v2", case=None, label="joy")
    v2_attacked = _fake_run_result(version="v2", case=_FIXTURE_CASE, label="joy")
    code, _ = lab_module.diagnose(v1_clean, v1_attacked, v2_clean, v2_attacked)
    assert code == "NO_MATERIAL_EFFECT"


def test_diagnosis_v2_regression():
    v1_clean = _fake_run_result(version="v1", case=None, label="joy")
    v1_attacked = _fake_run_result(version="v1", case=_FIXTURE_CASE, label="joy")
    v2_clean = _fake_run_result(version="v2", case=None, label="joy")
    v2_attacked = _fake_run_result(version="v2", case=_FIXTURE_CASE, status_code=500, label=None)
    code, _ = lab_module.diagnose(v1_clean, v1_attacked, v2_clean, v2_attacked)
    assert code == "V2_REGRESSION"


def test_diagnosis_inconclusive_when_clean_reference_invalid():
    v1_clean = _fake_run_result(version="v1", case=None, status_code=500, label=None)
    v1_attacked = _fake_run_result(version="v1", case=_FIXTURE_CASE, label="joy")
    v2_clean = _fake_run_result(version="v2", case=None, label="joy")
    v2_attacked = _fake_run_result(version="v2", case=_FIXTURE_CASE, label="joy")
    code, _ = lab_module.diagnose(v1_clean, v1_attacked, v2_clean, v2_attacked)
    assert code == "INCONCLUSIVE"


# ------------------------------------------------------------------------------------------
# Full pipeline (mocked network) + privacy: never written under results/ or verified artifacts
# ------------------------------------------------------------------------------------------


def _install_fake_endpoint_and_sender(monkeypatch):
    class FakeHandle:
        def __init__(self, version):
            self.version = version
            self.url = f"http://127.0.0.1:0/{version}"

        def stop(self):
            pass

    def fake_start_endpoint(version, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{version}_server.log").write_text("boot ok\n", encoding="utf-8")
        return FakeHandle(version)

    def fake_send_case(base_url, version, text, case, baseline_id):
        return _fake_run_result(version=version, case=case, label="joy", confidence=0.9)

    monkeypatch.setattr(run_all, "start_endpoint", fake_start_endpoint)
    monkeypatch.setattr(lab_module, "send_case", fake_send_case)


def test_run_custom_lab_pipeline_produces_real_counts(monkeypatch):
    _install_fake_endpoint_and_sender(monkeypatch)
    stages = []
    payload = lab_module.run_custom_lab(
        "job-pipeline", "I feel calm and happy about finishing this project",
        lambda stage, message: stages.append(stage),
    )
    assert payload["summary"]["variants_tested"] == len(payload["variants"])
    assert payload["summary"]["variants_tested"] >= 6
    # uniform "joy" everywhere -> no flips, no rejections/errors, everything no-material-effect
    assert payload["summary"]["v1_flips"] == 0
    assert payload["summary"]["v2_flips"] == 0
    assert payload["summary"]["no_material_effect"] == payload["summary"]["variants_tested"]
    assert stages[0] == "starting_v1"
    assert stages[-1] == "complete"
    for variant in payload["variants"]:
        assert variant["v1"]["tv_distance"] == 0.0
        assert variant["diff_original_html"] and variant["diff_attacked_html"]


def test_custom_lab_run_never_writes_under_results_or_verified_artifacts(monkeypatch, tmp_path):
    _install_fake_endpoint_and_sender(monkeypatch)

    def before(root):
        return set(root.rglob("*")) if root.exists() else set()

    results_before = before(Path(run_all.RESULTS_ROOT))
    verified_before = before(run_all.VERIFIED_FULL_REPORT_DIR)

    lab_module.run_custom_lab("job-privacy", "Something totally unremarkable happened today",
                              lambda stage, message: None)

    assert before(Path(run_all.RESULTS_ROOT)) == results_before
    assert before(run_all.VERIFIED_FULL_REPORT_DIR) == verified_before


def test_custom_lab_run_cleans_up_its_temp_directories(monkeypatch, tmp_path):
    created_dirs = []

    class FakeHandle:
        def __init__(self, version, out_dir):
            self.version = version
            self.url = f"http://127.0.0.1:0/{version}"
            self.out_dir = out_dir

        def stop(self):
            pass

    def fake_start_endpoint(version, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{version}_server.log").write_text("boot ok\n", encoding="utf-8")
        created_dirs.append(out_dir)
        return FakeHandle(version, out_dir)

    def fake_send_case(base_url, version, text, case, baseline_id):
        return _fake_run_result(version=version, case=case)

    monkeypatch.setattr(run_all, "start_endpoint", fake_start_endpoint)
    monkeypatch.setattr(lab_module, "send_case", fake_send_case)

    lab_module.run_custom_lab("job-cleanup", "A short sentence for cleanup testing",
                              lambda stage, message: None)

    assert created_dirs
    for directory in created_dirs:
        assert not directory.exists()


# ------------------------------------------------------------------------------------------
# System V5.4 final integration: native-style Back + sticky "Test Another Input" navigation.
# ------------------------------------------------------------------------------------------


def test_lab_masthead_has_native_back_first(client):
    body = client.get("/lab").text
    header = body[body.index('<header'):body.index('</header>')]
    assert 'id="nav-back" class="rl-back-btn" aria-label="Back"' in header
    assert header.index('id="nav-back"') < header.index('class="masthead-inner"')


def test_lab_js_back_uses_shared_history_fallback_behavior(client):
    assert '/static/chrome.js' in client.get("/lab").text
    js = client.get("/static/chrome.js").text
    assert 'window.history.back()' in js
    assert 'window.history.length > 1' in js
    assert 'new URL(document.referrer).origin === window.location.origin' in js
    assert 'querySelectorAll(".rl-back-btn")' in js


def test_test_another_input_lives_in_sticky_masthead_not_bottom_of_results(client):
    body = client.get("/lab").text
    nav = body[body.index('id="primary-nav"'):body.index("</nav>")]
    assert 'id="nav-test-another"' in nav
    assert "Test Another Input" in nav
    # The old bottom-of-results duplicate button is gone -- exactly one control now.
    assert body.count("Test Another Input") == 1
    assert 'id="lab-again-btn"' not in body


def test_nav_test_another_hidden_by_default_and_only_shown_on_results(client):
    body = client.get("/lab").text
    button_start = body.index('id="nav-test-another"')
    tag = body[body.rindex("<button", 0, button_start):body.index(">", button_start) + 1]
    assert "hidden" in tag
    # Server-rendered "hidden" alone isn't enough -- confirm lab.js actually toggles it.
    lab_js = client.get("/static/lab.js").text
    assert "navTestAnother.hidden = false" in lab_js  # shown in showResults()
    assert lab_js.count("navTestAnother.hidden = true") >= 3  # hidden in every other view


def test_nav_test_another_reuses_existing_reset_function(client):
    js = client.get("/static/lab.js").text
    assert "function resetToInput()" in js
    assert 'navTestAnother.addEventListener("click", resetToInput)' in js
    # One reset implementation, not a second/duplicated one.
    assert js.count("function resetToInput()") == 1


def test_nav_test_another_reset_clears_session_storage(client):
    js = client.get("/static/lab.js").text
    reset_start = js.index("function resetToInput()")
    reset_body = js[reset_start:js.index("\n  }", reset_start)]
    assert "clearJobId()" in reset_body


def test_lab_masthead_retains_v54_navbar_tokens(client):
    # System V5.4 final integration must not regress the earlier navbar unification pass.
    body = client.get("/lab").text
    assert 'class="masthead"' in body
    assert 'class="masthead-inner"' in body
    assert 'class="brand-text"' in body
    assert 'id="nav-toggle"' in body
    assert 'aria-controls="primary-nav"' in body


def test_lab_mobile_nav_closes_on_button_click_not_only_links(client):
    # nav-test-another is a <button>, not an <a> -- the mobile-menu-close wiring must cover
    # both element types or the sticky action would leave the mobile drawer open.
    js = client.get("/static/chrome.js").text
    assert 'nav.querySelectorAll("a, button")' in js


# ------------------------------------------------------------------------------------------
# System V5.4 final integration: sequential Custom<->Demo run regression (the real bug).
#
# Root cause (reproduced and fixed this session): attacks.metadata._MANIFEST/_FINGERPRINTS
# are plain module-level dicts that persist for the life of the long-running web process.
# analysis/validation.py's validate_run() asserts an EXACT set-equality between a demo/full
# run's planned attack ids and the manifest's current keys (`planned_attacks != set(manifest)`
# at analysis/validation.py:124). Before this fix, a Lab job's unique-per-job attack ids
# (derived from its own baseline_id, `lab.<job_id>.*`) were registered permanently into that
# same global dict and never removed, so ANY Demo/Full run started afterward in the same
# process -- even much later -- failed at its analysis stage with "planned attack IDs
# disagree with manifest". This was never a V1/V2 process/port lifecycle problem (that
# hypothesis was investigated and ruled out by evidence -- see HANDOFF.md).
# ------------------------------------------------------------------------------------------


def test_custom_lab_registration_leaves_no_trace_in_global_manifest():
    manifest_before = attack_metadata.manifest()
    baseline = lab_module.build_lab_baseline("Testing manifest isolation behavior here",
                                             "leak-check-job")
    lab_module.select_lab_variants(baseline)
    manifest_after = attack_metadata.manifest()
    assert manifest_after == manifest_before


def test_custom_then_full_suite_manifest_still_matches_exactly():
    """This is the exact invariant analysis/validation.py checks on every real Demo/Full
    run; reproduced directly here (no real V1/V2 HTTP calls needed -- attack generation
    touches no network) as the regression test for the sequential Custom -> Demo bug."""
    baselines = load_baseline()
    baseline = lab_module.build_lab_baseline("Testing sequential isolation before a full run",
                                             "seq-check-job-1")
    lab_module.select_lab_variants(baseline)

    attacks = run_all.build_full_suite(baselines)
    planned_attack_ids = {case.attack_id for case in attacks}
    manifest_keys = set(attack_metadata.manifest())
    assert planned_attack_ids == manifest_keys


def test_full_suite_then_custom_lab_selection_still_works():
    """The reverse direction (brief: 'can be lighter-weight') -- a prior Demo/Full run's
    registrations must not break a subsequent Lab job's own attack selection."""
    baselines = load_baseline()
    run_all.build_full_suite(baselines)  # simulates a prior Demo/Full run's registrations
    baseline = lab_module.build_lab_baseline("Testing reverse-direction isolation afterward",
                                             "seq-check-job-2")
    variants = lab_module.select_lab_variants(baseline)
    assert len(variants) >= 6


def test_run_custom_lab_stops_each_endpoint_before_starting_the_next(monkeypatch):
    """Guards the lifecycle ordering the brief's hypotheses were concerned with (even though
    the real bug turned out to be elsewhere): a version's endpoint must be fully stopped
    before the next version's start_endpoint is called -- never overlapping."""
    events = []

    class FakeHandle:
        def __init__(self, version):
            self.version = version
            self.url = f"http://fake/{version}"

        def stop(self):
            events.append(("stop", self.version))

    def fake_start_endpoint(version, out_dir):
        events.append(("start", version))
        out_dir.mkdir(parents=True, exist_ok=True)
        return FakeHandle(version)

    def fake_send_case(base_url, version, text, case, baseline_id):
        return _fake_run_result(version=version, case=case)

    monkeypatch.setattr(run_all, "start_endpoint", fake_start_endpoint)
    monkeypatch.setattr(lab_module, "send_case", fake_send_case)

    lab_module.run_custom_lab("job-order", "Order matters for endpoint lifecycle testing",
                              lambda stage, message: None)

    assert events == [
        ("start", "v1"), ("stop", "v1"),
        ("start", "v2"), ("stop", "v2"),
    ]


def test_job_marked_complete_only_after_run_custom_lab_returns(monkeypatch, client):
    """The shared resource (JOB_LOCK) must not become available to the next job before the
    owned endpoint lifecycle inside run_custom_lab() has actually finished -- i.e. status
    only ever flips to "complete" after the function that does all start/stop work has
    returned, never before or during."""
    order = []

    def fake_run_custom_lab(job_id, text, progress_callback):
        order.append("run_custom_lab:enter")
        order.append("run_custom_lab:exit")
        return {"original_text": text, "v1_clean": {}, "v2_clean": {}, "variants": [], "summary": {}}

    monkeypatch.setattr(lab_module, "run_custom_lab", fake_run_custom_lab)

    resp = client.post("/api/lab/run", json={"text": "checking completion ordering"})
    job_id = resp.json()["job_id"]
    deadline = time.monotonic() + 2.0
    state = client.get(f"/api/lab/status/{job_id}").json()
    while state["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
        state = client.get(f"/api/lab/status/{job_id}").json()

    assert state["status"] == "complete"
    assert order == ["run_custom_lab:enter", "run_custom_lab:exit"]


# ------------------------------------------------------------------------------------------
# System V5.5 release-candidate polish: Lab masthead/design-contract checks.
# ------------------------------------------------------------------------------------------


def test_lab_page_loads_shared_app_css_and_no_lab_only_stylesheet(client):
    # Lab intentionally has no stylesheet of its own -- every visual token/component (frosted
    # masthead, circular back button, cards, landing tokens) comes from the one shared
    # web/static/app.css, so Home and Lab can never visually drift apart again.
    body = client.get("/lab").text
    assert '<link rel="stylesheet" href="/static/app.css">' in body
    assert body.count("<link rel=\"stylesheet\"") == 1


def test_lab_has_no_landing_particle_canvas(client):
    # The particle background is a Home-only flourish (brief: "internal pages... static or
    # nearly static") -- Lab must not load or render it.
    body = client.get("/lab").text
    assert 'id="rl-bg-canvas"' not in body
    assert "particles.js" not in body
