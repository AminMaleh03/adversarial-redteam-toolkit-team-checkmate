# Handoff — Team Checkmate

## Current Checkpoint

- Updated: 2026-09-09 13:34 +04:00 (Asia/Dubai), Codex.
- Active request: remediate the six runner review issues, commit, merge PR #5 onto main, push,
  and document for Claude. Ahsan explicitly authorized these actions in this conversation on
  9 September, including this task's exception to Amin's file ownership and agent merging.
  No teammate messages or edits to contract/attacks/endpoint/baseline/analysis/report authorized.
- Branch / observed implementation HEAD: `main` / `39fb79b`, pushed to `origin/main`.
  This final documentation checkpoint follows that merge; use `git log -1` for its own tip.
- Status: all six fixes implemented, verified, committed and pushed. Fix commit `5dea5e7`
  was pushed to `runner-amin`; merge commit `39fb79b` was pushed to main. GitHub API confirmed
  PR #5 is closed with `merged=true`, merge SHA `39fb79b1bc70f5576683ed9f3b52b5cc18b6521a`,
  merged at 2026-09-09 13:33:32 +04:00. The PR branch is retained.
- Committed files: `runner/run.py`, `tests/test_runner.py`, `runner/README.md`, and `HANDOFF.md`.
  Existing Codex/Claude handoff work was reconciled into this checkpoint/history. No contract
  or other components changed. This follow-up checkpoint is documentation-only.
- Next: hand back on main after committing/pushing this final checkpoint. No component work
  remains assigned; Claude should read this file and AGENTS.md before any new task.
- Processes: none remain. Runner test session 43569, full test session 32798 and live smoke
  session 61026 completed; all diagnostic/local endpoint servers shut down.

## Six Fixes and Consumer Notes

1. Prediction HTTP operations use a cancellable total ten-second deadline, including connection,
   upload, response headers and body. A persistent `asyncio.Runner` + `httpx.AsyncClient`
   implements it behind the synchronous Runner interface. Sending stays sequential; no attack
   retries. Client cancellation closes the operation; server-side inference may still continue.
2. Manifest is exported once to a staging directory under the chosen output directory before
   even the health preflight. Only successful preflight publishes `manifest.json` and starts
   replacing results. Failed preflight exits 2 and preserves old manifest/results/metadata.
   It does not publish a new zero-row run. Completed-run replacement remains intentional.
3. CLI and Runner reject prediction timeouts other than the settled ten seconds. Positive,
   finite health timeouts remain configurable and effective settings go into run metadata.
4. Skips are determined from the selected plan before execution, so early death cannot lose
   unreached skip IDs. Limit exclusion takes precedence when an ID is both beyond the limited
   prefix and named in --skip. The planned fingerprint still covers the full built suite.
5. Ctrl+C returns 130 and finalizes started runs with `termination_reason="interrupted"`,
   preserving completed rows and missing IDs. Success is assigned only after execution ends.
   Interrupted preflight also preserves existing artifacts.
6. Negative attack limits are rejected before building the suite or sending requests. Zero
   remains valid and sends all clean baselines with no attacks.

- Added 21 regression cases: CLI lifecycle/settings/coverage plus a real socket drip canceled
  at ten seconds, socket cleanup and a successful subsequent request.
- Public filenames and dataclass fields are unchanged. Async injected transports are now
  required for direct Runner tests; HTTPX MockTransport supports both interfaces.
- Close directly instantiated Runner objects in finally blocks to release client/event loop.
- Durable usage, artifact behavior and exit codes: [runner/README.md](runner/README.md).

## Validation by Codex for These Fixes

Python: root `.venv`, Python 3.11.9. No new dependencies or model downloads.

- `.\.venv\Scripts\python.exe -m pytest tests/test_runner.py -q`:
  **59 passed in 11.28s**.
- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, then
  `.\.venv\Scripts\python.exe -m pytest -q`: **123 passed, 1 warning in 15.57s**.
  Warning is the existing Starlette/AnyIO deprecation. Includes real endpoint/model tests.
- `.\.venv\Scripts\python.exe results/runner_review_e1997d1/live_smoke.py --source . --out results/runner_remediation/live_smoke`:
  **passed**, exit 0. Actual local Uvicorn V1 and V2, real model/tokenizer, --limit 40 and
  --skip malformed.oversized_10mb: 81 rows each (42 clean, 32 standalone, 7 derived).
  Matching full-suite and manifest fingerprints, all result fields/joins checked, no failed
  health, no missing selected cases. 511/512 tokens accepted by both; 513 returned V1 500 /
  V2 422. Extra-field request returned V1 200 / V2 422; invalid UTF-8 returned 400 on both.
- Full-suite planned fingerprint: `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430`.
  Manifest SHA: `0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717`.
- `git diff --check` and staged diff checks: clean before implementation commit. The merge
  introduced no changes relative to the tested PR branch (verified with
  `git diff runner-amin HEAD -- runner tests/test_runner.py contract.py`). No model-test rerun
  needed for this documentation-only follow-up; check its diff before committing.
- Initial root pytest collection hit duplicate modules from the old ignored review snapshot.
  Local ignored `results/conftest.py` now excludes generated artifacts from ordinary discovery;
  no tracked pytest configuration or component tests were bypassed.
- Generated evidence remains ignored: `results/runner_remediation/live_smoke/` has logs, JSONL,
  metadata, manifest and summary; `results/runner_review_e1997d1/` retains the unmodified PR
  archive/snapshot, original review and probes. No full post-fix live benchmark was run.

## Verified Pipeline Snapshot

