# Stage 3 foundation readiness report

Prepared 2026-09-15 by Claude Opus 5 in Ahsan's repository, under Task 5.

# Status: FOUNDATION_READY

All four members can start. The shared contracts, registry, evidence, frozen CI inputs and
fixture pack are committed, tested and published.

This supersedes the earlier NOT_READY report in this file. That verdict was raised because
the reviewed plan and the Task 1–4 descriptions had not been supplied; they were then
supplied in full, are now checked in verbatim under `docs/stage3/`, and the blocker is
resolved. Nothing else in the earlier report was retracted — the evidence and identity work
it described is unchanged and still verified.

### Commit-reference strategy (avoids self-reference)

A commit cannot contain its own SHA, so the **tested foundation** is referenced by tag:

| Reference | Meaning |
| --- | --- |
| tag `stage3-foundation-v1` | The exact tree every result below was measured against. |
| branch `stage3/foundation` | Where the foundation lives. |
| branch `stage3/integration` | The common integration branch, cut from the same commit. |

The commit that adds *this document* is the tagged foundation commit's parent-side
documentation; the tag is applied to the final commit and its full SHA is reported in chat
and in `HANDOFF.md`, not inside this file. If the foundation is amended later, cut a new
tag and update this table — a documentation commit is never itself a tested foundation.

---

## 1. Base and preservation

| Item | Value |
| --- | --- |
| Validated release identified | `ahsan/v5-redlab` @ `a17fc5b3d06f1a069ebfa0b85a95f14fe01d344e`, tag `v6.0.0` |
| Why not `main` | `main` is `c507033`, four releases behind. `a17fc5b` is the tagged, deployed V6. |
| Remote | `origin` → `github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate` |
| Method | A separate worktree at `C:/Users/ahsan/OneDrive/Desktop/stage3-foundation`, branch `stage3/foundation`, created from `a17fc5b`. |
| Environment | Python 3.11.9 in `.venv`, Windows 11, `core.autocrlf=true` |

