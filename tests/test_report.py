"""Report interface, evidence semantics, safe HTML and actual PDF regressions."""

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from report import generate as report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def data():
    summaries = {}
    for version in ("v1", "v2"):
        summaries[version] = {
            "version": version,
            "coverage": dict(planned=8, selected=8, completed=8, missing=0, skipped=0,
                             limit_excluded=0, coverage_rate=1.0),
            "category_stats": {c: dict(failed=0, eligible=1, failure_rate=0.0, review=0,
                                      diagnostic=0, unevaluable=0) for c in report.CATEGORIES},
            "operational": dict.fromkeys(report.OPERATIONS, 0),
            "drift": {
                "qualifying_flips": 0, "eligible_comparisons": 2, "flip_rate": 0.0,
                "baseline_denominator": dict(eligible=2, total=2, excluded_below_threshold=0,
                    excluded_baselines=[], no_prediction=[], statement="2 of 2 baselines eligible for flip scoring", threshold=0.6),
                "confidence_change": dict(mean_delta_on_flips=None, per_flip=[]),
                "excluded": {}, "unevaluable": {}, "flip_attack_ids": [],
            },
            "findings": [], "validity_tier_census": {}, "diagnostic_observations": [],
            "review_cases": [], "limitations": ["Fixture limitation: no accuracy claim."],
        }
    result = dict(schema_version=2, summary_v1=summaries["v1"], summary_v2=summaries["v2"],
        comparison=dict(fingerprints=dict(planned_match=True, manifest_match=True, whole_suite_comparable=True),
                        coverage=dict(matched_count=8, v1_only_count=0, v2_only_count=0, unavailable_count=0,
                                      v1_only=[], v2_only=[], unavailable=[]),
                        limitations=["Fixture limitation: no accuracy claim."], finding_comparisons=[],
                        new_finding_evidence=[], inconclusive_new_findings=[]))
    sync(result)
    return result


def sync(data):
    """Keep explicitly repeated schema fields synchronized in synthetic inputs."""
    c = data["comparison"]
    c["operational"], c["drift"], c["category_failure_rates"] = {}, {}, {}
    for v in ("v1", "v2"):
        s = data[f"summary_{v}"]
        c["coverage"][v] = copy.deepcopy(s["coverage"])
        c["operational"][v] = copy.deepcopy(s["operational"])
        for k in ("qualifying_flips", "eligible_comparisons", "flip_rate"):
            c["drift"][v + "_" + k] = s["drift"][k]
        c["drift"][v + "_baseline_denominator"] = s["drift"]["baseline_denominator"]["statement"]
        for category, stats in s["category_stats"].items():
            c["category_failure_rates"].setdefault(category, {})[v] = dict(
                failed=stats["failed"], eligible=stats["eligible"], rate=stats["failure_rate"])


def finding(data, version="v1", *, subfamily="oversized", ids=("attack-one",), tiers=("GOLD",), score=70, tier="High"):
    s = data[f"summary_{version}"]
    item = dict(finding=dict(finding_id=f"F-{version}-{len(s['findings']) + 1}", title=f"{subfamily}: request failure",
                            category="malformed", severity_score=score, severity_tier=tier,
                            description="Measured request failure.", remediation="Validate input before inference.", evidence=list(ids)),
                subfamily=subfamily, failure_mode="unhandled_5xx", affected_cases=len(ids), validity_tiers=list(tiers))
    s["findings"].append(item)
    for t in tiers:
        s["validity_tier_census"][t] = s["validity_tier_census"].get(t, 0) + 1
    return item


def resolution(data, entry, status="resolved", remaining=(), unavailable=(), improved=None):
    data["comparison"]["finding_comparisons"].append(dict(key=list(report.group_key(entry)), status=status,
        remaining_ids=list(remaining), unavailable_ids=list(unavailable),
        improved_ids=entry["finding"]["evidence"][:] if improved is None else list(improved)))


