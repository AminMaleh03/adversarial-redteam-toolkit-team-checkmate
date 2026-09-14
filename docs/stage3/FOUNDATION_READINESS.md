# Stage 3 foundation readiness report

Prepared 2026-09-15 by Claude Opus 5 in Ahsan's checkout.

## Status: NOT_READY

The evidence, identity and CI-freeze layers of the foundation are complete and verified.
The **contract, task-distribution and branch-publication layers are blocked on a missing
input**, and publishing member branches now would hand four people a foundation built on
guesses.

### Commit-reference strategy (avoids self-reference)

This document cannot contain its own commit SHA. The **tested foundation** is referenced
by tag:

| Reference | Meaning |
| --- | --- |
| tag `stage3-foundation-evidence` | The exact tree every verification below was run against. |
| branch `stage3/foundation` | Where work continues. |

The commit that adds *this document* is a **documentation commit made after** the tested
tree, and nothing in this report was re-run against it. When the foundation is completed
and re-verified, a new tag must be cut and this table updated; do not treat a
documentation commit as a tested foundation.

---

## The blocker, stated exactly

**The "Final reviewed implementation plan" and the Task 1–4 descriptions were not
supplied.** The task states they are in the pack and instructs that they be stored
verbatim as `docs/stage3/FINAL_PLAN.md` and
`docs/stage3/tasks/task_1_ahsan.md` … `task_4_*.md`. Neither the conversation nor the
repository contains that text. Searched and confirmed absent: the full working tree, all
branches, `HANDOFF.md` (including the uncommitted Codex edit), `AGENTS.md`, `CLAUDE.md`
and `.claude/`.

What that specifically blocks, and why each cannot be inferred:

| Blocked item | The missing specifics |
| --- | --- |
| `docs/stage3/FINAL_PLAN.md` | It *is* the plan text. Nothing to derive it from. |
| `docs/stage3/tasks/task_1..4_*.md` | "The exact task descriptions." Writing my own would make four people build to my invention. |
| `CONTRACTS.md` 3.0.0 | The task requires "exact function signatures and CLI flags from the final plan" for features that do not exist yet. Inventing an API four people then implement against is the single most expensive thing to get wrong here. |
| `RunResult` additions | The four field names are given (`target_id`, `suite_id`, `request_body_bytes`, `request_body_sha256`), but "the backward-compatible defaults in the final plan" are not. `None` is the obvious guess; a guess written into a frozen contract is not a contract. |
| `endpoint/targets.json` evaluations | The five evaluations and their targets/suites are given. The `baseline_file` overrides are "the two OCES seed files named in the final plan" — those filenames are not stated, and a placeholder path in an active registry is exactly what the task forbids. |
| `tests/fixtures/stage3` | Expected v3 analysis outputs, `GateOutcome`/`CheckResult` shapes and coverage declarations all have to match the contract above. Fixtures asserting an invented schema are worse than no fixtures. |
| Publishing the four member branches | They must come from one complete foundation commit. Publishing an incomplete one and re-cutting later defeats the purpose. |

**To unblock:** supply the final plan text and the four task descriptions. Everything
below is unaffected by them and stands as-is.

---

## What is complete and verified

### Base

