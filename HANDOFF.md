# Handoff — Team Checkmate

## Current Checkpoint

- Updated: 2026-09-09 (session timezone not specified), Claude.
- Active request: Khalid's analysis subtask. Implement `analysis/drift.py`,
  `analysis/severity.py`, `analysis/compare.py`, `analysis/analyze.py`, and
  `tests/test_analysis.py`, built and unit-tested against synthetic fixtures per the
  ClickUp brief. Real runner output (`results/full_20260909_135157/...`) was described in
  the task text but was **not** present on disk this session (`results/` does not exist
  locally; it is gitignored and was to be sent directly) -- no integration validation
  against real V1/V2 output has happened yet. That remains the next step once the folder
  is actually available.
- Branch: `khalid/analysis` (unchanged from session start). No commits made this session;
  changes are on disk, uncommitted, pending user review/commit instruction.
- Status: implementation complete, unit-tested, not yet committed, not yet validated
  against real data, not yet opened as a PR.
- Files written/changed this session: `analysis/drift.py`, `analysis/severity.py`,
  `analysis/compare.py`, `analysis/analyze.py`, `tests/test_analysis.py` (all previously
  stubs/empty). No other files touched; no edits outside `analysis/`/`baseline/`/
  `tests/test_analysis.py` per ownership rules. `contract.py` unchanged.
- Design decisions worth recording (not previously settled in AGENTS.md, made explicit in
  code comments/docstrings too): oracle and validity-tier string constants are duplicated
  as literals in `analysis/drift.py` (not imported from `attacks.metadata`), since analysis
  must never import from `attacks/` and the manifest JSON -- not the Python module -- is
  the real interface. `analysis/analyze.py` imports those constants from `analysis.drift`
  (same-package import, allowed). A result whose `attack_id` has no manifest entry raises
  `ValueError` rather than being silently skipped, matching the fail-loud pattern already
  used in `baseline/load.py`.
- Validation by Claude this session: `.venv` is Python 3.11.9 (already present, not
  created this session). `.venv/Scripts/python.exe -m pytest tests/test_analysis.py -q`:
  **91 passed**. `... tests/test_analysis.py tests/test_baseline.py -q`: **110 passed**.
  `pytest --collect-only -q` across the whole repo: **214 tests collected, no import
  errors** (this also triggers a real model download via `test_endpoint.py`'s module-level
  import, unrelated to analysis; that succeeded too, incidentally, but was not the point of
  running it). The model/endpoint/runner test suites were not otherwise re-run, since no
  code outside `analysis/`/`tests/test_analysis.py` changed this session.