def html(data, **kwargs):
    return report.render_html(data, source_sha256="a" * 64, **kwargs)


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids, self.links, self.tags, self.text = [], [], [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        if "href" in values:
            self.links.append(values["href"])

    def handle_data(self, value):
        self.text.append(value)


def test_report_renders_deterministically_without_mutating_input(data):
    original = copy.deepcopy(data)
    assert html(data) == html(data)
    assert data == original
    assert "No automatically scored finding groups" in html(data)


def test_local_links_and_unique_anchors(data):
    e = finding(data)
    resolution(data, e)
    doc = Document(html(data))
    assert len(doc.ids) == len(set(doc.ids))
    assert all(link[1:] in doc.ids for link in doc.links if link.startswith("#"))
    assert {"report.pdf", "analysis.json", "export_meta.json"} <= set(doc.links)
    assert not any(link.startswith(("http:", "https:", "file:")) for link in doc.links)


def test_xss_and_template_syntax_are_plain_text(data):
    payload = '<script>alert(1)</script><img src="file:///private">{{7*7}}'
    e = finding(data, ids=(payload,))
    e["finding"].update(title=payload, remediation=payload, description=payload, finding_id=payload)
    resolution(data, e)
    result = html(data)
    assert payload not in result
    assert "&lt;script&gt;" in result
    assert "{{7*7}}" in result
    # The only legitimate scripts are report/template.html's own static, repository-owned
    # ones: the <head> internal-navigation listener (System V6) and the sidebar/scrollspy
    # script (System V5.3). Verify the untrusted payload injected no further script tag and
    # never reached the body of a trusted one.
    assert Document(result).tags.count("script") == 2
    after_style = result.index("</style>")  # the CSS may itself mention "<script>" in prose
    for start in [i for i in range(len(result)) if result.startswith("<script>", i) and i > after_style]:
        assert "alert(1)" not in result[start:result.index("</script>", start)]
    # The one legitimate <img> is the trusted, base64-embedded Team Checkmate logo (see
    # report.generate._logo_data_uri) -- verify the untrusted payload did not inject an
    # additional image (e.g. an exfiltration src) alongside it.
    assert result.count("<img") == 1
    assert 'src="data:image/png;base64,' in result
    assert 'src="file:' not in result


def test_withheld_reason_suppresses_even_stale_comparison_fields(data):
    e = finding(data)
    resolution(data, e)
    data["comparison"]["comparison_withheld_reason"] = "Different input fingerprints."
    # A stale legacy field cannot cause a comparison claim to appear.
    data["comparison"]["findings_resolved"] = ["FABRICATED_CLAIM"]
    output = html(data)
    assert "Different input fingerprints." in output
    for absent in ("Resolved groups", "Newly demonstrated groups", "Compatible inputs", "Failure rate by attack category", "FABRICATED_CLAIM"):
        assert absent not in output
    assert "V1 observations only" in output and "V2 observations only" in output


def test_remaining_group_keeps_improved_and_inconclusive_case_qualifiers(data):
    e = finding(data, ids=("old-improved", "old-unknown"))
    finding(data, "v2", ids=("different-persistent-case",))
    resolution(data, e, "remaining", remaining=("different-persistent-case",), unavailable=("old-unknown",), improved=("old-improved",))
    output = html(data)
    assert "1 remaining / 1 improved / 1 inconclusive" in output
    for value in ("different-persistent-case", "old-unknown", "old-improved"):
        assert value in output


def test_unavailable_is_displayed_as_inconclusive(data):
    e = finding(data)
    resolution(data, e, "unavailable", unavailable=("attack-one",), improved=())
    output = html(data)
    assert '>Inconclusive</span>' in output
    assert '>Unavailable</span>' not in output


def test_mixed_demonstrated_and_inconclusive_new_group_counted_once(data):
    e = finding(data, "v2", ids=("regression", "prior-unknown"))
    data["comparison"]["new_finding_evidence"] = [dict(key=list(report.group_key(e)), regression_ids=["regression"])]
    data["comparison"]["inconclusive_new_findings"] = [dict(key=list(report.group_key(e)), unavailable_ids=["prior-unknown"])]
    output = html(data)
    assert "there are 1 distinct groups" in output
    assert "Demonstrated regression IDs" in output and "Unknown prior-state IDs" in output


def test_mixed_gold_silver_evidence_is_qualified(data):
    e = finding(data, tiers=("GOLD", "SILVER"))
    resolution(data, e)
    output = html(data)
    assert "SILVER qualification." in output and "also contains GOLD evidence" in output
    assert "GOLD 1" in output and "SILVER 1" in output


@pytest.mark.parametrize("score,tier,display", [(59.999999,"Medium","<60"), (84.999999,"High","<85"),
    (34.999999,"Low","<35"), (60,"High","60"), (59.8,"Medium","59.8"), (100,"Critical","100")])
def test_severity_display_does_not_round_across_tier(score, tier, display):
    assert report.score_display(dict(severity_score=score, severity_tier=tier)) == display


def test_findings_sorted_by_supplied_tier_and_unrounded_score(data):
    low = finding(data, subfamily="minor", score=20, tier="Low")
    high = finding(data, subfamily="major", score=90, tier="Critical")
    resolution(data, low)
    resolution(data, high)
    output = html(data)
    assert output.index('major: request failure') < output.index('minor: request failure')


def test_na_and_empty_coverage_are_explicit(data):
    for v in ("v1", "v2"):
        s = data[f"summary_{v}"]
        s["coverage"] = dict.fromkeys(s["coverage"], 0)
        s["category_stats"]["malformed"].update(eligible=0, failure_rate="N/A")
        s["drift"].update(eligible_comparisons=0, flip_rate="N/A")
    data["comparison"]["coverage"]["matched_count"] = 0
    sync(data)
    output = html(data)
    assert "N/A" in output and "No cases planned." in output


def test_partial_coverage_accepts_runner_six_decimal_rounding(data):
    for version in ("v1", "v2"):
        data[f"summary_{version}"]["coverage"].update(planned=9, selected=9, missing=1, coverage_rate=0.888889)
    data["comparison"]["coverage"].update(unavailable_count=1, unavailable=["attack:missing"])
    sync(data)
    assert "Partial coverage." in html(data)
    assert "8/9 (88.89%)" in html(data)


def test_diagnostic_review_tier_mismatch_remains_visible_and_unscored(data):
    data["summary_v1"]["diagnostic_observations"] = [dict(attack_id="punctuation-case", category="whitespace",
        subfamily="repeated_punctuation", validity_tier="REVIEW", oracle="diagnostic_no_fixed_oracle", tier_differs_from_diagnostic=True)]
    output = html(data)
    assert "punctuation-case" in output and ">REVIEW</td><td>Yes</td>" in output
    assert "No automatically scored finding groups" in output


@pytest.mark.parametrize("raw", [b'{', b'\xff', b'{"schema_version":2,"schema_version":2}',
                                   b'{"schema_version":NaN}', b'[]', b'null'])
def test_invalid_json_rejected(raw):
    with pytest.raises(ValueError):
        report.parse_report(raw)


@pytest.mark.parametrize("version", [1, 3, "2", True, 2.0, None])
def test_unsupported_schema_rejected(data, version):
    data["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        html(data)


@pytest.mark.parametrize("field", ["coverage", "category_stats", "operational", "drift", "findings", "limitations"])
def test_missing_summary_fields_fail_clearly(data, field):
    del data["summary_v1"][field]
    with pytest.raises(ValueError, match=field):
        html(data)


@pytest.mark.parametrize("value", [True, -1, 1.5, "1", None])
def test_invalid_counts_rejected(data, value):
    data["summary_v1"]["operational"]["timeouts"] = value
    sync(data)
    with pytest.raises(ValueError, match="nonnegative integer"):
        html(data)


@pytest.mark.parametrize("value", [True, float('nan'), float('inf'), -0.1, 2, "0.0"])
def test_invalid_rates_rejected(data, value):
    data["summary_v1"]["category_stats"]["encoding"]["failure_rate"] = value
    sync(data)
    with pytest.raises(ValueError):
        html(data)


def test_rate_must_match_explicit_counts(data):
    data["summary_v1"]["category_stats"]["encoding"]["failure_rate"] = 0.5
    sync(data)
    with pytest.raises(ValueError, match="rate does not match counts"):
        html(data)


def test_zero_denominator_cannot_be_reported_as_zero_percent(data):
    data["summary_v1"]["category_stats"]["encoding"]["eligible"] = 0
    sync(data)
    with pytest.raises(ValueError, match="zero denominator"):
        html(data)


def test_incompatible_without_reason_rejected(data):
    data["comparison"]["fingerprints"]["manifest_match"] = False
    with pytest.raises(ValueError, match="withheld_reason"):
        html(data)


def test_mismatched_comparison_rates_rejected(data):
    data["comparison"]["category_failure_rates"]["encoding"]["v2"]["failed"] = 1
    with pytest.raises(ValueError, match="differs from version summary"):
        html(data)


@pytest.mark.parametrize("mutate", [
    lambda e: e["finding"].update(remediation=""),
    lambda e: e.update(affected_cases=2),
    lambda e: e.update(validity_tiers=["REVIEW"]),
    lambda e: e["finding"].update(severity_tier="Unknown"),
    lambda e: e["finding"].update(severity_score=float('nan')),
    lambda e: e["finding"].update(evidence=["attack-one", "attack-one"]),
])
def test_invalid_findings_rejected(data, mutate):
    e = finding(data)
    resolution(data, e)
    mutate(e)
    with pytest.raises(ValueError):
        html(data)


def test_missing_structured_comparison_not_replaced_with_legacy_list(data):
    finding(data)
    data["comparison"]["findings_resolved"] = [["malformed", "oversized", "unhandled_5xx"]]
    with pytest.raises(ValueError, match="missing V1 finding groups"):
        html(data)


def test_resolved_with_persistent_evidence_rejected(data):
    e = finding(data)
    finding(data, "v2")
    resolution(data, e)
    with pytest.raises(ValueError, match="evidence does not join"):
        html(data)


def test_overlapping_new_and_inconclusive_ids_rejected(data):
    e = finding(data, "v2")
    key = list(report.group_key(e))
    data["comparison"].update(new_finding_evidence=[dict(key=key, regression_ids=["attack-one"])],
                              inconclusive_new_findings=[dict(key=key, unavailable_ids=["attack-one"])])
    with pytest.raises(ValueError, match="overlapping"):
        html(data)


def test_html_only_bundle_preserves_source_bytes_and_hashes(data, tmp_path, monkeypatch):
    monkeypatch.setattr(report, "render_pdf", lambda _: pytest.fail("HTML-only attempted PDF generation"))
    raw = b'\xef\xbb\xbf' + json.dumps(data, indent=4).encode()
    out = tmp_path / "bundle"
    report.generate_report(raw, out, html_only=True)
    assert (out / "analysis.json").read_bytes() == raw
    metadata = json.loads((out / "export_meta.json").read_text())
    assert metadata["source_sha256"] == hashlib.sha256(raw).hexdigest()
    for name, digest in metadata["files"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert "report.pdf" not in Document((out / "report.html").read_text(encoding="utf-8")).links


def test_invalid_input_writes_nothing(tmp_path):
    out = tmp_path / "new"
    with pytest.raises(ValueError):
        report.generate_report(b"{}", out)
    assert not out.exists()


def test_pdf_failure_writes_nothing(data, tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError("PDF failure")
    monkeypatch.setattr(report, "render_pdf", fail)
    out = tmp_path / "new"
    with pytest.raises(RuntimeError):
        report.generate_report(json.dumps(data).encode(), out)
    assert not out.exists()


def test_existing_output_preserved(data, tmp_path):
    marker = tmp_path / "report.html"
    marker.write_text("earlier evidence")
    with pytest.raises(ValueError, match="already exists"):
        report.generate_report(json.dumps(data).encode(), tmp_path)
    assert marker.read_text() == "earlier evidence"


def test_external_resource_fetch_blocked():
    for url in ("https://example.com/font", "file:///private", "data:text/plain,abc"):
        with pytest.raises(ValueError, match="disabled"):
            report.deny_resource(url)


def test_cli_file_and_stdin(data, tmp_path):
    raw = json.dumps(data).encode()
    source = tmp_path / "source.json"
    source.write_bytes(raw)
    for name, inp in (("file", str(source)), ("stdin", "-")):
        cmd = [sys.executable, "-m", "report.generate", "--input", inp, "--out", str(tmp_path / name), "--html-only"]
        result = subprocess.run(cmd, input=raw, capture_output=True, cwd=ROOT, timeout=30)
        assert result.returncode == 0, result.stderr.decode()
        assert (tmp_path / name / "report.html").exists()


def test_cli_error_is_actionable_without_traceback(tmp_path):
    cmd = [sys.executable, "-m", "report.generate", "--input", "-", "--out", str(tmp_path / "new")]
    result = subprocess.run(cmd, input=b"{}", capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 1
    assert b"Report generation failed:" in result.stderr and b"Traceback" not in result.stderr


def test_real_pdf_bundle_and_printed_evidence(data, tmp_path):
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        pytest.skip("Native PDF renderer unavailable on this machine")
    e = finding(data, tiers=("SILVER",), ids=("unique-print-evidence-123",))
    resolution(data, e)
    result = html(data)
    document = HTML(string=result, url_fetcher=report.deny_resource).render()
    text = " ".join(box.text for page in document.pages for box in page._page_box.descendants() if hasattr(box, "text"))
    assert "unique-print-evidence-123" in text  # Closed HTML details must print in full.
    assert "SILVER qualification." in text and "Validate input before inference." in text
    assert "2 of 2 baselines eligible" in text
    out = tmp_path / "pdf"
    report.generate_report(json.dumps(data).encode(), out)
    assert (out / "report.pdf").read_bytes().startswith(b"%PDF-")
    assert (out / "report.pdf").stat().st_size > 5000


def test_renderer_has_no_cross_component_imports():
    import ast
    tree = ast.parse(ROOT.joinpath("report/generate.py").read_text(encoding="utf-8"))
    forbidden = {"attacks", "analysis", "baseline", "runner", "endpoint"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] in forbidden for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden


# --------------------------------------------------------------------------------------
# demo mode: short single-page judge-facing report, presentation only (see run_all.py
# for how demo_evidence and mode are actually produced from a live run).
# --------------------------------------------------------------------------------------


def demo_evidence_fixture():
    return {
        "literal_crash_case_available": False,
        "crash_status_note": "No request in this run caused observed service unavailability.",
        "notes": [],
        "featured_failure": {
            "attack_id": "malformed.oversized_100kb", "category": "malformed", "subfamily": "oversized_100kb",
            "failure_mode": "unhandled_5xx", "failure_label": "unhandled server error",
            "input_description": "malformed/oversized_100kb", "payload_bytes": 102400, "preview": "A" * 50,
            "v1": dict(status_code=500, outcome="Unhandled server error", error=None, latency_ms=53.9,
                      latency_band="normal", endpoint_alive_after=True),
            "v2": dict(status_code=422, outcome="Rejected safely", error=None, latency_ms=59.1,
                      latency_band="normal", endpoint_alive_after=True),
            "technical_interpretation": "Unhandled 5xx but the service stayed available; not a process crash.",
            "remediation": "Reject requests above a defined body/input size limit before inference begins.",
        },
        "featured_prediction_flip": {
            "attack_id": "dataset-sadness-3.encoding.homoglyph.leading.d1", "baseline_id": "dataset-sadness-3",
            "category": "encoding", "subfamily": "homoglyph", "validity_tiers": ["SILVER"],
            "original_text": "i feel depressed", "attacked_text": "і feel depressed",
            "original_html": 'i feel depressed',
            "attacked_html": '<mark class="demo-mark">і</mark> feel depressed',
            "modification": "position 0: 'i' (U+0069 LATIN SMALL LETTER I) -> 'і' (U+0456 CYRILLIC SMALL LETTER I)",
            "original_label": "sadness", "original_confidence": 0.99, "attacked_label": "fear",
            "attacked_confidence": 0.28, "confidence_change": -0.71, "v2_still_flipped": True,
            "v1": dict(status_code=200, outcome="Accepted", error=None, latency_ms=20.2,
                      latency_band="normal", endpoint_alive_after=True),
            "v2": dict(status_code=200, outcome="Accepted", error=None, latency_ms=16.7,
                      latency_band="normal", endpoint_alive_after=True),
            "remediation": "Model-level robustness gap; needs adversarial training data augmentation.",
        },
    }


@pytest.fixture
def demo_data(data):
    # Round numbers, not the real 163/1928 -- schema validation requires the unavailable
    # list to be fully enumerated (len == count), and the point here is testing that the
    # demo template shows the COUNT without enumerating it, not reproducing a real run.
    for version in ("v1", "v2"):
        s = data[f"summary_{version}"]
        s["coverage"].update(planned=20, completed=15, selected=15, limit_excluded=5, coverage_rate=0.75)
    data["comparison"]["coverage"]["v1"] = copy.deepcopy(data["summary_v1"]["coverage"])
    data["comparison"]["coverage"]["v2"] = copy.deepcopy(data["summary_v2"]["coverage"])
    hidden_ids = [f"hidden-excluded-attack-{i}" for i in range(5)]
    data["comparison"]["coverage"].update(matched_count=15, unavailable=hidden_ids, unavailable_count=5)
    data["demo_evidence"] = demo_evidence_fixture()
    return data


def test_demo_mode_is_a_single_page_without_finding_register(demo_data):
    e = finding(demo_data, tiers=("SILVER",), ids=("attack-one",))
    resolution(demo_data, e)
    result = html(demo_data, mode="demo")
    assert "<article class=\"finding\"" not in result
    assert 'class="finding-index"' not in result
    assert 'id="findings"' not in result
    assert "LIVE DEMO RUN" in result
    assert "15 of 20 planned cases executed" in result  # actual fixture values, not hardcoded in the template


def test_demo_mode_nav_omits_findings_link(demo_data):
    result = html(demo_data, mode="demo")
    doc = Document(result)
    nav_start = result.index("<nav")
    nav_html = result[nav_start:result.index("</nav>", nav_start)]
    assert "Findings" not in nav_html
    assert "Demo" in nav_html and "Results" in nav_html and "Method" in nav_html


def test_demo_mode_highlights_unicode_change_and_omits_id_listing(demo_data):
    result = html(demo_data, mode="demo")
    assert '<mark class="demo-mark">і</mark>' in result  # pre-escaped by run_all.py, rendered via |safe
    assert "Excluded by demo limit: 5 cases" in result
    assert "hidden-excluded-attack-0" not in result  # counts only, never the enumerated ID list in demo mode


def test_full_mode_still_renders_finding_register(demo_data):
    e = finding(demo_data, tiers=("SILVER",), ids=("attack-one",))
    resolution(demo_data, e)
    result = html(demo_data, mode="full")
    assert "<article class=\"finding\"" in result
    assert "Findings" in result[result.index("<nav"):result.index("</nav>")]


def test_render_html_rejects_unknown_mode(demo_data):
    with pytest.raises(ValueError, match="mode"):
        html(demo_data, mode="ultra")


def test_generate_report_demo_pdf_substantially_shorter_than_full(demo_data, tmp_path):
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        pytest.skip("Native PDF renderer unavailable on this machine")
    e = finding(demo_data, tiers=("SILVER",), ids=("attack-one",))
    resolution(demo_data, e)
    raw = json.dumps(demo_data).encode()
    report.generate_report(raw, tmp_path / "full", mode="full")
    report.generate_report(raw, tmp_path / "demo", mode="demo")
    full_pages = len(HTML(string=(tmp_path / "full" / "report.html").read_text(encoding="utf-8")).render().pages)
    demo_pages = len(HTML(string=(tmp_path / "demo" / "report.html").read_text(encoding="utf-8")).render().pages)
    assert demo_pages < full_pages
    assert demo_pages <= 6


# --------------------------------------------------------------------------------------
# V3: real logo, sticky navbar, de-emphasized crash note, portable detailed-report link.
# --------------------------------------------------------------------------------------


def test_real_logo_is_embedded_and_placeholder_removed(demo_data):
    for mode in ("full", "demo"):
        result = html(demo_data, mode=mode)
        assert 'src="data:image/png;base64,' in result
        assert 'class="brand-logo"' in result
        assert 'class="mark"' not in result  # old "C." placeholder no longer used as branding


def test_missing_logo_asset_stops_report_generation(demo_data, monkeypatch, tmp_path):
    fake_path = tmp_path / "does-not-exist.png"
    monkeypatch.setattr(report, "LOGO_PATH", fake_path)
    report._logo_data_uri.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="logo"):
            html(demo_data)
    finally:
        report._logo_data_uri.cache_clear()  # restore the real logo for every other test


def test_masthead_is_sticky_with_scroll_offset_and_static_in_print():
    css = report.HERE.joinpath("style.css").read_text(encoding="utf-8")
    assert "position: sticky" in css and "top: 0" in css
    assert "scroll-padding-top:" in css.split("@media print", 1)[0]
    print_css = css.split("@media print", 1)[1]
    assert ".masthead { position: static" in print_css


def test_demo_hero_uses_functional_identity_not_marketing_copy(demo_data):
    result = html(demo_data, mode="demo")
    assert "LIVE DEMO RESULTS" in result
    assert "Robustness" not in result
    assert "in one minute" not in result
    assert "V1" in result and "Unhardened Endpoint" in result
    assert "V2" in result and "Hardened Endpoint" in result
    assert "Red Lab v5.0" in result and "Team Checkmate" in result


def test_demo_crash_note_is_a_small_caption_not_a_warning_box(demo_data):
    result = html(demo_data, mode="demo")
    assert "Literal crash/unavailability demonstrated" not in result
    assert '<p class="caption crash-note">No request in this run caused observed service unavailability.</p>' in result
    # It renders as a caption, not inside a prominent .notice.warning box.
    note_start = result.index('<p class="caption crash-note">')
    assert '<p class="notice warning">' not in result[max(0, note_start - 200):note_start]


def test_demo_missing_examples_still_render_as_prominent_warnings(demo_data):
    demo_data["demo_evidence"]["featured_failure"] = None
    demo_data["demo_evidence"]["notes"] = ["No unhandled server error, timeout, connection failure, "
                                           "or service-unavailability finding was found in this run."]
    result = html(demo_data, mode="demo")
    assert '<p class="notice warning">No unhandled server error' in result


def test_demo_view_detailed_report_link_when_available(demo_data):
    demo_data["detailed_report"] = {"available": True, "relative_href": "detailed/report.html"}
    result = html(demo_data, mode="demo")
    downloads = result[result.index('class="downloads"'):result.index("</header>")]
    assert 'href="detailed/report.html"' in downloads
    assert 'target="_blank"' in downloads
    assert "View Detailed Report" in downloads
    assert "Download PDF" not in downloads


def test_demo_omits_detailed_report_link_when_unavailable(demo_data):
    demo_data["detailed_report"] = {"available": False, "relative_href": ""}
    result = html(demo_data, mode="demo")
    downloads = result[result.index('class="downloads"'):result.index("</header>")]
    assert "View Detailed Report" not in downloads
    assert "Source JSON" in downloads  # still available regardless


# --------------------------------------------------------------------------------------
# V5.1: Red Lab identity, Home navigation, Source JSON new-tab (no forced download).
# --------------------------------------------------------------------------------------


def test_demo_and_full_reports_link_home_to_red_lab(demo_data):
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode)
        assert 'class="home-link" href="/"' in result
        assert "Back to Red Lab" in result


def test_source_json_opens_new_tab_without_forcing_download(demo_data):
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode)
        downloads = result[result.index('class="downloads"'):result.index("</header>")]
        idx = downloads.index('href="analysis.json"')
        tag = downloads[downloads.rindex("<a", 0, idx):downloads.index(">", idx) + 1]
        assert 'target="_blank"' in tag
        assert 'rel="noopener"' in tag
        assert "download" not in tag


def test_reports_credit_team_checkmate_and_show_red_lab_version(demo_data):
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode)
        assert "Team Checkmate" in result
        assert "Red Lab v5.0" in result


# ----------------------------------------------------------------------------------------
# V5.1 closure: partial-banner mustard removal, demo category comparison visual grammar.
# ----------------------------------------------------------------------------------------


def test_partial_banner_is_not_a_large_mustard_panel(demo_data):
    result = html(demo_data, mode="demo")
    css_block = result[result.index("<style>"):result.index("</style>")]
    # The whole banner must no longer be filled with the warning/amber token -- only a
    # small eyebrow accent may still use it (see AGENTS.md-adjacent System V5.1 brief).
    assert ".partial-banner { background: var(--rl-warning)" not in css_block
    assert "border-left: 4px solid var(--rl-red)" in css_block
    assert ".partial-banner .eyebrow { color: var(--rl-warning)" in css_block


def test_demo_category_comparison_shows_v1_v2_structure_with_bars(demo_data):
    result = html(demo_data, mode="demo")
    section = result[result.index('id="results"'):result.index('id="method"')]
    assert "V1 &middot; Unhardened" in section
    assert "V2 &middot; Hardened" in section
    assert section.count('class="bar-track"') == len(report.CATEGORIES) * 2  # one per V1/V2 cell
    assert 'class="v1-dot"' in section and 'class="v2-dot"' in section


def test_demo_category_bar_width_and_percent_remain_data_derived(demo_data):
    demo_data["summary_v1"]["category_stats"]["malformed"].update(failed=1, eligible=4, failure_rate=0.25)
    demo_data["comparison"]["category_failure_rates"]["malformed"]["v1"] = dict(failed=1, eligible=4, rate=0.25)
    result = html(demo_data, mode="demo")
    section = result[result.index('id="results"'):result.index('id="method"')]
    assert "25.00%" in section
    assert "1 / 4" in section
    assert 'width: 25.0%' in section


# ----------------------------------------------------------------------------------------
# V5.2 closure: no developer/CLI wording in judge-facing pages; masthead brand consistency.
# ----------------------------------------------------------------------------------------


def test_demo_report_has_no_developer_cli_instructions(demo_data):
    result = html(demo_data, mode="demo")
    assert "run_all.py" not in result
    assert "python run_all" not in result


def test_demo_partial_banner_points_to_technical_report_not_cli(demo_data):
    demo_data["detailed_report"] = {"available": True, "relative_href": "detailed/report.html"}
    result = html(demo_data, mode="demo")
    banner = result[result.index('class="partial-banner"'):result.index("</aside>")]
    assert "Technical Report" in banner
    assert "run_all.py" not in banner
    assert 'href="detailed/report.html"' in banner


def test_demo_partial_banner_mentions_technical_report_without_cli_when_no_detailed_link(demo_data):
    result = html(demo_data, mode="demo")  # no detailed_report set on this fixture
    banner = result[result.index('class="partial-banner"'):result.index("</aside>")]
    assert "Technical Report" in banner
    assert "run_all.py" not in banner


def test_reports_masthead_brand_shows_version_label(demo_data):
    # System V5.4: the masthead brand now renders from {{ creator_name }} ("Team Checkmate",
    # title case) inside .brand-creator, which applies text-transform: uppercase in CSS --
    # visually "TEAM CHECKMATE", same as web/templates/index.html's masthead -- rather than a
    # separate hardcoded uppercase literal in the template.
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode)
        header = result[result.index("<header"):result.index("</header>")]
        assert "Team Checkmate" in header
        assert 'class="brand-creator"' in header
        assert "Red Lab v5.0" in header