| Component | Owner | State |
| --- | --- | --- |
| contract.py | Ahsan | Four unchanged dataclasses; frozen |
| endpoint/ | Rayyan | V1/V2 implemented; tests and runner smoke pass |
| baseline/ | Khalid | 42 committed sentences and loader |
| attacks/ | Lamei | Six categories; 1,886 attacks, 33 standalone and 1,853 derived |
| runner/ | Amin | Implemented; six verified fixes merged and pushed to main in PR #5 |
| analysis/ | Khalid | Stubs; downstream file integration unverified |
| report/ | Ahsan | Renderer/template stubs |

Component tests and smoke runs do not establish complete analysis or report generation.

## Short Decision and Review History

- Prior instruction-sync work is committed at `7a06f3d`. CLAUDE.md imports AGENTS.md.
- Codex reviewed original PR #5 on 9 September: 102 existing tests passed (38 runner tests);
  six extra probes failed, reproducing the six issues now fixed. A full 1,928-case simulated
  transport check and real V1/V2 81-row smoke runs passed. Details remain in the ignored
  `results/runner_review_e1997d1/REVIEW.md` (historical review, not current implementation status).
- Claude independently verified the same original snapshot on 9 September: 42 + 1,886 cases,
  the same fingerprints, explicit non-truncation, 102 tests passing in 5.95s, and extra-field /
  100 KB / 1 MB differences via TestClient. These are Claude's historical results; the full
  suite does load the endpoint/model. Amin's claimed full live runs were not independently
  verified because his generated artifacts are not in Git.
- The manifest filename is settled as `manifest.json` by AGENTS.md. The older integration
  notes saying `attack_manifest.json` are a documentation inconsistency, not an open decision.

## Decisions and User Scope to Preserve

Source: Ahsan's local Claude Code conversations from 8–9 September, recovered by Codex and
checked against the repository where possible.

- Runner ownership remains Amin's. The 8 September stop on implementing it was superseded
  only for the six-issue remediation/merge explicitly authorized on 9 September (see checkpoint).
- Khalid handles analysis after Amin's runner work; Ahsan handles the report afterward.
  Do not start those implementations based solely on this handoff.
- Ahsan specifically authorized the baseline loader, its tests/cosmetic cleanup, and V2's
  explicit `truncation=False` fix. Those exceptions are completed, not continuing permission
  to edit Khalid's or Rayyan's components.
- Loader merge: `f4c49f3`; truncation merge: `33e2dcc`. Both exist locally; Claude reported
  pushing them and deleting the feature branches.
- Latest Claude documentation request: update contracts/rules only if needed. No dataclass
  change was needed. Claude saved the manifest rule and corrected scaffold status but hit
  its limit before final verification. These facts now live in the shared files.

## Runner Requirements

Ahsan wrote a ClickUp brief and asked Claude to review it. Preserve its requirements when
maintaining the runner:

- Use the baseline loader; build a deterministic suite, with real-tokenizer counts and explicit
  `truncation=False` for exact boundaries.
- Export `results/manifest.json` after building the suite and before sending any request.
- Send clean baselines, standalone attacks, then derived attacks in stable order.
- Preserve raw bodies/headers, including invalid UTF-8 bytes and valid JSON of the wrong shape.
- Explicit target/version CLI arguments, smoke-run limit and a skip option.
- Record every `RunResult` field, full response body, timing, and health after each request.
  Append and flush results incrementally; separate output by version; stop after failed health.
- Fingerprint the ordered inputs so the V1/V2 comparison can establish matching inputs.

The implementation stores fingerprints in `run_meta_<version>.json`, populates `all_scores`,
and separates planned, selected, completed, skipped, limit-excluded and missing IDs. The full
planned fingerprint stays unchanged by limit/skip flags; analysis must also check coverage.
These are now verified implementation facts, not claims about whether a ClickUp brief was sent.

## Open Questions and Parked Work

- Ahsan's supplied Khalid task now specifies the six unchanged top-level categories, rates with
  explicit eligible denominators, exclusion of unresolved review/diagnostic cases, grouping by
  category/subfamily/failure mode, and maximum supporting-instance severity rather than sums.
  This resolves the original mapping/raw-count concern at the specification level. It is not
  yet implemented or validated; descriptive rates remain dependent on the suite composition.
- Apply the manifest's per-case oracle and validity tier. `REVIEW` and `DIAGNOSTIC` cases must
  not be automatically counted as vulnerabilities; see `attacks/INTEGRATION_NOTES.md`.
  Claude proposed qualified language for `SILVER` cases; report implementation remains pending.
- Measure handwritten baseline confidence in the clean run; do not silently rewrite committed
  baseline sentences to improve scores. Claude raised this as a limitation to assess.
- Permanent endpoint tests for over-length rejection/non-truncation and Unicode cleanup remain
  parked. Claude reported temporary live checks passing; those are historical evidence.
- Documentation inconsistencies to resolve within an authorized task: the older `contract.py`
  comment equating raw mode with invalid JSON; integration notes using
  `attack_manifest.json` instead of the agreed `manifest.json`; README's plain-Python venv
  command. Do not quietly edit other owners' code while resolving documentation.
- Endpoint orphaned docstrings remain a parked cosmetic issue.
- Claude previously verified Python 3.11.9 and GTK/WeasyPrint on Ahsan's machine; Codex has not
  repeated the WeasyPrint import check. Other teammates may lack GTK; follow the shared rules.

## Next Action

Runner remediation and PR #5 merge are complete. Khalid owns analysis and its input-file
integration; Ahsan owns report implementation. Those components remain parked unless the
current user assigns them.

For a takeover, read `AGENTS.md` and this file, inspect Git state, and resume only the latest
user-authorized task. Update this checkpoint whenever progress or scope changes.
