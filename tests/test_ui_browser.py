"""Browser regressions for V5.5 state/history/chrome (real JS, controlled HTTP state).

Install tests/requirements-browser.txt, then set REDLAB_BROWSER_TESTS=1 and run pytest.
Uses installed Edge on Windows; elsewhere install Playwright Chromium. These tests never
start model jobs. Real endpoint acceptance is run separately against uvicorn web.app:app.
"""
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("REDLAB_BROWSER_TESTS") != "1",
                              reason="Set REDLAB_BROWSER_TESTS=1 for browser acceptance")
ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://redlab.test"


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        app = p.chromium.launch(channel="msedge" if sys.platform == "win32" else None)
        yield app
        app.close()


def running(stage="attacking_v1", index=2):
    return dict(status="running", stage=stage, stage_index=index, percent=30,
                message="Testing " + stage, run_name="one-demo")


def lab_result():
    outcome = dict(outcome="Prediction returned", label="joy", confidence=.9,
                   latency_ms=42, all_scores={"joy": .9, "neutral": .1})
    return dict(original_text="A clean reference", v1_clean=outcome, v2_clean=outcome,
                variants=[], summary=dict(variants_tested=0, v1_flips=0, v2_flips=0,
                    mitigated_by_v2=0, persisting_after_hardening=0, safe_rejections=0,
                    endpoint_errors=0))


@pytest.fixture
def ui(browser):
    from fastapi.testclient import TestClient
    from web.app import app
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    state = SimpleNamespace(demo={"status": "idle"}, lab={"status": "running", "stage": "preparing",
        "stage_index": 0, "percent": 5}, posts=0, lab_posts=0, gets=0, fail_get=False, errors=[])
    page.on("pageerror", lambda error: state.errors.append(str(error)))
    with TestClient(app) as client:
        def serve(route):
            path = urlsplit(route.request.url).path
            if path == "/api/status":
                state.gets += 1
                if state.fail_get:
                    state.fail_get = False
                    route.abort(); return
                route.fulfill(json=state.demo)
            elif path == "/api/run":
                state.posts += 1
                state.demo = running()
                route.fulfill(status=202, json=state.demo)
            elif path == "/api/lab/run":
                state.lab_posts += 1
                route.fulfill(status=202, json={**state.lab, "job_id": "private-test-token"})
            elif path.startswith("/api/lab/status/"):
                route.fulfill(json=state.lab)
            elif path == "/results/test/report.html":
                route.fulfill(content_type="text/html", body='<h1>Demo results</h1><a href="/">Home</a><a href="/lab">Lab</a>')
            else:
                response = client.get(path)
                route.fulfill(status=response.status_code, body=response.content,
                              content_type=response.headers.get("content-type", "text/html"))
        page.route(ORIGIN + "/**", serve)
        yield page, state
    assert not state.errors
    context.close()


def start_demo(page):
    page.goto(ORIGIN)
    page.locator("#run-btn").click()
    page.wait_for_url("**/#demo")
    page.wait_for_function("document.querySelector('#exec-heading').textContent.includes('attacking_v1')")


def complete_demo(page, state):
    state.demo = {"status": "complete", "result_url": "/results/test/report.html"}
    page.wait_for_url("**/results/test/report.html")


def test_active_demo_nav_rejoins_without_duplicate_and_keeps_polling(ui):
    page, state = ui
    start_demo(page)
    for _ in range(3):
        page.locator("#nav-live-demo").click()
    assert page.locator("#view-execution").is_visible()
    assert not page.locator("#view-home").is_visible()
    assert state.posts == 1
    state.demo = running("attacking_v2", 4)
    page.wait_for_function("document.querySelector('[data-lane=v2] .lane-status').textContent === 'Active'")
    assert page.locator('[data-lane="v1"] .lane-status').text_content() == "Complete"
    assert page.locator("#nav-live-demo").get_attribute("aria-current") == "page"


def test_demo_completion_replaces_history_and_back_returns_home(ui):
    page, state = ui
    start_demo(page)
    complete_demo(page, state)
    page.go_back()
    page.wait_for_function("!document.querySelector('#view-home').hidden")
    assert page.url == ORIGIN + "/"
    assert page.locator("#exec-back").is_hidden()
    page.go_forward()
    assert page.locator("h1").inner_text() == "Demo results"


def test_completed_execution_reload_uses_authoritative_result(ui):
    page, state = ui
    start_demo(page)
    state.demo = {"status": "complete", "result_url": "/results/test/report.html"}
    page.reload()
    page.wait_for_url("**/results/test/report.html")
    assert state.posts == 1


def test_fresh_home_does_not_redirect_to_previous_completed_demo(ui):
    page, state = ui
    state.demo = {"status": "complete", "result_url": "/results/test/report.html"}
    page.goto(ORIGIN)
    page.wait_for_function("!document.querySelector('#view-home').hidden")
    assert page.url == ORIGIN + "/"
    assert state.posts == 0


