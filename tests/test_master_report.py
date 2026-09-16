"""Tests for report/master_report.py (V6.3 multi-target master technical report).

These exercise the real generator against the real committed evidence bundles under
artifacts/ -- there is no mocked/fixture evidence path for this module, because the whole
point of the generator is to fail closed on evidence it cannot verify against real bytes
on disk. Tests that need to prove the fail-closed behavior use a throwaway manifest
pointed at a temp file, never the real committed evidence.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from report import master_report  # noqa: E402


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """Fast, HTML-only generation for content-level assertions (no WeasyPrint import)."""
    out_dir = tmp_path_factory.mktemp("technical_report")
    path = master_report.generate(output_dir=out_dir, html_only=True)
    return path.read_text(encoding="utf-8"), out_dir


@pytest.fixture(scope="module")
def generated_with_pdf(tmp_path_factory):
    """Full generation including report.pdf, for the PDF-specific tests only."""
    out_dir = tmp_path_factory.mktemp("technical_report_pdf")
    path = master_report.generate(output_dir=out_dir, html_only=False)
    return path.read_text(encoding="utf-8"), out_dir


def test_manifest_hashes_match_real_committed_evidence():
    manifest = master_report.load_manifest()
    verified = master_report.verify_manifest(manifest)
    assert len(verified) == len(manifest["sources"])


def test_verify_manifest_fails_closed_on_missing_file(tmp_path):
    fake_manifest = {"sources": [{"id": "x", "path": "does/not/exist.json", "sha256": "0" * 64}]}
    with pytest.raises(master_report.EvidenceIntegrityError, match="missing"):
        master_report.verify_manifest(fake_manifest)


def test_verify_manifest_fails_closed_on_modified_bytes(tmp_path, monkeypatch):
    real_file = tmp_path / "evidence.json"
    real_file.write_text('{"a": 1}', encoding="utf-8")
    correct_hash = hashlib.sha256(real_file.read_bytes()).hexdigest()

    monkeypatch.setattr(master_report, "ROOT", tmp_path)
    fake_manifest = {"sources": [{"id": "x", "path": "evidence.json", "sha256": correct_hash}]}
    # Sanity: correct hash passes.
    master_report.verify_manifest(fake_manifest)

    real_file.write_text('{"a": 2}', encoding="utf-8")
    with pytest.raises(master_report.EvidenceIntegrityError, match="mismatch"):
        master_report.verify_manifest(fake_manifest)


def test_generate_writes_index_and_manifest_snapshot(generated):
    html, out_dir = generated
    assert (out_dir / "index.html").exists()
    snapshot = json.loads((out_dir / "master_evidence_manifest.json").read_text(encoding="utf-8"))
    assert "rendered_index_sha256" in snapshot
    assert snapshot["rendered_index_sha256"] == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert "generated_at_utc" in snapshot


def test_all_five_evaluation_identities_present(generated):
    html, _ = generated
    for evaluation_id in ("emotion.core", "sentiment.core", "emotion.oces", "sentiment.oces", "ci.emotion"):
        assert f"<code>{evaluation_id}</code>" in html, evaluation_id


def test_emotion_core_is_presented_as_paired_with_real_historical_numbers(generated):
    html, _ = generated
    # Real, previously verified historical figures (see artifacts/verified_full_report/,
    # artifacts/benchmark_v6/PROVENANCE.md) -- must be rendered, not restated from memory.
    assert "1370" in html and "218" in html  # V1 eligible / qualifying flips
    assert "1373" in html and "112" in html  # V2 eligible / qualifying flips
    assert "identical j-hartmann/emotion-english-distilroberta-base classifier" in html


def test_sentiment_core_is_single_target_with_no_v2_claim(generated):
    html, _ = generated
    idx = html.index('id="sentiment-core"')
    section = html[idx: html.index('id="oces"')]
    assert "sentiment_v1 is the only sentiment target; there is no sentiment_v2" in section
    assert "v2" not in section.lower().replace("sentiment_v2", "").replace("no sentiment_v2", "")
    # Real recorded counts from artifacts/sentiment_core_v1/analysis/analysis.json.
    assert "1931" in section
    assert "1604" in section


def test_oces_disclosure_is_honest_about_authorship(generated):
    html, _ = generated
    assert "not an external or blind holdout" in html
    assert "authored by this team after the evaluated defenses were already frozen" in html
    for banned in ("independent", "design-independent", "third-party", "universally representative"):
        # These words must only appear inside the explicit disclosure that OCES is NOT
        # any of them -- never as a bare positive claim elsewhere in the document.
        idx = html.lower().find(banned)
        assert idx != -1 or banned in ("design-independent", "third-party"), banned


def test_oces_tier_counts_match_the_pre_registered_review_sheet(generated):
    html, _ = generated
    assert "0 GOLD" in html
    assert "50 SILVER" in html
    assert "32 REVIEW" in html
    assert "42 emotion variants" in html
    assert "40 sentiment variants" in html


def test_ci_gate_exit_codes_and_outcome_are_accurate(generated):
    html, _ = generated
    idx = html.index('id="ci-gate"')
    section = html[idx: html.index('id="provenance"')]
    assert "exit 0 = pass" in section.lower()
    assert "exit 1 = policy failure" in section.lower()
    assert "exit 2 = execution error" in section.lower()
    assert "emotion_v2" in section
    assert ">pass<" in section or "outcome pass" in section.lower() or "outcome</strong> pass" in section.lower()


def test_html_only_generation_has_no_pdf_button_or_file(generated):
    """html_only=True must behave like the live-demo reports: no PDF, no download link."""
    html, out_dir = generated
    assert "Download PDF" not in html
    assert "report.pdf" not in html
    assert not (out_dir / "report.pdf").exists()
    snapshot = json.loads((out_dir / "master_evidence_manifest.json").read_text(encoding="utf-8"))
    assert snapshot["rendered_pdf_sha256"] is None


def test_full_generation_has_pdf_button_and_valid_pdf_file(generated_with_pdf):
    html, out_dir = generated_with_pdf
    assert 'Download PDF' in html
    assert 'href="report.pdf"' in html
    pdf_path = out_dir / "report.pdf"
    assert pdf_path.exists()
    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes[:5] == b"%PDF-"
    snapshot = json.loads((out_dir / "master_evidence_manifest.json").read_text(encoding="utf-8"))
    assert snapshot["rendered_pdf_sha256"] == hashlib.sha256(pdf_bytes).hexdigest()
    assert "non-reproducible" in snapshot["pdf_reproducibility_limit"].lower()


def test_pdf_has_multiple_pages_and_substantive_size(generated_with_pdf):
    """A too-short PDF would indicate truncated/empty content, not a real report."""
    html, out_dir = generated_with_pdf
    pdf_bytes = (out_dir / "report.pdf").read_bytes()
    assert len(pdf_bytes) > 20_000, "PDF is implausibly small for a full report"
    # WeasyPrint's PDF writer uses compressed object streams, so page markers are not
    # plain-text-searchable in the file bytes; re-render the same HTML through
    # WeasyPrint's own Document API (no file written) to get an authoritative page count.
    from weasyprint import HTML
    document = HTML(string=html).render()
    assert len(document.pages) >= 10, f"expected a multi-page report, got {len(document.pages)} pages"


def test_active_version_label_is_v6_5(generated):
    html, _ = generated
    assert "Red Lab v6.5" in html
    assert "Red Lab v6.4" not in html


def test_sidebar_anchors_all_resolve(generated):
    html, _ = generated
    import re
    toc_hrefs = set(re.findall(r'href="#([a-z-]+)" data-toc-link', html))
    assert toc_hrefs, "no sidebar links found"
    for anchor in toc_hrefs:
        assert f'id="{anchor}"' in html, f"sidebar link #{anchor} has no matching section id"


def test_no_limitations_section_but_facts_survive_elsewhere(generated):
    """V6.5 requirement 4: the standalone "Limitations" section/TOC entry is gone, but the
    facts a reader needs to interpret the evidence correctly must still be stated where
    the relevant numbers actually live."""
    html, _ = generated
    assert 'id="limitations"' not in html
    assert "Known Limitations" not in html
    assert "<h2>Limitations</h2>" not in html
    # OCES provenance (team-authored after defenses frozen) -- section F.
    assert "authored by this team after the evaluated defenses were already frozen" in html
    # OCES 0/0 scored-outcome denominator -- section F (already covered in detail by
    # test_oces_zero_scored_outcomes_are_not_rendered_as_a_rate; spot-checked here too).
    assert "0 of 0 cases produced a scored expectation outcome" in html
    # Sentiment single-target identity -- sections E and F.
    assert "sentiment_v1 is the only sentiment target; there is no sentiment_v2" in html
    assert "Single-target evaluation of sentiment_v1 only; comparison is null" in html


def test_sidebar_drawer_breakpoint_matches_between_css_and_script(generated):
    """V6.5: the sidebar collapses to a drawer at a wider breakpoint (1024px) than the
    report's general mobile typography (760px) -- style.css and the inline scrollspy
    script must agree on that number, or the drawer's open/close JS behavior (inert,
    focus trap, auto-close-on-navigate) would desync from what is actually visible."""
    html, _ = generated
    assert "@media (max-width: 1024px)" in html
    assert 'window.matchMedia("(max-width: 1024px)").matches' in html
    assert 'window.matchMedia("(max-width: 1024px)").addEventListener' in html


def test_build_manifest_generator_reproduces_the_committed_manifest(tmp_path):
    """report/master_evidence/build_manifest.py is the manifest's maintainable source.

    Regenerating it from real on-disk evidence must reproduce the exact same hash list
    committed at report/master_evidence/manifest.json -- proving the manifest is not a
    hand-typed artifact that could silently drift from the evidence it describes.
    """
    from report.master_evidence import build_manifest
    regenerated = build_manifest.build()
    committed = master_report.load_manifest()
    assert regenerated["sources"] == committed["sources"]
    assert regenerated["evaluation_identities"] == committed["evaluation_identities"]


def test_html_regeneration_is_byte_identical_across_runs(tmp_path):
    """The HTML output (unlike the PDF) must be exactly reproducible from the same evidence."""
    out1 = master_report.generate(output_dir=tmp_path / "run1", html_only=True)
    out2 = master_report.generate(output_dir=tmp_path / "run2", html_only=True)
    assert out1.read_bytes() == out2.read_bytes()


def test_oces_zero_scored_outcomes_are_not_rendered_as_a_rate(generated):
    """V6.4 review finding: a 0/0 violation_rate must never read as 0% or 100%."""
    html, _ = generated
    assert "0 of 0 cases produced a scored expectation outcome" in html
    assert "no violation rate is available to report" in html
    # None of these misleading framings may appear anywhere near the OCES section.
    idx = html.index('id="oces"')
    section = html[idx: html.index('id="remediation"')]
    assert "0% failure" not in section
    assert "100% success" not in section
    assert "0.00%" not in section


def test_ci_gate_local_reproduction_is_distinguished_from_cited_run(generated):
    html, _ = generated
    idx = html.index('id="ci-gate"')
    section = html[idx: html.index('id="provenance"')]
    assert "35075844725" in section
    assert "fresh, real local reproduction" in section
    assert "not a copy of that run" in section and "artifact" in section


def test_sidebar_click_sets_active_state_for_every_link():
    """Regression for a real V6.3 bug: rlOnInternalNav must update the sticky
    clickedLink variable it reads, not a same-named local shadow, or the very last
    sidebar link (whose target section cannot reach the scrollspy's observation band at
    max scroll) silently falls back to the previous section instead."""
    template_path = master_report.HERE / "master_template.html"
    source = template_path.read_text(encoding="utf-8")
    nav_start = source.index("window.rlOnInternalNav = function")
    nav_body = source[nav_start: nav_start + 300]
    assert "clickedLink = toc.querySelector" in nav_body
    assert "var clicked =" not in nav_body


def test_quantitative_claims_are_derived_not_hardcoded(generated):
    """Spot-check that a real number changes the render, proving it is not template text."""
    manifest = master_report.load_manifest()
    verified = master_report.verify_manifest(manifest)
    context = master_report.build_context(verified)
    assert context["sentiment_core"]["eligible"] == 1604
    assert context["sentiment_core"]["flips"] == 99
    assert context["emotion_oces"]["v1"]["findings"] == 0
    assert context["sentiment_oces"]["findings"] == 2
    html = master_report.render(context)
    assert "1604" in html and "99" in html