def test_reports_masthead_brand_uses_shared_class_names_with_web_app(demo_data):
    # System V5.4 navbar unification: report masthead brand markup uses the same class names
    # as web/templates/index.html's masthead (brand-text/brand-creator/brand-product), not the
    # old report-only brand-lines/brand-name/brand-version names.
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode)
        header = result[result.index("<header"):result.index("</header>")]
        assert 'class="brand-text"' in header
        assert 'class="brand-product"' in header
        assert "brand-lines" not in header
        assert "brand-name" not in header
        assert "brand-version" not in header


def test_report_style_css_masthead_tokens_match_web_app():
    css = (ROOT / "report" / "style.css").read_text(encoding="utf-8")
    assert "--rl-nav-height: 84px" in css
    assert "--rl-masthead-width: 1160px" in css
    assert "--rl-masthead-pad-x: 32px" in css
    assert "--report-nav-height: var(--rl-nav-height)" in css  # alias -- scrollspy JS unaffected


# ------------------------------------------------------------------------------------------
# System V5.4 final integration: native-style Back navigation on both report pages.
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["full", "demo"])
def test_report_back_is_outside_constrained_header_content(demo_data, mode):
    result = html(demo_data, mode=mode)
    header = result[result.index('<header'):result.index('</header>')]
    assert 'onclick="return rlGoBack(event)"' in header
    assert 'class="rl-back-btn"' in header
    assert 'aria-label="Back" title="Back"' in header
    assert header.index('class="rl-back-btn"') < header.index('class="masthead-inner"')


