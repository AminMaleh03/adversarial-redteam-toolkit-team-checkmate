# Stage 3 decisions — what was resolved, from what source

Concrete resolutions made by the foundation task, each with the evidence it rests on, plus
the corrections the reviewed plan makes to the earlier Claude Code proposal.

Authority order: `docs/stage3/FINAL_PLAN.md` (reviewed plan) → `CONTRACTS.md` (shapes) →
this file (how a specific value was obtained). Where the earlier draft proposal disagrees
with any of these, it is superseded.

---

## A. Resolved by measurement, not assumption

### A1. The base is `a17fc5b`, not `main`

`main` is at `c507033`, four releases behind. The validated release is `ahsan/v5-redlab` @
`a17fc5b3d06f1a069ebfa0b85a95f14fe01d344e`, tag `v6.0.0` — the tagged, deployed V6.

*Source:* `git branch -vv`, `git log --decorate`, `git tag`. The uncommitted `HANDOFF.md`
edit reported in the transcript was confirmed still present and was preserved untouched.

### A2. `results/repro_1` is the raw run behind the published benchmark

`results/repro_1/report/analysis.json` is **byte-identical** to
`artifacts/verified_full_report/analysis.json`
(`12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`), which is also that
report's own recorded `source_sha256`.

*Source:* direct SHA-256 comparison; `export_meta.json`. Preserved into
`artifacts/benchmark_v6/`.

### A3. The published benchmark reproduces from source

- Rebuilding the suite at this base reproduces the recorded
  `planned_suite_sha256 = 7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430`
  and the full ordered 1928-entry planned case list.
- `attacks.library.write_manifest` reproduces
  `manifest_sha256 = 0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717`.
- Re-running `analysis.run_analysis` over the preserved bytes reproduces `schema_version`,
  `summary_v1`, `summary_v2` and `comparison` identically to the published analysis.

The claimed figures are therefore **retained**: 1,928 cases per endpoint; 29/14 finding
groups; 15 resolved / 14 remaining; flips 218/1,370 (V1) and 112/1,373 (V2).

*Caveat, recorded rather than smoothed over:* the run itself recorded **no model
revision**. `endpoint/model.py` had no `revision=` at the time; the pin was added
afterwards from the local cache state. Strongly supported, not independently attested.

### A4. "First two sorted baseline IDs" means `dataset-anger-0`, `dataset-anger-1`

`runner.run.main` sorts baselines by `baseline_id` before building and fingerprinting
([`runner/run.py`](../../runner/run.py), the `sorted(load_baseline(), ...)` call). Sorted
order is stable against `baseline.json` being written in a different file order.

*Found the hard way:* an initial fingerprint recomputation used raw file order and did not
match any of the 72 historical `run_meta` files. Reading the source resolved it — the
discrepancy was in the recomputation, not in the repository.

### A5. The frozen CI selection is 162 cases

42 baselines + 32 standalone (33 minus `malformed.oversized_10mb`) + 88 derived
(44 × 2 baselines). Ordered ids in `analysis/case_sets/ci_core_v1.json`; counts are derived
from those lists, not asserted separately.

`malformed.oversized_10mb` is excluded because a 10 MB body makes CI wall-clock and peak
memory unpredictable on a shared runner. `oversized_100kb` and `oversized_1mb` remain and
exercise the same failure mode.

### A6. Real model, tokenizer and dataset pins

| | value | how |
| --- | --- | --- |
| emotion revision | `0e1cd914e3d46199ed785853e12b57304e04178b` | `scan_cache_dir()`: `refs/main` → this commit; matches `endpoint/model.py` |
| sentiment revision | `714eb0fa89d2f80546fda750413ed43d93601a13` | `HfApi().model_info(...).sha` |
| sentiment labels | `NEGATIVE`, `POSITIVE` | `config.json` `id2label` at that revision |
| sentiment limit | 512 | `tokenizer_config.json` `model_max_length` |
| dataset revision | `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb` | `HfApi().dataset_info(...)` |
| split | `validation`, 872 rows, 428 neg / 444 pos | the parquet itself |

No weights were downloaded or loaded. Full detail: [`MODEL_IDENTITY.md`](MODEL_IDENTITY.md).

### A7. The OCES freeze point

`endpoint/v2.py`, git blob `b71787e3bf39e4062f883c9e34fae78d5b7c6263`, SHA-256
`cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e`. Byte-identical at
`c507033`, `bba3a7b` and `a17fc5b`; last content change `e23d365` (2026-09-08). Lamei
authors OCES against this exact hash. A foundation test asserts it has not drifted.

### A8. A real pre-existing bug, found and fixed

`tests/test_web.py::test_verified_full_served_bytes_match_recorded_evidence_hashes` **fails
on any fresh Windows clone of `v6.0.0`**: `artifacts/verified_full_report/analysis.json`
checks out CRLF-converted (`8a950cad…`) instead of the `12d47b35…` recorded in its own
`export_meta.json`. The deployed app would serve bytes failing their own integrity check.
It passed only in Ahsan's working copy, where the generator had written the file directly
and it was never checked out.

*Confirmed* by cloning unmodified `a17fc5b` and running that test alone. *Fixed* by
`.gitattributes` scoped to `artifacts/**` with the `binary` attribute (`-text -diff
-merge`), which also stops `git diff --check` reading preserved CRs as trailing whitespace.
Published bytes unchanged; project-wide text rules unchanged.

---

## B. Corrections to the earlier proposal — implemented as written

