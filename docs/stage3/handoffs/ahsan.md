# Task 1 handover — Ahsan product integration

Date: 2026-09-15 (Asia/Dubai)  
Agent: Codex, working for Ahsan  
Branch: `stage3/ahsan`  
Implementation base: merge `d5c5a7bbf789bd858da021c9ccc114e349fb8448` over integrated SHA
`40ceef06cfecd10fb34ab53c5e41de35cd694ae8`

Status: **implemented and core-verified; final Task 1 acceptance blocked by two missing
cross-owner runtime inputs.** This is not a completion or deployment claim.

## Integrated dependency identity

- Rayyan handover: `44ce8d438fbe79afbb6c0bf04b2aae900ab7ef27`, merged to integration by PR #10.
- Khalid work: merged to integration by PR #7 (`71a11f7` merge), followed by the integrated
  compatibility repair `db06f6f`.
- Lamei work: merged to integration by PR #8 (`0474c74` merge), followed by OCES portability
  repairs `2864f54` and `b6891dd`.
- The authoritative tested integration snapshot before Task 1 was `40ceef06`.

## Work delivered

- `run_all.py`: preserves the original positional API/default emotion path and adds
  keyword-only evaluation selection, `html_only`, internal CI mode, trusted registry
  resolution, collision-safe IDs/directories, `run.json`, registry/selection snapshots,
  exact paired-plan reuse, sequential target lifecycle, atomic LF JSON, partial evidence,
  v3 composition, target-specific remediation, and process-tree memory measurement.
- `report/`: accepts schema v2 and v3; validates required target, family, coverage/OCES and
  remediation evidence; renders independent targets, valid comparisons only, explicit
  single-target non-comparison, denominators, exclusions, coverage and OCES provenance;
  records source/output hashes.
- `web/`: registry-backed `/api/targets`; explicit 422 and global-busy 409 responses;
  status carries run/evaluation/target identity and downloads; stale run/evaluation results
  are discarded; Demo and ephemeral Lab switch between paired emotion and a genuine
  single-target sentiment path.
- `.github/workflows/release-gate.yml`: executes `runner.gate` on the checked-out candidate,
  verifies commit/model identity, uploads evidence even on policy failure, enforces the gate
  exit code, and permits Hugging Face deployment only for a published release after a pass.
  Deployment requires environment secret `HF_TOKEN` and variable `HF_SPACE_ID`.
- `Dockerfile`: caches both model/tokenizer pairs directly from `endpoint/targets.json` at
  their exact pinned revisions.
- README/report guide and Ahsan-owned tests updated.

## Real core evidence produced by this agent

Both commands used Python 3.11 from the project `.venv`, real cached pinned weights, real
uvicorn services and the target-aware runner. Both exited 0 and left ports 8000–8002 free.

| Evaluation | Enclosing run ID | Evidence | Result |
| --- | --- | --- | --- |
| `emotion.core` demo | `0e947d4a63484cd8` | `results/task1_emotion_acceptance_0e947d4a63484cd8` | 162/1928 rows on each of `emotion_v1` and `emotion_v2`; v3 paired HTML/JSON complete |
| `sentiment.core` demo | `066e4f2f00324a68` | `results/task1_sentiment_acceptance_066e4f2f00324a68` | 162/1931 rows on `sentiment_v1`; uppercase label space; v3 HTML/JSON complete with `comparison: null` |

Evidence SHA-256, in the table order above:

- Emotion `analysis.json`: `6fe066f9502557e39f8fc6015e2f40d6c23c4e2b45e553c7a29eece3c269629e`
- Emotion `report.html`: `150c035a5d0849dc09e26e1fcdd309f024d6778d45a5df16db2acfa839648597`
- Emotion `run.json`: `5074a99d786ec41f4e2580b867ba459778145682309e2c8e1872450467400e20`
- Sentiment `analysis.json`: `6f81895468ca792dce6b7a36f5fa5294a3db9117e964461e7932eebf8f51b1c0`
- Sentiment `report.html`: `335a6bece6a1ebc3acf2f82400df6963e5d080303b4470ffde4c1a2e40b5e493`
- Sentiment `run.json`: `811818389381c54fcba4110759ff4721e7a32c571b8752bf12e884e9a07a8790`

Windows process-tree probing measured 294,629,376 bytes for the loaded sentiment endpoint
(venv launcher plus descendant). This is a best-effort per-service peak, not evidence that
only one model can be resident.

## Blocking evidence

1. OCES execution cannot start. `runner.plan_run` delegates to the allowed public call
   `attacks.library.build_suite(..., suite="oces")`, which raises `ContractError` stating
   that it generates core only. Frozen OCES JSON exists, but no public loader/registering
   function was delivered. Task 1 forbids implementing Lamei's production component as a
   workaround.
2. `analysis/policies/ci_core_v1.json` does not exist. A real invocation of `runner.gate`
   produced `results/task1_gate_missing_policy/gate_result.json`, outcome
   `execution_error`, exit 2, check `gate_policy_readable`. The clean-reference file alone
   is not a frozen policy and must not be promoted by Ahsan.

Consequences: real OCES reports, same-policy regression failure/correction pass, a candidate
unavailable-target gate run under that policy, release workflow URLs, final Docker/live
acceptance, deployment, and the five-page/20 MiB competition PDF are not available. The
workflow is real but cannot pass until the named policy exists. No regressed revision was
merged or deployed. No placeholder evidence was created.

## Validation

- Ahsan-owned focused suite after implementation: `254 passed`, one existing Starlette
  deprecation warning.
- Full non-browser suite: `1033 passed, 28 skipped`, one existing Starlette deprecation
  warning, in 85.11 seconds.
- Browser acceptance with `REDLAB_BROWSER_TESTS=1`: `27 passed`, one existing Starlette
  deprecation warning, in 74.49 seconds. A compatibility regression found during this run
  was corrected: stale-response identities are enforced when supplied, while historical
  status payloads without the new optional identity fields continue to poll.
- Release workflow YAML parsed successfully after verifying that the gate candidate identity
  uses its contracted `commit` key.
- `git diff --check`: clean (Git emitted only local autocrlf conversion notices).
- The immutable final branch-tip SHA is recorded in the PR and completion response. A commit
  cannot embed its own SHA in its contents; this handover records the tested parent/base and
  the complete validation evidence instead.

## Required next actions

1. Lamei supplies a public, isolated frozen-OCES loader through `attacks.library` (or the
   user explicitly authorizes an ownership exception).
2. Khalid resolves real CI manifest/coverage hashes, commits
   `analysis/policies/ci_core_v1.json` as frozen, and hands over its exact SHA.
3. Rebase/merge those dependencies, run emotion/sentiment OCES, then execute and preserve
   the same-policy failure/pass/error gate demonstrations.
4. Only after gate pass: build/accept the two-model container, publish a release through the
   dependent workflow, run the deployed model-switch/repeat/download journeys, and generate
   the final competition PDF from final real artifacts.

Previous verified release/rollback identity remains V6 GitHub commit `4c68d47` and Hugging
Face Space revision `732faf7`, as recorded in `HANDOFF.md`. This Task 1 work did not deploy.