- Follow-up review round (same session, same date): the user pasted external review
  feedback on `severity.py`/`analyze.py`/`compare.py`. One part of that feedback (claims
  of `FM_*` constants, a `score_instance` function, and a live `analysis/oracles.py`) did
  not match this repo -- verified by re-reading the actual files and hashing
  `severity.py`; no such file or names exist here, and this was called out to the user
  rather than silently accepted. The rest of the feedback identified four real, confirmed
  bugs, now fixed:
  1. `analyze.py` leak detection had a bare `"pydantic."` marker in
     `_INTERNAL_NAME_MARKERS`; Pydantic v2's default 422 body includes a public docs URL
     (`errors.pydantic.dev`) containing that substring, so every ordinary type-confusion
     422 would have been misclassified as an information leak. Marker removed; a test
     with a real Pydantic v2 error body (including the `url` field) now asserts no leak.
  2. `compare.py`'s `resolve_finding_group` decided "unavailable" only from V2's
     missing/skipped lists, so an id absent from V2 for any other reason (a runner bug, a
     truncated results file) would silently read as "resolved". Changed to require
     positive proof of completion: it now takes `v2_completed_attack_ids` and marks
     anything not in that set unavailable. `compare_versions` derives that set itself from
     `meta_v2["case_ids"]["completed"]` rather than trusting a caller-supplied
     missing/skipped set. The test that had asserted "resolved" on empty missing/skipped
     sets (correctly flagged as enshrining the bug) was rewritten to require explicit
     completion, plus a new test pins the exact gap (an id in neither list is
     unavailable, not resolved).
  3. `analyze.py`'s `is_connfail` matched on `error.startswith("connection_error")`,
     Amin's exact runner string. This missed his other non-timeout no-response case
     (`transport_error`-prefixed, from the generic `httpx.HTTPError` branch in
     `runner/run.py`), which would have silently fallen through to `bucket="pass"`.
     Changed to a structural check: `status_code is None and latency_band != "timeout"`,
     which is correct for both error kinds regardless of message format. Tests added for
     both prefixes plus arbitrary non-matching error text.
  4. `build_comparison_summary` computed `whole_suite_comparable: false` on a fingerprint
     mismatch but still emitted `findings_resolved`/`remaining`/`newly_appearing` and
     paired category-rate deltas -- reporting the flag next to the claims it was supposed
     to block. Now withholds those fields entirely (returns only fingerprints + coverage
     + a `comparison_withheld_reason`) when the suite isn't comparable. Tests cover both
     the withheld and the normal-emission path.
  Also addressed on request: the six-oracle dispatch in `evaluate_case` was if/elif
  branching; the brief asks for an explicit lookup. Refactored into `ORACLE_HANDLERS`, a
  dict keyed by all six oracle constants, each mapping to a handler function (most are a
  documented no-op since their failure modes are already covered by the cross-cutting
  checks). All 102 tests in `tests/test_analysis.py` pass after the fixes (91 before this
  round + 11 new); full-repo collection is clean at 225 tests (up from 214).
- Runnable-state verification (same session, after the fix round). A throwaway harness in
  the session scratchpad (`dryrun_analysis.py`, outside the repo, nothing written into
  `results/`) built synthetic artifacts using the REAL schemas -- manifest via
  `attacks.library.write_manifest` over the committed 42 baselines, run metadata via
  `runner.run.build_meta` -- then ran `analysis.analyze.run_analysis_from_dir` over
  1,928-row V1 and V2 files. Results:
  - The join reproduces the documented suite composition exactly: malformed 21,
    boundary 11, perturbation 377, encoding 973, whitespace 252, truncation 252. This is
    the strongest available evidence that the `family`/`subfamily`/oracle/tier join
    against Lamei's real manifest schema is correct.
  - Full pipeline runs clean: findings emitted for both versions, coverage passed through
    from run_meta, comparison produced, `python -m analysis.analyze <dir>` works.
  - Output is JSON-serialisable without `default=str`; identical across two full runs
    (findings, summaries and comparison all deterministic).
  - Severity spot-checks against the frozen tables: flip at clean confidence 0.93 -> 56.5
    Medium; stack-trace leak -> 85.0 Critical; health failure -> 100 Critical; 4.2s slow
    response -> 24.4 Low; oversized_10mb timeout -> 60.0 High (size adjustment +0).
  - The oversized_10mb timeout appears once on V1 and once on V2 and is classified as a
    timeout with no cause attributed, matching the brief's required handling.
  - Resolution semantics confirmed against synthetic rows (real schema, not real data):
    a V1 case that changed failure mode on V2 resolved on its own terms and produced a
    separate newly-appearing finding.
  - A `transport_error:` no-response row landed in `unevaluable`, not `pass`, confirming
    the structural connection-failure fix.
  - A realistic Pydantic v2 422 (with the `errors.pydantic.dev` url field) was not
    flagged as a leak, confirming that fix.
  - Architectural rules re-checked: `analysis/` imports only stdlib, `contract`, and
    same-package `analysis.*` -- no `attacks/`, `runner/`, `endpoint/` imports. Files
    touched remain only `analysis/`, `tests/test_analysis.py`, `HANDOFF.md`.
  - 121 tests pass (`tests/test_analysis.py` + `tests/test_baseline.py`); whole-repo
    collection clean at 225; `git diff --check` clean.