def test_reports_back_uses_shared_history_fallback_behavior(demo_data):
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode)
        assert "function rlGoBack(event)" in result
        assert "window.history.back()" in result
        assert "window.history.length > 1" in result
        assert "document.referrer" in result
        # Only the report's own inline scripts (System V5.3 invariant, extended by V6):
        # rlGoBack lives inside the end-of-body script, never in a tag of its own. The full
        # report additionally carries the <head> internal-navigation listener, which must be
        # in <head> so it is active while this large document is still parsing.
        assert result.count("<script>") == (2 if mode == "full" else 1)


def test_demo_report_csp_allows_only_its_own_inline_script(demo_data):
    result = html(demo_data, mode="demo")
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', result).group(1)
    assert "script-src 'unsafe-inline'" in csp
    assert "http" not in csp and "eval" not in csp


def test_group_key_allows_equal_category_and_subfamily(data):
    e = finding(data, subfamily="malformed")
    resolution(data, e)
    assert "malformed: request failure" in html(data)


def test_all_positive_v2_evidence_must_be_preserved(data):
    e = finding(data)
    finding(data, "v2", ids=("attack-one", "new-persistent-case"))
    resolution(data, e, "remaining", remaining=("attack-one",), improved=())
    with pytest.raises(ValueError, match="evidence does not join"):
        html(data)


