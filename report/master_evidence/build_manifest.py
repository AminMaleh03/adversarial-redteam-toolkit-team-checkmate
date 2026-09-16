"""Regenerate report/master_evidence/manifest.json from real, on-disk evidence.

This is the maintainable source-of-truth generator for the source-evidence manifest that
``report.master_report`` re-verifies at render time (see ``verify_manifest`` there). It
hashes each listed file fresh every run; it never invents or reuses a stale hash. Run
``python -m report.master_evidence.build_manifest`` after adding a new evidence source,
then re-run ``python -m report.master_report`` to pick it up.

To add a source: run the real evaluation, commit the resulting bundle under
``artifacts/<name>/`` with its own ``PROVENANCE.md`` (never hand-edit bytes after
generation), add one entry to ``SOURCES`` below, and rerun this script.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().parent / "manifest.json"

REPORT_IDENTITY = {
    "name": "Red Lab Master Technical Report",
    "product_version_label": "Red Lab v6.4",
    "contracts_version": "3.0.0",
    "generator_module": "report.master_report",
    "generator_version": "1.0.0",
    "oces_generator_version": "1.2.1",
}

EVALUATION_IDENTITIES = ["emotion.core", "sentiment.core", "emotion.oces", "sentiment.oces", "ci.emotion"]

# (id, path, classification, evaluation_id, section, description)
SOURCES = [
    ("emotion_core_historical_analysis", "artifacts/verified_full_report/analysis.json",
     "real", "emotion.core", "D",
     "Historical V5 full emotion Core benchmark analysis (V1+V2 paired, 1928/1928 each)."),
    ("emotion_core_historical_export_meta", "artifacts/verified_full_report/export_meta.json",
     "real", "emotion.core", "D", "Export hash metadata for the archived /verified-full/ bundle."),
    ("emotion_core_historical_report_html", "artifacts/verified_full_report/report.html",
     "real", "emotion.core", "D", "Archived V5 rendered report, served at /verified-full/."),
    ("emotion_core_benchmark_v6_provenance", "artifacts/benchmark_v6/PROVENANCE.md",
     "real", "emotion.core", "D", "Byte-provenance and reproduction proof for the emotion.core historical run."),
    ("emotion_core_benchmark_v6_manifest", "artifacts/benchmark_v6/run/manifest.json",
     "real", "emotion.core", "D", "Frozen request manifest for the emotion.core historical run (both endpoints)."),
    ("sentiment_core_analysis", "artifacts/sentiment_core_v1/analysis/analysis.json",
     "real", "sentiment.core", "E", "Real single-target sentiment.core run analysis (schema v3)."),
    ("sentiment_core_provenance", "artifacts/sentiment_core_v1/PROVENANCE.md",
     "real", "sentiment.core", "E", "Provenance and verified counts for the sentiment.core run."),
    ("emotion_oces_analysis", "artifacts/emotion_oces_v1/analysis/analysis.json",
     "real", "emotion.oces", "F", "Real paired emotion.oces run analysis (schema v3)."),
    ("emotion_oces_provenance", "artifacts/emotion_oces_v1/PROVENANCE.md",
     "real", "emotion.oces", "F", "Provenance and verified counts for the emotion.oces run."),
    ("emotion_oces_freeze_hashes", "artifacts/emotion_oces_v1/run/oces_freeze_content_hashes.json",
     "real", "emotion.oces", "F", "Frozen-defense content hashes recorded at emotion.oces run time."),
    ("sentiment_oces_analysis", "artifacts/sentiment_oces_v1/analysis/analysis.json",
     "real", "sentiment.oces", "F", "Real single-target sentiment.oces run analysis (schema v3)."),
    ("sentiment_oces_provenance", "artifacts/sentiment_oces_v1/PROVENANCE.md",
     "real", "sentiment.oces", "F", "Provenance and verified counts for the sentiment.oces run."),
    ("oces_review_sheet", "attacks/data/oces/oces_review_sheet.csv",
     "real", None, "F", "Pre-registered OCES case authoring sheet: 82 rows, proposed_tier column (0 GOLD / 50 SILVER / 32 REVIEW)."),
    ("ci_gate_result", "artifacts/ci_gate_evidence_v1/gate_result.json",
     "real", "ci.emotion", "H", "Real local ci.emotion gate outcome (pass, exit 0, 13/13 checks) at this milestone's commit."),
    ("ci_gate_analysis", "artifacts/ci_gate_evidence_v1/analysis/analysis.json",
     "real", "ci.emotion", "H", "Analysis document backing the local ci.emotion gate run."),
    ("ci_gate_provenance", "artifacts/ci_gate_evidence_v1/PROVENANCE.md",
     "real", "ci.emotion", "H", "Provenance for the local ci.emotion gate reproduction, incl. its relationship to the cited GitHub Actions run."),
    ("ci_policy", "analysis/policies/ci_core_v1.json",
     "real", "ci.emotion", "H", "Frozen CI release-gate policy (Khalid-owned, analysis/policies/)."),
    ("targets_registry", "endpoint/targets.json",
     "real", None, "C", "Static, model-free target/evaluation registry defining all five evaluation identities."),
]

EXTERNAL_CITATIONS = [
    {
        "id": "ci_github_actions_run",
        "description": (
            "GitHub Actions 'Stage 3 release gate' run on stage3/ahsan (PR #11), confirmed "
            "via the public GitHub REST API to have completed with conclusion success and "
            "its deploy job skipped. This session has no GitHub API token to download the "
            "run's own uploaded artifact bytes, so it is cited by run number and verified "
            "outcome only, never hashed as if its artifact were present."
        ),
        "run_number": "35075844725",
        "classification": "external_citation_unverifiable",
        "evaluation_id": "ci.emotion",
        "section": "H",
    },
]

NOT_APPLICABLE = [
    {
        "field": "sentiment.core / sentiment.oces hardening comparison",
        "reason": "There is no sentiment_v2 target. comparison is null in both analysis documents by contract; no before/after claim is made.",
    },
    {
        "field": "emotion.core / emotion.oces model revision independent attestation",
        "reason": "artifacts/benchmark_v6/PROVENANCE.md: the historical run predates revision pinning; the revision is strongly supported (re-verified cache scan) but not recorded by the run itself.",
    },
    {
        "field": "OCES GOLD-tier cases",
        "reason": "attacks/data/oces/oces_review_sheet.csv proposed_tier column contains zero GOLD rows (0 GOLD / 50 SILVER / 32 REVIEW of 82).",
    },
]


def build() -> dict:
    sources = []
    for source_id, rel_path, classification, evaluation_id, section, description in SOURCES:
        data = (ROOT / rel_path).read_bytes()
        sources.append({
            "id": source_id, "path": rel_path, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "classification": classification, "evaluation_id": evaluation_id,
            "section": section, "description": description,
        })
    return {
        "report_identity": REPORT_IDENTITY,
        "evaluation_identities": EVALUATION_IDENTITIES,
        "sources": sources,
        "external_citations": EXTERNAL_CITATIONS,
        "not_applicable": NOT_APPLICABLE,
    }


def main() -> int:
    manifest = build()
    OUT_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} with {len(manifest['sources'])} sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
