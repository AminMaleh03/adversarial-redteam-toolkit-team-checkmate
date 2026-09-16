# OCES baseline-association correction - 17 September 2026

These are corrected analyses of the original real OCES requests, not new model runs.
The original `artifacts/emotion_oces_v1/` and `artifacts/sentiment_oces_v1/` bundles,
including every raw response, manifest and original analysis, remain unchanged.

The original inference commit was `78188adbdcb4449429116af3161a032516d38aa8`.
The affected code was audited at main `724799c`. `run_all._oces_block` incorrectly
looked for a baseline ID in an attack manifest entry; that field belongs to the
recorded attack RunResult. The correction uses that existing association to locate
the clean response within the same target. All oracle rules, validity tiers,
confidence thresholds, request data, model pins, and other analysis blocks are unchanged.

Reproduce with the project's Python 3.11 environment:

```
python artifacts/oces_baseline_link_v1/reanalyse.py
python -m report.master_evidence.build_manifest
python -m report.master_report
```

`reanalyse.py` validates the original target inputs through the normal orchestrator,
then replaces only `evaluations[0].oces` in separate derived analysis files. It asserts
that every other analysis field is unchanged. Original `run_identity` fields continue
to identify the original inference, not a new execution. `correction.json` records
hashes of the preserved inputs, original and corrected analyses, reproduction script,
and corrected orchestration function. No model inference is repeated.

| Target | Meets expectation | Violates expectation | Excluded | Unevaluable |
| --- | ---: | ---: | ---: | ---: |
| emotion_v1 | 18 | 0 | 24 | 0 |
| emotion_v2 | 18 | 0 | 24 | 0 |
| sentiment_v1 | 26 | 2 | 12 | 0 |

Emotion exclusions are 20 REVIEW cases and 4 low-confidence comparisons per target.
Sentiment excludes 12 REVIEW cases. These exclusions remain part of the predeclared
rules. The restored scored denominators and violations match the existing general
drift summaries: 0/18 for each emotion endpoint, 2/28 for sentiment.

The master technical report now reads these corrected copies. The correction does not
establish universal robustness, ground-truth accuracy, or a sentiment hardening benefit.
The optional reference-label wiring and induced-misclassification field were not changed.
OCES remains team-authored after the defences were frozen, with knowledge of those
defences, not a blind holdout. Original run provenance remains in the two original bundles.