def test_comparison_coverage_cannot_invent_matched_cases(data):
    data["comparison"]["coverage"]["matched_count"] = 9
    with pytest.raises(ValueError, match="completed coverage"):
        html(data)


def test_document_stylesheet_is_not_html_escaped(data):
    text = html(data)
    css = text.split("<style>", 1)[1].split("</style>", 1)[0]
    assert '"Segoe UI"' in css and ".two-up > .panel" in css
    assert "&#34;" not in css and "&gt;" not in css


def test_appendix_follows_findings_in_reading_order(data):
    text = html(data)
    assert text.index('id="findings"') < text.index('id="appendix"') < text.index('id="v1-audit"')


def test_operational_categories_preserve_error_health_separation(data):
    for v in ("v1", "v2"):
        data[f"summary_{v}"]["operational"].update(unhandled_5xx=2, timeouts=3, connection_failures=4, service_unavailable=5)
    sync(data)
    text = html(data)
    for label, n in (("Unhandled HTTP 5xx", 2), ("Request timeouts", 3), ("Connection failures", 4), ("Failed health checks", 5)):
        assert f'{label}</th><td>{n}</td><td>{n}</td>' in text


# ----------------------------------------------------------------------------------------
# System V5.3: interactive technical report -- restructured opening, complete sidebar/TOC,
# desktop collapse + mobile drawer, scrollspy, print safety. Full mode (report/template.html)
# only -- the demo report is untouched by this session.
# ----------------------------------------------------------------------------------------