- Brief-compliance pass (same session, final round). A line-by-line audit against the
  ClickUp brief found eight required outputs that were computed but never surfaced, or
  missing entirely. All are now implemented and tested:
  1. `drift.baseline_confidence_census()` added, plus `analyze.build_drift_block()`, so
     the reduced baseline denominator ("36 of 42 baselines eligible for flip scoring")
     is emitted next to every flip rate, in both the per-version summary and the
     comparison. This number is NOT derivable downstream: derived-attack counts per
     baseline are not uniform (truncation/boundary cases depend on sentence length), so
     it had to come from analysis.
  2. That same census is the "check the moment the real run lands" deliverable -- it
     reports total baselines, how many cleared 0.6, which fell below (with their
     confidences), and any with no prediction. The threshold stays 0.6; if too few
     clear it the response is to discuss expanding the baseline, never to lower it.
  3. Confidence change is now surfaced (`confidence_change`: per-flip clean/attacked/
     delta plus the mean); previously it lived only on `DriftRecord` and never reached
     the summary, though the brief lists it as required.
  4. `LIMITATION_NOTES` added and emitted unconditionally in both the version summary and
     the comparison, covering the three the brief names: no model-accuracy claim rests on
     baselines that miss their intended label; V2 is application-layer only with no
     retraining, so persistent perturbation findings are honest non-improvements; and a
     failed health check is observed unavailability, not process death.
  5. Per-finding `affected_cases` recorded as reproducibility information, explicitly
     separate from severity, with the finding description stating that the count
     indicates reproducibility and not impact.
  6. `invalid_input_accepted` added to the operational counts, so "error-handling gaps"
     are directly comparable between versions as the brief's compare list requires.
  7. Comparison now carries qualifying-flip counts and eligible-comparison counts (not
     just rates), and lists unmatched evidence (`v1_only`, `v2_only`, `unavailable`)
     rather than only counting it.
  8. `validity_tier_census` added so the report can state how much evidence is GOLD vs
     SILVER, per the brief's instruction to be honest that most of the suite is SILVER.
  Also tightened the service-unavailability wording to "observed service unavailability
  ... not evidence of process death", and the word "crash" appears nowhere in emitted
  finding text. A test asserts all three.
  Verification after this round: 134 tests pass (`tests/test_analysis.py` +
  `tests/test_baseline.py`), repo-wide collection clean at 238, dry run still green with
  the suite composition still reproducing 21/11/377/973/252/252, output still
  deterministic and JSON-serialisable, `git diff --check` clean, `analysis/` still imports
  nothing from `attacks/`.
- Next: (1) get the real `results/full_20260909_135157/` artifacts onto disk and run
  `analysis.analyze.run_analysis(...)` against them for integration validation, per the
  brief's required handling of the three specific known issues (oversized_10mb timeout,
  six low-confidence baselines excluded from flip scoring only, five mispredicted
  baselines noted as a limitation) -- the implementation is written generically and should
  already satisfy all three without special-casing, but this is unverified against real
  data. (2) Once validated, commit and open Khalid's analysis PR for Ahsan per the
  Definition of Done. Do not commit before the user asks.
- Processes: none running.

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
| analysis/ | Khalid | Implemented + unit-tested against synthetic fixtures; real-data integration unverified |
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

- Ahsan's supplied Khalid task specifies the six unchanged top-level categories, rates with
  explicit eligible denominators, exclusion of unresolved review/diagnostic cases, grouping by
  category/subfamily/failure mode, and maximum supporting-instance severity rather than sums.
  This is now implemented in `analysis/` and unit-tested against synthetic fixtures (91 tests
  passing); not yet validated against a real run. See Current Checkpoint above.
- Apply the manifest's per-case oracle and validity tier. `REVIEW` and `DIAGNOSTIC` cases must
  not be automatically counted as vulnerabilities; see `attacks/INTEGRATION_NOTES.md`. Now
  implemented as an explicit lookup in `analysis/analyze.py::evaluate_case`, covering all six
  oracle values; `SILVER`/`GOLD`/`REVIEW`/`DIAGNOSTIC` tiers are preserved per finding in
  `finding_meta`. Report-side rendering of qualified `SILVER` language remains Ahsan's.
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