| # | Earlier proposal | Resolution in this foundation |
| --- | --- | --- |
| 1 | OCES negation family; directional oracles; a 0.15 score-drop threshold | **Removed.** Two families only: `oces.paraphrase`, `oces.distractor`, under the existing label-invariance oracle. `contract.OCES_FAMILIES` is the only list. A foundation test asserts no fixture mentions negation or 0.15. |
| 2 | "Design-independent" additional set | **Removed.** Required wording: *authored after the evaluated defenses were frozen; authors were aware of the defenses; not a blind holdout.* Asserted by test. |
| 3 | Input-gate checks prove the defenses are irrelevant | **Rejected.** Valid JSON, suitable type, bounded tokens and unchanged `clean_text` establish only that those specific gates accept the text unchanged. Not a proof about the exception handler, not a proof of semantic preservation. |
| 4 | A fixed 643 / 1,217 / 26 coverage split | **Not an acceptance target.** Coverage is derived from actual controls and case construction. Strict-type tests count as exercising a declared control even when V1's framework already rejects them; shared behaviour is stated via `incremental_vs_v1`. |
| 5 | Sentiment must produce 1,928 cases | **Rejected.** Sentiment has its own generated count. `endpoint/targets.json` says so explicitly. The original emotion count/fingerprint is preserved because it was verified (A3). |
| 6 | Sometimes omit, sometimes null the comparison | **`comparison: null` everywhere** for single-target. Always present, always null, never `{}`, never an improvement figure. Asserted by test. |
| 7 | Manifest text length used as the wire body size | **Rejected.** `request_body_bytes` / `request_body_sha256` are **sender-recorded**, captured from the prepared request, present even when transport then fails. |
| 8 | Enrich historical manifests in place | **Rejected.** `artifacts/benchmark_v6/` is byte-exact with no added fields. Coverage arrives as a separate `attack_id`-keyed overlay recording its own later creation time and hashes. |
| 9 | 200-eligible-case minimum; +0.05 flip tolerance; 80% positive control; blanket finding-group regression | **All removed.** Flip rates, slow counts and finding groups are informational in this first policy. |
| 10 | A 500 proves an internal crash | **Rejected.** The hardened V2 handler itself returns 500. Wording is "observed server-error response". The historical `unhandled_5xx` key is preserved for compatibility and explained. |
| 11 | Branch from `main` | **Rejected.** See A1. Base is `a17fc5b`; uncommitted work preserved; a separate worktree was used. |
| 12 | Replace `AGENTS.md` with a pointer | **Rejected.** `AGENTS.md` was updated narrowly. Every unrelated rule is preserved verbatim. |
| 13 | "607 passed" is the pass criterion | **Rejected.** It is historical. This foundation reports its own run: 681 passed, 27 skipped, from a clean clone. |
| 14 | — | Functional navigation is integration work (Task 1). The five-page limit applies only to the separate competition submission, not to the technical report. |
| 15 | Sequential startup proves one model in memory | **Rejected.** Parent processes and tokenizer helpers can retain weights. Task 1 measures the actual process tree/container. |

---

## C. Decisions the foundation made where the plan left a choice

| Decision | Choice and reason |
| --- | --- |
| Where the shared types live | `contract.py`, not a new module. The plan allows a separate module "if the actual repository requires it"; it does not. Every component already imports `contract`, so one import path with no new coupling. |
| `analysis/case_sets/` vs the policy reference path | The plan's ownership table names `analysis/policies/**` and `analysis/case_sets/**`. The frozen selection is in `case_sets/`, the approved clean-output reference in `policies/`. |
| Ports | `emotion_v1` 8000, `emotion_v2` 8001 (matching the existing `run_all.ENDPOINT_SPECS`), `sentiment_v1` 8002. Collisions are rejected at registry load. |
| Existence checks | Split out of `load_registry` into `require_runnable`. Requiring Task 2/4 files at load time would break the working emotion path for everyone until both land. |
| `.gitattributes` scope | `artifacts/** binary` — narrower than project-wide, wider than `benchmark_v6` alone, because the already-published report had the same live bug (A8). |
| `web/lab.py::_isolated_attack_registry` | **Left alone.** `scoped_registry` is opt-in; the plan says not to change existing callers until their owners wire it. Note that the existing helper snapshots without clearing, which is insufficient for suite isolation — that is exactly why `scoped_registry` clears. |
| Genuine vs synthetic fixtures | One genuine fixture (`legacy/genuine_v2_analysis.json`), produced by the real analysis code over a real subset of preserved bytes. Everything else is synthetic and says so in a `_synthetic` block. |

---

## D. Open items owned by later tasks

| Item | Owner | Note |
| --- | --- | --- |
| Manifest and coverage hashes in the CI policy | Khalid | Cannot exist before a real feature run. Procedure in `analysis/case_sets/README.md`. A draft policy **must error**, never pass. |
| Sentiment weights load and serve the pinned label space | Rayyan | Runtime acceptance, Task 2. Nothing here loaded weights. |
| No truncation anywhere on the new sentiment path | Rayyan | The standing project rule applies unchanged to the new model. Easy to reintroduce while fixing something unrelated. |
| OCES case content, tiers and freeze commit | Lamei | Must be committed **before** any inference. No model predictions while selecting or reviewing. |
| Sentiment baseline selection | Lamei | By dataset label and mechanical criteria only — never by model correctness or confidence. The validation split is a public benchmark, not a proven-unseen holdout. |
| v3 analysis, coverage, remediation, policy | Khalid | Fixtures give the target shapes; they are not an implementation. |
| UI, report, workflow, deployment, submission | Ahsan | Task 1. Not started here. |