| Item | Value |
| --- | --- |
| Validated release identified | branch `ahsan/v5-redlab`, commit `a17fc5b3d06f1a069ebfa0b85a95f14fe01d344e`, tag `v6.0.0` |
| Why not `main` | `main` is at `c507033`, four releases behind. `a17fc5b` is the tagged, deployed V6 release. |
| Remote | `origin` → `github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate` (plus a `space` remote for the HF Space) |
| Working method | A separate worktree at `C:/Users/ahsan/OneDrive/Desktop/stage3-foundation` on new branch `stage3/foundation`, created from `a17fc5b`. |
| Pre-existing work preserved | The uncommitted `HANDOFF.md` edit (Codex's reference-document audit) is untouched in the main checkout. No reset, no stash, no discard. Branches `main`, `ahsan/report`, `ahsan/v5-redlab`, `runner-amin` untouched. Nothing pushed. |
| Environment | Python 3.11.9 in `.venv`; Windows 11; `core.autocrlf=true` |

### Model, tokenizer and dataset identity — all real, no placeholders

Full detail in [`MODEL_IDENTITY.md`](MODEL_IDENTITY.md).

| | Repo ID | Revision (40 hex) | Labels | Limit |
| --- | --- | --- | --- | --- |
| Emotion (existing) | `j-hartmann/emotion-english-distilroberta-base` | `0e1cd914e3d46199ed785853e12b57304e04178b` | 7 emotion labels | 512 |
| Sentiment (new) | `distilbert/distilbert-base-uncased-finetuned-sst-2-english` | `714eb0fa89d2f80546fda750413ed43d93601a13` | `NEGATIVE` / `POSITIVE` (uppercase) | 512 |
| Dataset | `stanfordnlp/sst2` | `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb` | validation split, 872 rows, `idx`/`sentence`/`label` | — |

The emotion pin was verified against the real cache (`refs/main` → `0e1cd914…`). No
model weights were downloaded or loaded for any of this; only metadata and tokenizer
assets. Runtime acceptance requirements that remain are listed in `MODEL_IDENTITY.md`.

### Original benchmark evidence — preserved and reproduced

`artifacts/benchmark_v6/`, with [`PROVENANCE.md`](../../artifacts/benchmark_v6/PROVENANCE.md).

- **Source identified and proven:** `results/repro_1/report/analysis.json` is
  byte-identical to `artifacts/verified_full_report/analysis.json`
  (`12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`), which is also
  that report's own recorded `source_sha256`.
- **Payload fingerprint re-derived from source:** rebuilding the suite at this base
  reproduces the run's `planned_suite_sha256`
  `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430` and the full
  ordered 1928-entry `case_ids.planned` list.
- **Manifest re-derived from source:** `0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717`,
  equal to the recorded hash and to the preserved file.
- **Numerical reproduction:** re-running `analysis.run_analysis` over the *preserved*
  bytes reproduces `schema_version`, `summary_v1`, `summary_v2` and `comparison`
  identically to the published analysis — from a clean clone, not just in place.
- Nine files preserved byte-exact; no field added to any original manifest or run
  metadata; the published report untouched.
- Known limitations recorded rather than smoothed over — chiefly that **the benchmark run
  recorded no model revision** (the pin was added afterward) and that the run has **no
  sender-recorded request-byte evidence**, so findings needing it are *unavailable*, not
  absent.
- Legacy target mapping recorded explicitly (`v1`→`emotion_v1`, `v2`→`emotion_v2`),
  scoped to this directory only.
- OCES freeze point recorded: `endpoint/v2.py`, blob `b71787e3bf39e4062f883c9e34fae78d5b7c6263`,
  SHA-256 `cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e`,
  byte-identical at `c507033`, `bba3a7b` and `a17fc5b`. No OCES case was authored or run
  here.

### Frozen CI input

`analysis/case_sets/ci_core_v1.json` + `analysis/policy_reference/ci_core_v1_clean_reference.json`,
documented in [`analysis/case_sets/README.md`](../../analysis/case_sets/README.md).

- `case_set_id` `ci_core_v1`, `suite_id` `core`, frozen from the real source suite.
- 42 baselines + 32 standalone + 88 derived = **162 cases**, as ordered ID lists.
- Sole exclusion `malformed.oversized_10mb`, with rationale.
- Derived coverage = the first two sorted baseline IDs, `dataset-anger-0` and
  `dataset-anger-1` (sorted order is the runner's own: it sorts baselines by ID before
  building and fingerprinting).
- Clean reference: real top labels for all 42 baselines from the verified `emotion_v2`
  rows, labelled a regression reference and explicitly **not** ground truth.
- No manifest/coverage hash that cannot exist yet. The resolution procedure is written
  down and a draft policy **must error**, never pass.

### A real pre-existing bug found and fixed

`tests/test_web.py::test_verified_full_served_bytes_match_recorded_evidence_hashes`
**fails on any fresh Windows clone of `v6.0.0`**. `artifacts/verified_full_report/analysis.json`
checks out CRLF-converted (`8a950cad…`) instead of the `12d47b35…` recorded in its own
`export_meta.json`, so the deployed web app would serve bytes that fail their own
integrity check. It passed only in Ahsan's working copy, where the report generator had
written the file directly and it was never checked out.

Confirmed by cloning the unmodified `a17fc5b` and running that test in isolation. Fixed
by a `.gitattributes` scoped to `artifacts/**` only. The published bytes are unchanged;
only the checkout conversion is pinned. Project-wide text rules are untouched.

---

## Verification commands and actual outcomes

All run against the tree tagged `stage3-foundation-evidence`, on Windows, with
`.venv` (Python 3.11.9).

| Check | Command | Result |
| --- | --- | --- |
| Full existing suite, in the worktree | `python -m pytest -q` | **580 passed, 27 skipped, 1 warning** (after the `.gitattributes` fix; before it, 579 passed / 1 failed — the pre-existing bug above) |
| Full existing suite, from a clean clone | `git clone --no-local --branch stage3/foundation …` then `python -m pytest -q` | **580 passed, 27 skipped** |
| Whitespace / conflict markers | `git diff --check --cached` | clean |
| Evidence byte-exactness after fresh clone | SHA-256 of all 9 preserved files | all 9 match |
| `verified_full_report` integrity after fresh clone | hashes vs its own `export_meta.json` | `report.html`, `analysis.json`, `report.pdf` all match; `source_sha256` matches |
| Benchmark reproduction from clean clone | `analysis.run_analysis` over `artifacts/benchmark_v6/run/*` | `schema_version`, `summary_v1`, `summary_v2`, `comparison` all identical to published |
| Suite fingerprint from source | rebuild + `runner.run.fingerprint_suite` | `7fcccf16…a430` — matches |
| Manifest from source | `attacks.library.write_manifest` | `0471bccb…a717` — matches |
| Case-set integrity | counts vs list lengths, duplicate check, exclusion check, reference coverage, derived-ID ownership | all pass |
| Identity resolution | `HfApi.model_info` / `dataset_info`, `scan_cache_dir` | all resolved to real values |

**Meaningful skips:** the 27 skips are pre-existing on this base (browser/UI tests
needing Playwright, and WeasyPrint-dependent paths). They are unrelated to this work.
The historical "607 tests passed" figure was **not** used as evidence for anything here.

No endpoint was deployed, no new inference was executed, and no OCES case was authored
or run.

---

## Changed files

Tested tree (tag `stage3-foundation-evidence`), two commits on `stage3/foundation`:

```
.gitattributes                                        (new)
analysis/case_sets/README.md                          (new)
analysis/case_sets/ci_core_v1.json                    (new)
analysis/policy_reference/ci_core_v1_clean_reference.json  (new)
artifacts/benchmark_v6/PROVENANCE.md                  (new)
artifacts/benchmark_v6/analysis/analysis.json         (new, byte-exact copy)
artifacts/benchmark_v6/analysis/export_meta.json      (new, byte-exact copy)
artifacts/benchmark_v6/run/demo_evidence.json         (new, byte-exact copy)
artifacts/benchmark_v6/run/manifest.json              (new, byte-exact copy)
artifacts/benchmark_v6/run/results_v1.jsonl           (new, byte-exact copy)
artifacts/benchmark_v6/run/results_v2.jsonl           (new, byte-exact copy)
artifacts/benchmark_v6/run/run_meta_v1.json           (new, byte-exact copy)
artifacts/benchmark_v6/run/run_meta_v2.json           (new, byte-exact copy)
artifacts/benchmark_v6/source/baseline.json           (new, byte-exact copy)
```

Documentation commit (after the tested tree): `docs/stage3/MODEL_IDENTITY.md`,
`docs/stage3/FOUNDATION_READINESS.md`.

**No existing file was modified.** `contract.py`, `endpoint/`, `baseline/`, `attacks/`,
`runner/`, `report/`, `web/`, `run_all.py`, `AGENTS.md`, `CLAUDE.md` and `HANDOFF.md` are
all untouched on this branch.

---

## Not done, and why

| Step | State |
| --- | --- |
| `FINAL_PLAN.md`, `tasks/task_1..5` | Blocked — source text not supplied. |
| `OWNERSHIP.md`, `DECISIONS.md` | Deferred with the plan: both must agree with it. |
| `AGENTS.md` / `CLAUDE.md` pointers | Deferred — they are meant to point at the final contract and tasks, which do not exist yet. |
| `CONTRACTS.md` 3.0.0 | Blocked — needs the plan's signatures, flags and field defaults. |
| `RunResult` new fields, shared structural types | Blocked on defaults and on the single agreed import path. |
| `endpoint/targets.py` + `targets.json` | Blocked on the two OCES `baseline_file` names. |
| `attacks.metadata.scoped_registry` | Not blocked; not yet written. A working precedent exists at `web/lab.py:190` (`_isolated_attack_registry`) and should be generalised there, with nested-context and exception-restoration tests. |
| `tests/fixtures/stage3` | Blocked on the v3/GateOutcome schemas. |
| Publishing `stage3/integration` and the four member branches | Deliberately not done. They must all come from one complete, tested foundation commit. Nothing has been pushed. |

**Nothing here proves final functionality.** The fixtures do not exist yet, and when they
do they will demonstrate schema agreement, not working features. The UI, report,
deployment work and the separate five-page submission all remain outstanding, as does
every one of the four feature work packages.
