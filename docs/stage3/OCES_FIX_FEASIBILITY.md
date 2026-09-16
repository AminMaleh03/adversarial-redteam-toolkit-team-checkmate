# OCES baseline-link correction: feasibility verified

> **Status update, 17 September 2026 (later the same day):** the correction described below
> was applied, tested and deployed. It is commit `45c531c` on `fix/oces-baseline-link`,
> merged to `main` at `dc80f86`, live on the Hugging Face Space at revision `efa68212`. The
> corrected evidence is in `artifacts/oces_baseline_link_v1/` with its own `PROVENANCE.md`.
> Corrected pass rates: `emotion_v1` 18/18 (100.0%), `emotion_v2` 18/18 (100.0%),
> `sentiment_v1` 26/28 (92.9%) — meets-expectation over scored cases, excluding the
> pre-declared REVIEW/low-confidence exclusions. Everything below this notice is the
> original feasibility analysis, preserved as-is; it is no longer "not applied."

17 September 2026, Codex. Diagnosis against committed `main` **724799c**. Active checkout remains `stage3/integration` **cf4c90a**. User asked why OCES scoring is incomplete and whether a fix is available. This is a verified repair preview, not an applied production change.

## Cause and candidate

`run_all.py:_oces_block` builds a dictionary of actual clean result rows, keyed by `baseline_id`. It then tries to find each attack's clean result using:

```python
clean=baselines.get(value.get("baseline_id"))
```

Here `value` is an attack manifest entry, which has no `baseline_id`. The lookup returns `None` even though the correct clean row exists. `analysis.oces.classify_case` therefore marks every non-REVIEW case unevaluable. REVIEW cases are excluded earlier in the scorer.

The raw attack `RunResult` already carries the correct association. The isolated candidate changes only the clean-row lookup:

```python
clean=(
    baselines.get(attacks[attack_id].baseline_id)
    if attack_id in attacks else None
)
```

The manifest remains the source of oracle and validity-tier rules; the result row supplies only its existing baseline association. No attack metadata, threshold, contract, model, or historical record needs changing to fix this defect.

## Verified replay

Command:

```powershell
.\.venv\Scripts\python.exe results/oces_fix_check/replay.py
```

**PASS.** The script extracts the actual `_oces_block` function and exact model-free analysis modules from 724799c. It supplies committed manifests and raw result rows through a test adapter. It first reproduces the original stored OCES summaries exactly, then runs the candidate in memory. No application module is edited, no model loaded, and no original artifact rewritten.

| Target | Meets expectation | Violates expectation | Excluded | Unevaluable |
| --- | ---: | ---: | ---: | ---: |
| Emotion V1 | 18 | 0 | 24 | 0 |
| Emotion V2 | 18 | 0 | 24 | 0 |
| Sentiment V1 | 26 | 2 | 12 | 0 |

These are **candidate reanalysis results**, not newly published benchmark evidence. The restored semantic denominators and violation counts match the existing independently computed drift summaries: 0/18 for each emotion target and 2/28 for sentiment.

For each emotion endpoint, 20 REVIEW cases and 4 low-confidence comparisons remain excluded. Sentiment excludes 12 REVIEW cases. The unchanged rules exclude these legitimately; fixing the association does not make all 82 variants eligible or guarantee a perfect score.

Checks also establish that every recorded attack points to an existing same-target baseline, and that removing an actual attack or clean row still yields not-executed or unevaluable respectively. Missing records are never converted to passes.

Full reproduction script, candidate function, before/after JSON blocks and summary are under ignored `results/oces_fix_check/`. `summary.json` identifies this output explicitly as an isolated preview.

## Remaining implementation work

1. Apply the correction on a feature branch based on completed main, with a focused orchestrator regression test using manifest entries without `baseline_id` and actual result-row associations. Existing direct scorer tests pass clean rows explicitly and do not establish this connection works.
2. Preserve existing schema, thresholds and case eligibility. Maintain missing-data behaviour and target validation.
3. Separately review the optional `reference_label` argument: `_oces_block` does not currently pass it, so the induced-misclassification field is not a measured accuracy result. This does not prevent scoring prediction consistency; do not interpret it as ground-truth correctness.
4. Reanalyse the preserved raw runs and generate new, explicitly corrected reports/provenance and evidence hashes. Keep the original bundles immutable. The existing raw responses suffice for this correction; a fresh model inference run is not required to recover these scores.
5. Run relevant orchestrator/report checks and update presentation statements only after the corrected evidence is formally generated and verified. Deployment/merge/push remain separate actions.

The production correction belongs in Ahsan-owned `run_all.py` and its tests. No shared contract amendment or another owner's production-code change is required for this baseline-association fix.