def test_cross_page_live_demo_entry_reattaches_active_job(ui):
    page, state = ui
    state.demo = running()
    page.goto(ORIGIN + "/lab")
    page.locator('a[href="/#run"]').click()
    page.wait_for_url("**/#demo")
    assert page.locator("#view-execution").is_visible()
    assert state.posts == 0


def test_product_back_and_direct_entry_fallback(ui):
    page, state = ui
    page.goto(ORIGIN + "/lab")
    page.locator("#nav-back").click()
    page.wait_for_url(ORIGIN + "/")
    start_demo(page)
    page.locator("#exec-back").click()
    page.wait_for_function("!document.querySelector('#view-home').hidden")
    assert state.demo["status"] == "running"
    page.locator("#nav-live-demo").click()
    page.wait_for_url("**/#demo")
    assert state.posts == 1


def test_demo_recovers_from_transient_poll_failure(ui):
    page, state = ui
    start_demo(page)
    state.fail_get = True
    state.demo = running("attacking_v2", 4)
    page.wait_for_function("document.querySelector('#exec-heading').textContent.includes('attacking_v2')")
    assert state.posts == 1


def test_lab_completed_reattach_history_and_test_another(ui):
    page, state = ui
    page.goto(ORIGIN)
    page.goto(ORIGIN + "/lab")
    page.locator("#lab-text").fill("A clean reference")
    page.locator("#lab-submit").click()
    page.wait_for_function("sessionStorage.getItem('labJobId') !== null")
    state.lab = {"status": "complete", "result": lab_result()}
    page.reload()
    page.wait_for_function("!document.querySelector('#view-lab-results').hidden")
    assert page.locator("#view-lab-execution").is_hidden()
    page.locator('#primary-nav a[href="/"]').click()
    page.go_back()
    page.wait_for_function("!document.querySelector('#view-lab-results').hidden")
    page.locator("#nav-test-another").click()
    assert page.locator("#view-lab-input").is_visible()
    assert page.evaluate("sessionStorage.getItem('labJobId')") is None
    page.reload()
    assert page.locator("#view-lab-input").is_visible()
    assert state.lab_posts == 1


@pytest.mark.parametrize("width", [390, 768, 1024, 1366, 1440, 1920])
def test_responsive_chrome_ctas_and_no_overflow(ui, width):
    page, state = ui
    page.set_viewport_size({"width": width, "height": 900})
    for path in ("/", "/lab", "/verified-full/report.html"):
        page.goto(ORIGIN + path)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), path
        header = page.locator(".masthead").bounding_box()
        assert header["x"] == 0 and header["width"] == width
        if path == "/":
            page.wait_for_function("document.querySelector('canvas').width > 0")
            field = page.locator("canvas").bounding_box()
            assert abs(field["x"]) < 1 and abs(field["width"] - width) < 1
            buttons = page.locator(".hero-actions .button")
            a, b = buttons.nth(0).bounding_box(), buttons.nth(1).bounding_box()
            assert abs(a["width"] - b["width"]) < 1 and a["height"] == b["height"]
        else:
            back = page.locator(".masthead > .rl-back-btn").bounding_box()
            assert 12 <= back["x"] <= 28
            assert back["y"] == 20


def test_report_sidebar_fast_feedback_ordering_and_fixed_back(ui):
    page, state = ui
    page.goto(ORIGIN + "/verified-full/report.html")
    before = page.locator(".masthead > .rl-back-btn").bounding_box()
    page.locator("#toc-collapse").click()
    assert page.locator(".masthead > .rl-back-btn").bounding_box() == before
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#toc-collapse").click()
    for target in ("category-failure-rates", "v1-audit", "v1-validity", "v2-audit", "v2-validity", "v2-findings"):
        link = page.locator('[data-toc-link][href="#' + target + '"]')
        link.click()
        page.wait_for_function("id => document.querySelector('[data-toc-link][aria-current]')?.getAttribute('href') === '#' + id", arg=target, timeout=1000)
    assert page.evaluate("getComputedStyle(document.documentElement).scrollBehavior") == "auto"


def test_mobile_report_drawer_keyboard_and_backdrop(ui):
    page, state = ui
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(ORIGIN + "/verified-full/report.html")
    assert page.locator("#toc-backdrop").is_hidden()
    page.locator("#toc-toggle").click()
    assert page.locator("#toc-backdrop").is_visible()
    assert page.evaluate("document.activeElement.id") == "toc-close"
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.querySelector('#report-toc').contains(document.activeElement)")
    page.keyboard.press("Escape")
    assert page.locator("#toc-backdrop").is_hidden()
    assert page.locator("#toc-toggle").get_attribute("aria-expanded") == "false"
    page.locator("#toc-toggle").click()
    page.locator('[data-toc-link][href="#category-failure-rates"]').click()
    assert page.locator("#category-failure-rates").bounding_box()["y"] >= page.locator(".masthead").bounding_box()["height"]


