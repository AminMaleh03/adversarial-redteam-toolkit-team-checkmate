# Presentation fact check — 17 September 2026

> **Status update, 17 September 2026 (later the same day):** this audit's "Material OCES
> limitation" section below describes the state at `main` `724799c`, before the fix. The
> baseline-association defect it found was corrected and deployed the same day (commit
> `45c531c`, merged at `dc80f86`, live at Space revision `efa68212`). A real OCES semantic
> pass rate is now available — it is **not** "unavailable in these saved runs" as this
> section instructs the presentation to state. Corrected rates: `emotion_v1`/`emotion_v2`
> 18/18 (100.0%) each, `sentiment_v1` 26/28 (92.9%), over scored cases only (pre-declared
> REVIEW/low-confidence cases remain excluded, as before). See
> `artifacts/oces_baseline_link_v1/PROVENANCE.md` and `docs/stage3/OCES_FIX_FEASIBILITY.md`.
> Anyone using this document to brief a presentation tool should use the corrected numbers
> above in place of every "semantic pass/fail rate unavailable" instruction below.

Audited by Codex against committed `main` **724799c**, not the active older `stage3/integration` checkout (**cf4c90a**). Source presentation: `C:/Users/ahsan/Downloads/Checkmate_University of Wollongong in Dubai.pdf`. Extracted its text and visually inspected all five rendered slides. Application code, PDF and benchmark artifacts were not modified.

The ready-to-use deliverable is [PRESENTATION_CLAUDE_PROMPT.md](PRESENTATION_CLAUDE_PROMPT.md). It reconciles all 20 requests, including the later instruction to remove the custom-input card rather than merely rewrite it.

## Existing numbers

| Deck claim | Audit finding |
| --- | --- |
| Emotion: 1,928 requests per endpoint | Correct: 42 clean + 1,886 attacks each. Recorded execution, not 100% successful predictions. |
| Emotion: 91 → 0 server errors | Correct HTTP 5xx count. Does not establish process death or internal model crashes. |
| Critical and High: 7 → 0 | Correct finding-group count: V1 has 1 Critical + 6 High; V2 has neither. |
| Scored failure rate: 18.0% → 6.6% | Correct: 310/1,718 → 113/1,718. Different from flip rate and total-request failure rate. |
| 15 weakness groups resolved | Correct as groups absent from V2 on this benchmark; not a universal fix guarantee. |
| Sentiment: 1,931/1,931 | Correct: 42 clean + 1,889 attacks, one unhardened target. |
| 82 post-freeze cases | Correct only as 82 distinct attack variants across tasks: 42 emotion + 40 sentiment. Baselines add to request totals. |
| 13/13 release checks passed | Recorded statuses are correct; 11 blocking, 2 nonblocking. Ground-truth accuracy was not measured; the other nonblocking check is slow responses. |
| 1,134 automated tests passing | Historical handoff claim, not independently reproduced here. Remove the headline rather than present it as a new audit result. |
| Demo in about 40 seconds | Historical environment-dependent observation; remove the guarantee-like wording. |

## Strong additions

- **Sentiment core:** independently recomputed **99 qualifying flips / 1,604 eligible comparisons = 6.17%**, with 42/42 clean baselines above the eligibility threshold. Also recorded: 85 HTTP 5xx, 1 timeout, 18 finding groups (4 High, 14 Medium). There is no sentiment V2, so no hardening reduction can be claimed.
- **Residual emotion weakness:** independently verified the identical **58 homoglyph flip case IDs** in V1 and V2. This gives the redundant results widget a concrete purpose and supports testing prediction robustness separately from input validation.
- Emotion core flip statistics, if needed in notes, are **218/1,370 (15.91%) → 112/1,373 (8.16%)**. Both use 36/42 eligible clean baselines. These are not the deck's 18.0% → 6.6% metric.

## Material OCES limitation found in code and evidence

OCES means **Out-of-Coverage Evaluation Suite**. Its executed request counts and separate drift summaries are real:

| Target | Requests | Separate drift summary | Dedicated semantic-status block |
| --- | --- | --- | --- |
| Emotion V1 | 63 (21 seeds + 42 variants) | 0/18 qualifying flips | 20 excluded, 22 unevaluable; 0 scored |
| Emotion V2 | 63 | 0/18 qualifying flips | 20 excluded, 22 unevaluable; 0 scored |
| Sentiment V1 | 60 (20 seeds + 40 variants) | 2/28 qualifying flips | 12 excluded, 28 unevaluable; 0 scored |

All dedicated semantic rates are `numerator: 0, denominator: 0, rate: null`. They are **not zero failure rates or complete passes**.

There is a concrete baseline-association problem, not just cautious scoring: `run_all.py:_oces_block` looks up the clean row using `value.get("baseline_id")` from the attack manifest. None of the 42 emotion or 40 sentiment manifest entries has this field. The raw attack result rows do carry baseline associations, and the general drift scorer uses them correctly. The dedicated OCES scorer consequently records **“no clean baseline result for the same target”** for every non-REVIEW case. `analysis/oces.py:classify_case` excludes REVIEW cases before the lookup failure can affect their status.

This audit did not fix the implementation or regenerate evidence: the user requested a presentation prompt. The prompt explicitly retains OCES as an additional evaluation design, discloses that a semantic pass/fail rate is unavailable, and removes its zero-result success headline. Any later repair and rerun would create new evidence requiring a separate presentation update. Do not imply the current semantic evaluation is complete.

OCES was team-authored after the defences were frozen, with knowledge of the defences; it is not a blind holdout. Its 82 authoring rows are 0 GOLD / 50 SILVER / 32 REVIEW. Present it coherently with the finished design without rewriting this provenance.

## Other claims corrected