def test_full_report_no_old_marketing_hero_or_cli_instructions(data):
    result = html(data)
    assert "Robustness" not in result
    assert "run_all.py" not in result
    assert "python run_all" not in result


def test_full_report_introduces_v1_and_v2_before_the_comparison(data):
    result = html(data)
    assert result.index('id="v1-intro"') < result.index('id="comparison"')
    assert result.index('id="v2-intro"') < result.index('id="comparison"')
    # ...and both endpoints are introduced before the "what changed" narrative reads them.
    assert result.index('id="overview"') < result.index('id="v1-intro"') < result.index('id="v2-intro"')


def test_full_report_states_same_underlying_model(data):
    result = html(data)
    assert "Same underlying AI model" in result


def test_full_report_v1_v2_labels_are_consistent(data):
    result = html(data)
    assert result.count("V1 &mdash; Unhardened Endpoint") == 2  # hero pill + intro card
    assert result.count("V2 &mdash; Hardened Endpoint") == 2
    assert "Hardened version" not in result
    assert "Protected API" not in result


def test_full_report_pipeline_lives_in_method_not_the_opening(data):
    result = html(data)
    assert result.index('id="overview"') < result.index('id="experiment"') < result.index('id="method"')
    assert result.index('id="method"') < result.index('id="pipeline"') < result.index('id="appendix"')
    assert result.count('aria-label="System data flow"') == 1  # not duplicated anywhere