def test_reduced_motion_preserves_static_particles(ui):
    page, state = ui
    page.emulate_media(reduced_motion="reduce")
    page.goto(ORIGIN)
    page.wait_for_function("document.querySelector('canvas').width > 0")
    first = page.locator("canvas").evaluate("el => el.toDataURL()")
    # Two rendered frames, not an artificial product delay.
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    assert page.locator("canvas").evaluate("el => el.toDataURL()") == first
    assert page.locator("canvas").is_visible()


def test_lab_metric_icons_preserve_values_labels_and_readable_layout(ui):
    page, state = ui
    result = lab_result()
    result["summary"] = dict(zip(result["summary"], (24, 8, 3, 5, 3, 2, 1)))
    state.lab = {"status": "complete", "result": result}
    page.goto(ORIGIN + "/lab")
    page.evaluate("sessionStorage.setItem('labJobId', 'private-test-token')")
    page.reload()
    page.wait_for_function("!document.querySelector('#view-lab-results').hidden")
    labels = ["Variants tested", "V1 label flips", "V2 label flips", "Mitigated by V2",
              "Persisting after hardening", "Safe rejections", "Endpoint errors"]
    for width in (1920, 1440, 1366, 1024, 768, 390):
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.locator('.lab-metric dt').all_text_contents() == labels
        assert page.locator('.lab-metric dd').all_text_contents() == ['24', '8', '3', '5', '3', '2', '1']
        for metric in page.locator('.lab-metric').all():
            icon = metric.locator('svg')
            assert icon.count() == 1 and icon.get_attribute('aria-hidden') == 'true'
            assert icon.get_attribute('focusable') == 'false'
            number, label, glyph = (metric.locator(selector).bounding_box()
                                    for selector in ('.lab-metric-value', 'dt', 'svg'))
            assert number['y'] < label['y']
            assert glyph['x'] >= label['x'] + label['width']
            assert metric.evaluate('el => el.scrollWidth <= el.clientWidth')
        assert state.lab_posts == 0


def test_demo_evidence_entry_preserves_provenance_and_fits_header(ui):
    from report.generate import render_html
    page, state = ui
    data = json.loads((ROOT / 'artifacts/verified_full_report/analysis.json').read_bytes())
    data['detailed_report'] = {'available': True, 'relative_href': 'detailed/report.html'}
    data['demo_evidence'] = {'notes': [], 'featured_failure': None, 'featured_prediction_flip': None}
    source_hash = 'a' * 64
    rendered = render_html(data, source_sha256=source_hash, mode='demo')
    page.route(ORIGIN + '/evidence-preview', lambda route: route.fulfill(
        content_type='text/html', body=rendered))
    for width in (1920, 1440, 1366, 1024, 768, 390):
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(ORIGIN + '/evidence-preview')
        assert page.locator('#source h2').inner_text() == 'Evidence bundle'
        assert page.locator('#source .section-number').inner_text() == '03'
        assert page.locator('#source .hash').inner_text() == source_hash
        assert 'Analysis schema v2' in page.locator('#source').inner_text()
        if width <= 760:
            page.locator('#report-menu-toggle').click()
        else:
            boxes = [page.locator(s).bounding_box() for s in ('.brand', '#report-menu', '.downloads')]
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    assert (a['x'] + a['width'] <= b['x'] + 1 or b['x'] + b['width'] <= a['x'] + 1
                            or a['y'] + a['height'] <= b['y'] + 1 or b['y'] + b['height'] <= a['y'] + 1)
        page.locator('#report-menu a[href="#source"]').click()
        assert page.url.endswith('#source')
        heading = page.locator('#source h2').bounding_box()
        assert 0 <= heading['y'] < 1000
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_charts_exact_verified_rates_denominators_and_scale(ui):
    page, state = ui
    page.goto(ORIGIN + "/verified-full/report.html")
    data = json.loads((ROOT / "artifacts/verified_full_report/analysis.json").read_bytes())
    figures = page.locator("figure.comparison-chart")
    assert figures.count() == 2
    for category, block in zip(data["comparison"]["category_failure_rates"], page.locator(".chart-category").all()):
        # Match by heading, not by JSON order.
        name = block.locator("h4").inner_text().lower()
        for i, version in enumerate(("v1", "v2")):
            rate = data["comparison"]["category_failure_rates"][name][version]
            value = block.locator(".chart-value").nth(i).inner_text()
            assert f'{rate["rate"] * 100:.2f}%' in value
            assert f'{rate["failed"]} / {rate["eligible"]}' in value
    for i, version in enumerate(("v1", "v2")):
        drift = data["summary_" + version]["drift"]
        value = figures.nth(1).locator(".chart-value").nth(i).inner_text()
        assert f'{drift["flip_rate"] * 100:.2f}%' in value
        assert f'{drift["qualifying_flips"]} / {drift["eligible_comparisons"]}' in value
    assert figures.first.locator(".chart-axis").inner_text().split() == ["0%", "25%", "50%", "75%", "100%"]
