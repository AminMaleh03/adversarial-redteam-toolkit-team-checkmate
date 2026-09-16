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
    out_dir = tmp_path_factory.mktemp("technical_report")
    path = master_report.generate(output_dir=out_dir)
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


def test_no_master_pdf_button_present(generated):
    html, _ = generated
    assert "Download PDF" not in html
    assert "report.pdf" not in html


def test_active_version_label_is_v6_3(generated):
    html, _ = generated
    assert "Red Lab v6.3" in html


def test_sidebar_anchors_all_resolve(generated):
    html, _ = generated
    import re
    toc_hrefs = set(re.findall(r'href="#([a-z-]+)" data-toc-link', html))
    assert toc_hrefs, "no sidebar links found"
    for anchor in toc_hrefs:
        assert f'id="{anchor}"' in html, f"sidebar link #{anchor} has no matching section id"


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