def test_full_report_has_findings_and_evidence_navigation(data):
    result = html(data)
    toc = result[result.index('class="toc-nav"'):result.index("</nav>", result.index('class="toc-nav"'))]
    assert "Findings" in toc and 'href="#v1-findings"' in toc and 'href="#v2-findings"' in toc
    assert "Evidence" in toc and 'href="#v1-audit"' in toc and 'href="#provenance"' in toc


def test_full_report_toc_is_complete_and_every_target_resolves(data):
    e = finding(data, tiers=("SILVER",), ids=("attack-one",))
    resolution(data, e)
    result = html(data)
    doc = Document(result)
    all_ids = doc.ids
    assert len(all_ids) == len(set(all_ids)), "duplicate section/element IDs in the rendered report"
    toc = result[result.index('class="toc-nav"'):result.index("</nav>", result.index('class="toc-nav"'))]
    toc_targets = re.findall(r'href="#([^"]+)"', toc)
    assert len(toc_targets) >= 15  # a real, complete TOC -- not just Results/Findings/Method
    missing = [t for t in toc_targets if f'id="{t}"' not in result]
    assert not missing, f"sidebar links to nonexistent anchors: {missing}"
    # Every top-level report section referenced in the brief is represented.
    for label in ("Overview", "Measured Outcomes", "Findings", "Remediation", "Method", "Evidence"):
        assert label in toc


def test_full_report_sidebar_desktop_and_mobile_controls_exist(data):
    result = html(data)
    assert 'id="toc-collapse"' in result and 'aria-controls="report-toc"' in result
    assert 'id="toc-toggle"' in result and 'aria-controls="report-toc"' in result and 'aria-expanded="false"' in result
    assert 'id="toc-close"' in result
    assert 'aria-label="Report contents"' in result  # accessible label on the <aside>


def test_full_report_sidebar_hidden_and_content_full_width_in_print(data):
    css = report.HERE.joinpath("style.css").read_text(encoding="utf-8")
    print_css = css.split("@media print", 1)[1]
    assert ".report-toc, .toc-backdrop { display: none !important; }" in print_css.replace("\n", " ") or \
        (".report-toc" in print_css and "display: none" in print_css)
    assert ".toc-toggle" in print_css
    assert ".report-shell, .report-shell.toc-collapsed { display: block" in print_css.replace("\n  ", " ")


def test_full_report_source_json_home_and_pdf_preserved(data):
    result = html(data, include_pdf=True)
    header = result[result.index("<header"):result.index("</header>")]
    assert 'href="analysis.json" target="_blank" rel="noopener"' in header
    assert 'class="home-link" href="/"' in header
    assert 'href="report.pdf" download' in header


def test_full_report_grid_layout_has_no_horizontal_overflow_escape_hatch(data):
    css = report.HERE.joinpath("style.css").read_text(encoding="utf-8")
    assert ".report-shell > main { min-width: 0; }" in css


def test_full_report_scrollspy_uses_red_accent_not_teal(data):
    css = report.HERE.joinpath("style.css").read_text(encoding="utf-8")
    assert ".toc-sublist a.is-active" in css
    active_rule = css[css.index(".toc-sublist a.is-active"):css.index("}", css.index(".toc-sublist a.is-active"))]
    assert "var(--rl-red)" in active_rule


def test_full_report_csp_allows_only_its_own_inline_script(data):
    result = html(data)
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', result).group(1)
    assert "script-src 'unsafe-inline'" in csp
    assert "http" not in csp and "eval" not in csp


# ----------------------------------------------------------------------------------------
# V5.3 final polish: demo masthead spacing, sidebar collapse-at-top, Evidence & Audit
# reading-order fix, and the scrollspy root-cause fix (robust document-order tracking).
# ----------------------------------------------------------------------------------------


def test_demo_masthead_nav_items_are_structurally_separated(demo_data):
    result = html(demo_data, mode="demo")
    css = result[result.index("<style>"):result.index("</style>")]
    rule = css[css.index(".masthead nav {"):css.index("}", css.index(".masthead nav {")) + 1]
    assert "display: flex" in rule
    assert "gap:" in rule  # the actual bug: without this, <a> tags render with zero gap


def test_full_report_evidence_audit_sidebar_matches_dom_reading_order(data):
    result = html(data)
    appendix_html = result[result.index('id="appendix"'):]
    expected = ("v1-audit", "v1-validity", "v2-audit", "v2-validity", "provenance")
    dom_order = sorted(expected, key=lambda aid: appendix_html.index(f'id="{aid}"'))
    assert dom_order == list(expected)  # confirms the real DOM order this test asserts against

    sidebar_start = result.index('id="toc-group-appendix"')
    sidebar_end = result.index("</ul>", sidebar_start)
    sidebar = result[sidebar_start:sidebar_end]
    sidebar_order = re.findall(r'href="#([^"]+)"', sidebar)
    assert sidebar_order == list(expected)


def test_full_report_evidence_audit_anchors_exist_and_are_unique(data):
    result = html(data)
    doc = Document(result)
    for aid in ("v1-audit", "v1-validity", "v2-audit", "v2-validity", "provenance"):
        assert doc.ids.count(aid) == 1


def test_full_report_evidence_audit_targets_have_scroll_margin(data):
    css = report.HERE.joinpath("style.css").read_text(encoding="utf-8")
    audit_rule = css[css.index(".audit-details {"):css.index("}", css.index(".audit-details {"))]
    assert "scroll-margin-top: var(--report-nav-height)" in audit_rule
    provenance_rule = css[css.index(".provenance {"):css.index("}", css.index(".provenance {"))]
    assert "scroll-margin-top: var(--report-nav-height)" in provenance_rule


def test_full_report_scrollspy_tracks_every_toc_link_not_just_top_level(data):
    result = html(data)
    script = result[result.rindex("<script>"):]  # the end-of-body sidebar/scrollspy script
    # The observer's target set is built from every [data-toc-link] with no narrowing to
    # top-level sections only -- this is what makes the Evidence & Audit subsections (and
    # every other subsection) participate in the scrollspy at all.
    assert 'toc.querySelectorAll("[data-toc-link]")' in script
    # The actual root-cause fix: track intersection state per target and resolve to the
    # document-order-last currently-intersecting one, rather than reacting to a single
    # IntersectionObserver batch entry (which broke for closed <details> elements).
    assert "intersecting.set(entry.target, entry.isIntersecting)" in script
    assert "compareDocumentPosition" in script
    assert "aria-current" in script.split("function setActive")[1][:400]