- **Three targets, two models:** emotion V1/V2 and sentiment V1. The custom-input UI selects one task: either the emotion pair or the single sentiment target.
- **Configuration-only onboarding:** overstated. A registry entry describes a target; compatible serving code, task data and validation are also needed. The completed sentiment integration demonstrates reuse, not arbitrary model onboarding.
- **“Same pinned revision” in the historical experiment:** the current loader is pinned, but the original emotion benchmark predates that pin. Its provenance supports the resolved revision without independent attestation in the original run. Use “same emotion model.”
- **“Provably safer,” “prove hardening fixes it,” and universal elimination:** finite test results do not establish those absolutes. Use observed effects within the recorded benchmark.
- **“Label accuracy” in the gate:** explicitly unmeasured in `gate_result.json`. The operative check is agreement with approved reference labels.
- **“Pass, then deploy”:** the configured release-event deploy job depends on the successful gate. A passing PR/manual check does not itself deploy; this is not proof of universal branch protection or control of manual deployments.
- **SHA-256:** all 18 master-report source hashes and lengths matched committed bytes. This validates integrity relative to the manifest, not the correctness of every interpretation or a guarantee against someone replacing both file and manifest.
- **Silent truncation:** the project's model and V2 tokenizer paths explicitly disable it. Remove it as a claimed observed failure.

## Market-research sources

The comparison is a current review of documented scope, not evidence that the team previously conducted a market survey or a competitive performance experiment:

- [TextAttack official documentation](https://textattack.readthedocs.io/en/latest/0_get_started/basic-Intro.html): NLP adversarial attacks, augmentation and training.
- [ART official documentation](https://adversarial-robustness-toolbox.readthedocs.io/en/main/): broad ML adversarial attacks, defences and evaluation.
- [garak official documentation](https://docs.garak.ai/garak): LLM vulnerability scanning.

The prompt differentiates Red Lab by the workflow demonstrated in this repository, without unsupported claims that other tools lack API testing, automation or a web interface.

## Reproduction and evidence paths

Command executed with the project's Python 3.11 environment:

```powershell
.\.venv\Scripts\python.exe results/presentation_audit/verify.py
```

Result: **PASS — 18 source hashes/lengths, 6 raw target/suite runs**, including raw row counts, 5xx, timeouts and independently reconstructed eligible flip pairs. Finding-group counts and scored failure rates were recalculated from saved analysis groups/category totals. The audit does not claim a fresh inference run or a full independent reimplementation of the failure scorer.

Machine-readable output: `results/presentation_audit/verified-metrics.json`. Extracted PDF text and page renders are in the same ignored directory. PDF tooling was installed only under `results/presentation_audit_tools`, not into the project environment or requirements.

Primary committed sources at 724799c:

- `report/master_evidence/manifest.json`
- `artifacts/verified_full_report/analysis.json`
- `artifacts/benchmark_v6/run/` and `artifacts/benchmark_v6/PROVENANCE.md`
- `artifacts/sentiment_core_v1/{analysis,run}/`
- `artifacts/emotion_oces_v1/{analysis,run}/`
- `artifacts/sentiment_oces_v1/{analysis,run}/`
- `artifacts/ci_gate_evidence_v1/gate_result.json`
- `endpoint/{targets.json,model.py,v2.py}`, `web/lab.py`
- `analysis/{drift.py,oces.py}`, `run_all.py:_oces_block`
- `.github/workflows/release-gate.yml`

No model tests or benchmark reruns were needed. No deployment, commit, push, or teammate message was performed.

## Updated deck review — 17 September 2026

Reviewed all five pages of `Checkmate_University_of_Wollongong_in_Dubai (1).pdf` by text extraction and rendered-page inspection. This is a suggestions-only follow-up; the deck and application remain unchanged.

The user accepted replacing sentiment's flip metric with 1,931 test requests executed and recorded. The new slide 5 implements that card but still mentions sentiment instability in its subtitle and 99 sentiment flips in conclusion 2. Suggested alignment: describe demonstrated pipeline reuse across emotion and sentiment instead; retain the broader lesson that residual prediction sensitivity remains.

Recounting both committed core manifests at 724799c explains the exact three-case difference: sentiment has 10 compatibility-ligature variants versus emotion's 6 (+4), and 41 adjacent-letter-swap variants versus emotion's 42 (-1). Both have 42 clean baselines and all other subfamily counts match. These are input-content-dependent transformations, not inconsistent counting. Suggested presentation shorthand: **about 1,900 requests** for each full core target, with exact 1,928 emotion and 1,931 sentiment counts retained in speaker notes/evidence. Never relabel either exact total as the other; keep 162-case CI and 1,718 scored-case denominators distinct.

Rechecked `summary_v1.category_stats.whitespace` and `summary_v2.category_stats.whitespace`: **68/210 -> 0/210 scored failures**. This is a concrete optional replacement for the prominent homoglyph widget: "Whitespace-related test failures: 68 -> 0; 210 scored cases per endpoint." Retain the visible 6.6% overall residual failure rate and a short statement that some prediction sensitivity remains. This recommendation does not claim homoglyphs were fixed.

Re-read `endpoint/v2.py:clean_text`: NFKC normalization, control/format filtering and whitespace collapse are implemented; a confusable-character-specific control is not. Unicode's official [UTS #39](https://www.unicode.org/reports/tr39/) describes confusable detection separately. Do not claim homoglyph mitigation is impossible or necessarily requires retraining. The current experiment establishes a gap in its four tested controls, not the limits of all possible hardening.

Slide 4 also omits the earlier OCES semantic-rate limitation and gives that card a green check. Suggested correction: label it additional testing and retain a short qualifier that semantic scoring is incomplete in the saved evidence; see the concrete baseline-association defect above. All follow-up edits here are recommendations, not approved presentation changes or new implementation work.