**Pre-existing work preserved.** The uncommitted `HANDOFF.md` edit in the main checkout
(Codex's reference-document audit) is untouched. No reset, stash, discard or force-push.
`main`, `ahsan/report`, `ahsan/v5-redlab` and `runner-amin` are unchanged, and no existing
branch was overwritten. The main checkout is still on `ahsan/v5-redlab`.

---

## 2. Contracts and shared symbols

**`CONTRACTS.md` version 3.0.0.** `contract.py` is the single import path; `CONTRACTS_VERSION`
matches the document heading.

`RunResult` gains four **appended** fields with backward-compatible defaults, exactly as the
plan specifies. Existing fields and their order are untouched, every existing positional
construction still works, and every preserved historical row still loads:

| Field | Type | Default |
| --- | --- | --- |
| `target_id` | `str` | `""` |
| `suite_id` | `str` | `""` |
| `request_body_bytes` | `int \| None` | `None` |
| `request_body_sha256` | `str \| None` | `None` |

`BaselineCase`, `AttackCase` and `Finding` are **structurally unchanged** (asserted by test).

New model-free shared symbols in `contract.py`: `ContractError`, `ModelSpec`, `TaskSpec`,
`TargetSpec`, `EvaluationSpec`, `Registry`, `CheckResult`, `GateOutcome`, plus the
`SUITE_*`, `EVAL_KIND_*`, `EVAL_MODE_*`, `OCES_FAMILY_*`, `OCES_FAMILIES`, `CORE_FAMILIES`,
`COVERAGE_*`, `CHECK_*`, `OUTCOME_*` and `EXIT_CODE_BY_OUTCOME` constants.

These enforce rather than describe: `ModelSpec` rejects anything that is not an exact 40-hex
pin; `GateOutcome` rejects a wrong exit code, zero checks, an all-`not_applicable` "pass",
a `pass` alongside a failing blocking check, a `policy_failure` with nothing failing, and an
`execution_error` with nothing errored.

**Approved import edges** (in `AGENTS.md` and `CONTRACTS.md` §9): `runner.gate → run_all`
and `→ analysis.policy`; `runner.run → endpoint.targets` (model-free) and the attack
library; analysis reads manifests and overlays from artifacts. Two edges must not exist:
**analysis never imports `attacks/`**, and **`run_all` never imports `runner.gate`**.

**Ownership** is in `docs/stage3/OWNERSHIP.md` and the `AGENTS.md` table: Rayyan gains
`runner/`, Lamei gains `baseline/`, Ahsan owns `run_all.py` and `web/`, Khalid owns
`analysis/**` including `policies/` and `case_sets/`. **No dependency on Amin.** The
contract-amendment procedure is recorded in both `AGENTS.md` and `CONTRACTS.md` §10.

---

## 3. Registry

`endpoint/targets.py` + `endpoint/targets.json`, with real references. One-time foundation
ownership; transfers to Rayyan.

The five evaluations are exactly as specified:

| `evaluation_id` | kind | targets | suite | baseline file resolved |
| --- | --- | --- | --- | --- |
| `emotion.core` | paired | `emotion_v1`, `emotion_v2` | `core` | `baseline/baseline.json` |
| `emotion.oces` | paired | `emotion_v1`, `emotion_v2` | `oces` | `baseline/oces/emotion_seeds.json` |
| `sentiment.core` | single | `sentiment_v1` | `core` | `baseline/sentiment_baseline.json` |
| `sentiment.oces` | single | `sentiment_v1` | `oces` | `baseline/oces/sentiment_seeds.json` |
| `ci.emotion` | single | `emotion_v2` | `core`, `case_set_id=ci_core_v1`, `mode=ci` | `baseline/baseline.json` |

The two OCES seed-file overrides resolve through `registry.baseline_file_for()`, so a run
records the hash of the file it actually used — never the unrelated core baseline hash.
There is no `ci_core` suite; CI is a frozen selection of `core`.

**Loading imports no model.** A subprocess check confirms `torch`, `transformers` and
`endpoint.model` are all absent from `sys.modules` after `load_registry()`. Path syntax and
every cross-reference are validated at load; **existence** of a future module or baseline
file is checked by `require_runnable()` at execution time, so the missing Task 2/4 files do
not break the working emotion path. Verified now: `emotion.core` and `ci.emotion` have no
missing requirements; `sentiment.core` correctly reports both files as still absent.

---

## 4. Model, tokenizer and dataset pins — real, no placeholders

| | repo id | revision (40 hex) | labels | limit |
| --- | --- | --- | --- | --- |
| emotion | `j-hartmann/emotion-english-distilroberta-base` | `0e1cd914e3d46199ed785853e12b57304e04178b` | 7 emotion labels | 512 |
| sentiment | `distilbert/distilbert-base-uncased-finetuned-sst-2-english` | `714eb0fa89d2f80546fda750413ed43d93601a13` | `NEGATIVE`, `POSITIVE` | 512 |
| dataset | `stanfordnlp/sst2` | `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb` | validation, 872 rows, 428/444 | — |

The emotion pin was re-verified against the local cache (`refs/main` → `0e1cd914…`). **No
weights were downloaded or loaded** anywhere in this task; only metadata and tokenizer
config. Detail, including the SST-2 selection rules, is in
[`MODEL_IDENTITY.md`](MODEL_IDENTITY.md).

### Runtime checks that remain, and whose they are

| Check | Owner |
| --- | --- |
| Sentiment weights load at the pinned revision and the served endpoint returns the pinned label space verbatim | Rayyan (Task 2) |
| No truncation anywhere on the new sentiment path — pipeline, direct tokenizer call, handler | Rayyan (Task 2) |
| A target whose loaded identity contradicts its declared identity fails the run | Rayyan (Task 2) |
| Real generated sentiment case count (**not** required to be 1,928) | Lamei (Task 4) / Rayyan (Task 2) |
| Manifest and coverage hashes in the CI policy, resolved from real artifacts | Khalid (Task 3) |
| OCES content, tier decisions and freeze commit, before any inference | Lamei (Task 4) |

---

## 5. Original evidence and frozen CI inputs

`artifacts/benchmark_v6/` — nine files copied **byte-exact** from `results/repro_1`, with
[`PROVENANCE.md`](../../artifacts/benchmark_v6/PROVENANCE.md). No field was added to any
original manifest or run metadata; the published report is untouched.

| Path | SHA-256 |
| --- | --- |
| `run/manifest.json` | `0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717` |
| `run/results_v1.jsonl` | `f617ac34a1a0148ee4507491effcf89183fbc3c5c385416f0a554ef1a4ebcb82` |
| `run/results_v2.jsonl` | `0b37eb18b91521ea6bb0228462a1cf3fef85c2580e0d178a2502bac50a79273f` |
| `run/run_meta_v1.json` | `e32d8a68409ea6df301b296cfdfaa0fcc57ea1d104e6cb10f94140308ea67c04` |
| `run/run_meta_v2.json` | `646170e1143d9a8d6130baa9899432130c626fcaeb394428824c629bdc8ca276` |
| `run/demo_evidence.json` | `ecdf11d687076082b4b40ea64e2eb1e1a178860ba4b59393e78e409dfeb85792` |
| `analysis/analysis.json` | `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da` |
| `analysis/export_meta.json` | `e1212b048a380f59f56c2cd926fd79cf7464afe7ca937651952d04b0afa042e5` |
| `source/baseline.json` | `78ea8914dd7aeade060a10d9a14671c3ed455cbe9a3ae087b63ab448db7c0ace` |

Three independent reproductions: the suite fingerprint `7fcccf16…a430` and the full ordered
1928-entry planned list re-derive from source; the manifest `0471bccb…a717` re-derives from
source and equals the preserved file; and re-running `analysis.run_analysis` over the
preserved bytes reproduces `schema_version`, `summary_v1`, `summary_v2` and `comparison`
identically to the published analysis, **from a clean clone**. The claimed figures
(1,928 cases; 29/14 finding groups; 15 resolved / 14 remaining; flips 218/1,370 and
112/1,373) are therefore retained.

Limitations are recorded, not smoothed over: the benchmark run **recorded no model
revision** (the pin was added afterwards), and it has **no sender-recorded request-byte
evidence**, so findings needing it are *unavailable*, not absent. Legacy mapping
(`v1→emotion_v1`, `v2→emotion_v2`) is explicit and scoped to that directory.

**Frozen CI selection** — `analysis/case_sets/ci_core_v1.json`, documented in
[`analysis/case_sets/README.md`](../../analysis/case_sets/README.md):

- 42 baselines + 32 standalone + 88 derived = **162 cases**, as ordered id lists.
- Sole exclusion `malformed.oversized_10mb`, with a recorded rationale.
- Derived coverage = the first two sorted baseline ids, `dataset-anger-0` and
  `dataset-anger-1` (the runner sorts by id before building, so this is well defined).
- Every selected id was checked to exist in the source manifest or planned baseline list.
- **Approved clean reference** in `analysis/policies/ci_core_v1_clean_reference.json`: real
  top labels for all 42 baselines from the verified `emotion_v2` rows, explicitly labelled a
  regression reference and **not** ground truth.
- **No hash that cannot exist yet.** The resolution procedure for the manifest and coverage
  hashes is written down, and a draft policy **must error**, never pass.

**OCES freeze point** recorded for Lamei: `endpoint/v2.py`, blob
`b71787e3bf39e4062f883c9e34fae78d5b7c6263`, SHA-256
`cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e`, byte-identical at
`c507033`, `bba3a7b` and `a17fc5b`. No OCES case was authored or run here.

---

## 6. Fixture pack

`tests/fixtures/stage3/` — 53 files, ~352 KiB, fully offline, built by a committed
deterministic generator that validates its own output.

Four evaluations with coherent results, manifests, run metadata, coverage, a case
selection, a registry snapshot and a `run.json` index; a complete `expected_analysis_v3.json`;
five gate outcomes covering exit 0/1/2 plus all-rejecting and wrong-clean-output; API
status examples including a **stale** poll; remediation examples including one with missing
request-byte evidence and one model-level fix; and eleven negative fixtures each with a
recorded reason.

Every hash is a real SHA-256 of the bytes it describes. Every synthetic artifact carries a
`_synthetic` block. `legacy/genuine_v2_analysis.json` is **genuine** — produced by the real
`analysis.run_analysis` over a real subset of the preserved benchmark bytes.

**These fixtures do not prove any feature works.** They demonstrate agreed shapes and
arithmetic. A page rendered from them is a shape check, not a product demonstration.

---

## 7. Verification — exact commands and real results

All run on Windows with `.venv` (Python 3.11.9), against the tree tagged
`stage3-foundation-v1`.

| # | Command | Result |
| --- | --- | --- |
| 1 | `.\.venv\Scripts\python.exe -m pytest -q` | **681 passed, 27 skipped, 1 warning** |
| 2 | `.\.venv\Scripts\python.exe -m pytest -q tests/test_stage3_foundation.py` | **101 passed** |
| 3 | Clean clone (`git clone --no-local --branch stage3/foundation`) then `python -m pytest -q` | **681 passed, 27 skipped** |
| 4 | `python tests/fixtures/stage3/build_fixtures.py` | `validation: OK`, 53 files, 351.8 KiB; rebuild is byte-identical |
| 5 | `git diff --check` | clean |
| 6 | Evidence byte-exactness after a fresh clone | all 9 preserved files match |
| 7 | `verified_full_report` vs its own `export_meta.json`, after a fresh clone | `report.html`, `analysis.json`, `report.pdf` all match |
| 8 | Benchmark reproduction from the clean clone | `summary_v1`, `summary_v2`, `comparison` identical to published |
| 9 | Registry import in a subprocess | no `torch`, `transformers` or `endpoint.model` in `sys.modules` |

The 681 comprises the 580 pre-existing tests plus 101 new foundation tests. **The historical
"607 passed" was not used as evidence for anything.**

**Skips: 27, all pre-existing and unrelated** — browser/UI tests needing Playwright, and
WeasyPrint-dependent paths (WeasyPrint import failure is a documented, expected condition
for everyone but Ahsan).

### A real pre-existing bug, found and fixed

`tests/test_web.py::test_verified_full_served_bytes_match_recorded_evidence_hashes` **fails
on any fresh Windows clone of `v6.0.0`**: `artifacts/verified_full_report/analysis.json`
checks out CRLF-converted (`8a950cad…`) instead of the `12d47b35…` recorded in its own
`export_meta.json`, so the deployed app would serve bytes failing their own integrity check.
It passed only in Ahsan's working copy, where the generator had written the file directly.

Confirmed by cloning unmodified `a17fc5b` and running that test alone. Fixed with a
`.gitattributes` scoped to `artifacts/**`. Published bytes are unchanged; project-wide text
rules are unchanged.

Two further defects were caught by the new foundation tests during development — a stale
fixture manifest and a non-renormalised worktree copy — and both were fixed before commit.

---

## 8. Files added and changed

**Added**

```
.gitattributes
CONTRACTS.md
endpoint/targets.py
endpoint/targets.json
analysis/case_sets/README.md
analysis/case_sets/ci_core_v1.json
analysis/policies/ci_core_v1_clean_reference.json
artifacts/benchmark_v6/PROVENANCE.md
artifacts/benchmark_v6/analysis/analysis.json          (byte-exact copy)
artifacts/benchmark_v6/analysis/export_meta.json       (byte-exact copy)
artifacts/benchmark_v6/run/demo_evidence.json          (byte-exact copy)
artifacts/benchmark_v6/run/manifest.json               (byte-exact copy)
artifacts/benchmark_v6/run/results_v1.jsonl            (byte-exact copy)
artifacts/benchmark_v6/run/results_v2.jsonl            (byte-exact copy)
artifacts/benchmark_v6/run/run_meta_v1.json            (byte-exact copy)
artifacts/benchmark_v6/run/run_meta_v2.json            (byte-exact copy)
artifacts/benchmark_v6/source/baseline.json            (byte-exact copy)
docs/stage3/FINAL_PLAN.md                              (verbatim from the task pack)
docs/stage3/TASK_PACK_README.md                        (verbatim)
docs/stage3/tasks/task_1_ahsan.md … task_5_foundation.md  (verbatim, byte-verified)
docs/stage3/OWNERSHIP.md
docs/stage3/DECISIONS.md
docs/stage3/MODEL_IDENTITY.md
docs/stage3/FOUNDATION_READINESS.md
docs/stage3/handoffs/README.md
tests/test_stage3_foundation.py
tests/fixtures/stage3/**                               (53 files)
```

**Modified** — four files, all additive

```
contract.py          four appended RunResult fields + new shared types; nothing reordered
attacks/metadata.py  scoped_registry added; no existing caller changed
AGENTS.md            ownership table, Stage 3 import edges, pointer to the final contract
CLAUDE.md            pointer to the Stage 3 documents
HANDOFF.md           checkpoint (on this branch only)
```

`endpoint/model.py`, `endpoint/v1.py`, `endpoint/v2.py`, `baseline/**`, `attacks/` (other
than the added context manager), `runner/**`, `analysis/` (other than the new data files),
`report/**`, `web/**` and `run_all.py` are **untouched**. Task 1–4 work is not started.

The five task descriptions were verified byte-identical to the standalone files supplied
alongside the combined pack before being committed.

---

## 9. Branches and how each member starts

All five branch tips are the **same** foundation commit.

```bash
git fetch origin
git checkout -b stage3/<your-name> origin/stage3/<your-name>
git rm --cached -r -q . && git reset --hard      # see the note below; safe, no content change
py -3.11 -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt   # if needed
.\.venv\Scripts\python.exe -m pytest -q                                     # expect 681 passed, 27 skipped
```

**Why the `git rm --cached` line, on Windows.** This foundation adds a `.gitattributes`
that stops `core.autocrlf` rewriting files whose SHA-256 is recorded and asserted. Git
applies checkout conversion only to files whose blob actually changes, so if you already
had this repository cloned, switching branches leaves your **existing** working copies of
`artifacts/**` and the fixture pack in their previously-converted form — and the hash
checks then fail locally while passing everywhere else. The line above re-checks-out the
working tree under the new attributes. It changes no committed content, and it is
unnecessary on a fresh `git clone`.

If you skip it and see failures in
`test_published_report_bytes_match_their_own_recorded_hashes`,
`test_verified_full_served_bytes_match_recorded_evidence_hashes` or
`TestFixturePack::test_manifest_hashes_are_real`, that is this and nothing else. Verified:
a true fresh clone of the foundation branch gives 681 passed, 27 skipped with no such step.

| Member | Branch | Task | Independent first checks |
| --- | --- | --- | --- |
| Ahsan | `stage3/ahsan` | `docs/stage3/tasks/task_1_ahsan.md` | Render `tests/fixtures/stage3/expected_analysis_v3.json` and `legacy/genuine_v2_analysis.json`; confirm `comparison: null` renders an explanation and never an improvement figure; exercise `api/status_stale.json`. |
| Rayyan | `stage3/rayyan` | `task_2_rayyan.md` | `pytest tests/test_endpoint.py tests/test_runner.py`; build the CLI against `runs/*/*/run_meta.json`; drive gate exit codes from `gate/*.json`. |
| Khalid | `stage3/khalid` | `task_3_khalid.md` | Reproduce the preserved benchmark from `artifacts/benchmark_v6/`; use `runs/**` as input and `expected_analysis_v3.json` as target; every file in `negative/` must be rejected. |
| Lamei | `stage3/lamei` | `task_4_lamei.md` | `pytest tests/test_attacks.py tests/test_baseline.py`; confirm the payload fingerprint `7fcccf16…a430` still reproduces; build against `attacks.metadata.scoped_registry`. |

Read `CONTRACTS.md`, `docs/stage3/FINAL_PLAN.md` and your task file before writing code.
Do not edit files outside your ownership — request an amendment instead.

---

## 10. What is explicitly not done

This foundation makes the four tasks startable. It implements none of them.

| Outstanding | Owner |
| --- | --- |
| Sentiment endpoint, target-aware runner, gate CLI | Rayyan |
| Analysis v3, coverage, remediation, CI policy | Khalid |
| Coverage map, OCES content and freeze, sentiment baselines | Lamei |
| UI/report v3, API, GitHub gate workflow, deployment, submission PDF | Ahsan |
| Real end-to-end runs; the CI fail/pass/error demonstration; deployed acceptance; repeat-run and resource evidence | Ahsan, with Rayyan |

No application was deployed, no new inference was executed, no OCES case was authored or
run, and no feature work package was started. **No fixture in this foundation is evidence
that any of the above works.**