def test_full_report_toc_collapse_is_above_the_scrollable_toc_area(data):
    result = html(data)
    sticky_head_start = result.index('class="toc-sticky-head"')
    sticky_head_end = result.index("</div>", sticky_head_start)
    scroll_start = result.index('id="toc-scroll"')
    collapse_idx = result.index('id="toc-collapse"')
    # The collapse control lives inside the sticky head, and the sticky head closes before
    # the independently-scrollable TOC area begins -- it can never be scrolled out of view.
    assert sticky_head_start < collapse_idx < sticky_head_end < scroll_start


def test_full_report_toc_scroll_is_independently_scrollable(data):
    css = report.HERE.joinpath("style.css").read_text(encoding="utf-8")
    scroll_rule = css[css.index(".toc-scroll {"):css.index("}", css.index(".toc-scroll {"))]
    assert "overflow-y: auto" in scroll_rule
    toc_rule = css[css.index(".report-toc {"):css.index("}", css.index(".report-toc {"))]
    assert "overflow-y: auto" not in toc_rule  # only the inner region scrolls, not the whole aside


def test_full_report_mobile_drawer_markup_intact(data):
    result = html(data)
    assert 'id="toc-toggle"' in result and 'aria-controls="report-toc"' in result
    assert 'id="toc-backdrop"' in result
    assert 'id="toc-close"' in result


def test_full_report_no_v54_custom_input_ui(data):
    result = html(data)
    assert "Try Your Own Input" not in result
    assert "<textarea" not in result


def test_full_report_analysis_schema_not_a_hero_badge(data):
    result = html(data)
    hero = result[result.index('id="overview"'):result.index('id="experiment"')]
    assert "Analysis schema" not in hero  # moved out of the hero entirely
    provenance = result[result.index('id="provenance"'):result.index("</section>", result.index('id="provenance"'))]
    assert "Analysis schema v2" in provenance
    assert "Red Lab v5.0" in provenance  # product version, a distinct concept, still present


def test_full_report_remediation_architecture_preserved(data):
    e = finding(data, tiers=("GOLD",), ids=("attack-one",))
    resolution(data, e)
    result = html(data)
    # Finding-level remediation is untouched.
    finding_section = result[result.index('id="findings"'):result.index('id="remediation"')]
    assert '<div class="remediation"><h5>Recommended remediation</h5>' in finding_section
    # The collected section still exists, still explains itself as a reference view, and
    # still contains the same (unaltered) remediation text.
    remediation_section = result[result.index('id="remediation"'):result.index('id="method"')]
    assert "Validate input before inference." in remediation_section
    assert "collected" in remediation_section.lower()


def test_long_unbroken_evidence_stays_on_pdf_page(data):
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        pytest.skip("Native PDF renderer unavailable on this machine")
    e = finding(data, ids=("case-" + "X" * 300,))
    resolution(data, e)
    document = HTML(string=html(data), url_fetcher=report.deny_resource).render()
    for page in document.pages:
        for box in page._page_box.descendants():
            if hasattr(box, "text") and box.text.strip():
                assert box.position_x >= 0
                assert box.position_x + box.width <= page.width + 1, box.text


# ------------------------------------------------------------------------------------------
# System V5.5 release-candidate polish: judging-rubric navigation layer.
# ------------------------------------------------------------------------------------------

RUBRIC_DIMENSIONS = {
    "Fit": ("20%", "#experiment"),
    "Relevance": ("15%", "#defenses"),
    "Prototype": ("25%", "#v1-observations"),
    "Technical Depth": ("25%", "#results"),
    "Innovation": ("15%", "#comparison"),
}


def test_full_report_sidebar_has_five_rubric_dimensions_with_percentages(data):
    result = html(data, mode="full")
    sidebar = result[result.index('id="report-toc"'):result.index("</aside>")]
    assert "Judging Rubric" in sidebar
    for name, (pct, _href) in RUBRIC_DIMENSIONS.items():
        assert name in sidebar
        assert pct in sidebar
    # Sums to 100% -- the real competition weighting, not an invented one.
    total = sum(int(pct.rstrip("%")) for pct, _ in RUBRIC_DIMENSIONS.values())
    assert total == 100


def test_full_report_rubric_links_resolve_to_real_section_ids(data):
    result = html(data, mode="full")
    sidebar = result[result.index('id="report-toc"'):result.index("</aside>")]
    for name, (_pct, href) in RUBRIC_DIMENSIONS.items():
        assert f'href="{href}"' in sidebar, f"{name} rubric link missing from sidebar"
        target_id = href.lstrip("#")
        assert f'id="{target_id}"' in result, f"{name} rubric link target #{target_id} does not exist in the report"


def test_full_report_rubric_chips_carry_text_labels_not_color_alone(data):
    result = html(data, mode="full")
    # Every in-content rubric chip repeats its dimension name and percentage as visible text
    # (never a color swatch alone) -- brief section 29/43.
    for name, (pct, _href) in RUBRIC_DIMENSIONS.items():
        chip_text = f"{name} &middot; {pct}"
        assert chip_text in result, f"missing visible rubric-chip text for {name}"


def test_full_report_rubric_does_not_use_v2_success_green():
    css = (ROOT / "report" / "style.css").read_text(encoding="utf-8")
    rubric_vars = css[css.index(".rubric-fit"):css.index(".rubric-block")]
    assert "--rl-success" not in rubric_vars
    assert "#2e7d4f" not in rubric_vars


def test_report_has_no_unsupported_superlative_claims(demo_data):
    for mode in ("demo", "full"):
        result = html(demo_data, mode=mode).lower()
        for phrase in ("world first", "world-first", "unique in the industry", "industry-leading"):
            assert phrase not in result


def test_full_report_rubric_block_hidden_on_narrow_mobile_sidebar_drawer():
    css = (ROOT / "report" / "style.css").read_text(encoding="utf-8")
    mobile_block = css[css.index("@media (max-width: 760px)"):]
    assert ".rubric-block { display: none; }" in mobile_block
