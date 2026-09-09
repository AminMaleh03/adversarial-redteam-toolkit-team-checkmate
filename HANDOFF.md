# Handoff — Team Checkmate

## Current Checkpoint - Codex

- Updated: 2026-09-09T17:54:39+04:00, Codex; branch `khalid/analysis`, observed HEAD `29d0dcc`.
- User authorized fixing the major analysis comparison issue: unevaluable V2 evidence
  must not resolve a V1 finding. Implemented and verified; fix committed at `2ca2473`, pushed in draft PR #6.
- Changed: `analysis/analyze.py`, `analysis/compare.py`, `tests/test_analysis.py`, and
  this handoff. Baseline, frozen contract, and other owners' components unchanged.
- Comparison now intersects metadata completion with actual evidence evaluable for
  each failure mode. Flip resolution requires an eligible clean/attacked pair;
  missing rows, unusable predictions/references, low-confidence references, unscored
  review/diagnostic cases, and connection failures cannot silently prove a fix.
  Clean rejection still resolves an observable server-error finding. Positively
  observed health failures remain reportable even with a connection failure.
- Internal API change: `compare_versions` and `compare_findings` require
  `v2_evaluable_attack_ids_by_mode`; the orchestrator supplies it from VersionAnalysis.
- Added 19 regression cases. Before implementation, the first 17 produced 13 failures
  and 4 passing controls with `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider
  tests/test_analysis.py -q -k ComparisonEvidenceEligibility --tb=line`.
- Final validation by Codex: `.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider
  tests/test_analysis.py tests/test_baseline.py -q`: 158 passed in 0.92s.
  `git diff --check`: clean. No model tests or live endpoints run for this change.
- Repeated `run_analysis_from_dir('results/khalid_validation/full2')` after the fix:
  deterministic; 1,928 completed rows each; comparison remains 15 resolved, 14 remaining,
  0 unavailable, 0 newly appearing. Per-version counts and drift totals unchanged.
- Remaining smaller review concerns are not fixed: mixed-version input, diagnostic
  oracle/tier inconsistency, severity rounding at tier boundaries, comparison rate
  denominators. This task does not establish that the entire area has no issues.
- User authorized committing and publishing the reviewed draft PR on 2026-09-09.
  Fix committed as `2ca2473`; upstream documentation merged as `29d0dcc`, retaining
  both handoff histories. Confirmed analysis/tests/contract unchanged by that merge;
  incoming attack integration notes match origin/main exactly.
- Branch `khalid/analysis` pushed. Draft PR #6 is open against `main`:
  https://github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate/pull/6
  GitHub creation response confirmed open/draft, head khalid/analysis, base main.
  Approved description includes remaining concerns; no direct main push or PR merge.
- Publication used local Git credentials through Git and the GitHub REST API; the
  connector could not access this repository. No credentials written or printed.
- Next: Ahsan reviews draft PR #6. Remaining smaller issues stay disclosed above;
  no additional fixes are in progress. This final documentation checkpoint is being
  committed and pushed to the same feature branch. No processes left running.

## Historical checkpoint - Claude


- Updated: 2026-09-09 (session timezone not specified), Claude.
- Active request: Khalid's analysis subtask. Implement `analysis/drift.py`,
  `analysis/severity.py`, `analysis/compare.py`, `analysis/analyze.py`, and
  `tests/test_analysis.py`, built and unit-tested against synthetic fixtures per the
  ClickUp brief. Real runner output (`results/full_20260909_135157/...`) was described in
  the task text but was **not** present on disk this session (`results/` does not exist
  locally; it is gitignored and was to be sent directly) -- no integration validation
  against real V1/V2 output has happened yet. That remains the next step once the folder
  is actually available.
- Branch: `khalid/analysis`. Two commits made this session: `a068b7d` (the four analysis
  modules + tests + handoff) and `c7c7d71` (corrupt-results-row loader fix). Working tree
  clean. Neither has been pushed; no PR opened yet.
- Status: implementation complete, unit-tested, **and now validated against a real full
  V1/V2 run executed locally** (see "Real-run validation" below). Not pushed, no PR yet.
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
## Real-run validation (Claude, 2026-09-09, this checkout)

Rather than wait for Amin's benchmark folder, we generated a full run locally: uvicorn
V1 on 127.0.0.1:8000 and V2 on 127.0.0.1:8001 (Rayyan's endpoints, run not edited), then
`python -m runner.run` for each version into `results/khalid_validation/full2/`
(gitignored). 1,928/1,928 both versions, coverage 1.0000, `termination_reason: completed`,
~45s per version. **Both servers have since been shut down; no processes left running.**

This is a cross-check, NOT a replacement for the agreed benchmark dataset. The report must
still be written against Amin's `full_20260909_135157/` run, because the team's required
handling references his specific measured values.

Independently reproduced from Amin's reported figures:
- Planned-suite fingerprint `7fcccf16989784ca...` and manifest SHA `0471bccbf293095d...`,
  both identical to his, with 1,886 manifest entries. Recomputed manifest hash matches the
  value stored in run_meta, which also proves the oracles were registered before any
  request was sent.
- The six sub-0.6 baselines match **to four decimal places**: handwritten-neutral-4
  0.4655, handwritten-neutral-0 0.4688, dataset-surprise-0 0.4906, handwritten-disgust-4
  0.5072, handwritten-disgust-2 0.5228, dataset-surprise-5 0.5481. "36 of 42 eligible"
  reproduces exactly.
- Suite composition 21/11/377/973/252/252 across the six categories.
- The 5xx concentration the brief warns about: 84 of the V1 unhandled 500s are exactly two
  truncation subfamilies (`signal_end_over_limit`, `signal_start_over_limit`) at 42
  baselines each. Grouping collapses them to 2 findings, not 84.

Measured outcome on this hardware (V1 -> V2): unhandled 5xx 91 -> 0; observed
unavailability 0 -> 0; connection failures 0 -> 0; flip rate 218/1370 (15.9%) ->
112/1373 (8.2%). Category failure rates: malformed .1905 -> .0476, boundary .0909 -> 0,
perturbation .1194 -> .1194, encoding .1117 -> .0677, whitespace .3238 -> 0,
truncation .5238 -> .0238. Comparison: 15 findings resolved, 14 remaining, 0 newly
appearing, 0 unavailable.

Two findings the team needs, both material:

1. **`malformed.oversized_10mb` is hardware-dependent, and on this machine V2 DID reject
   it.** Amin recorded no response on either version, ~9,993 ms, `latency_band: "timeout"`.
   Here V1 returned **500 at 2,488 ms** and V2 returned **422 at 4,014 ms** — both in the
   `slow` band, neither timed out. This fully explains the only discrepancy in the headline
   numbers: 91 unhandled 500s here vs his 90, the extra one being the 10 MB case that
   500'd instead of timing out. The other 90 match.
   Consequence: the brief's instruction "Do not classify it as a V2 length rejection. V2
   returned nothing; it did not reject" is correct **for his run** but is not a property of
   the system — given more headroom V2's length check is reached and returns 422. The
   analysis code writes no causal explanation either way and needs no change; this is
   reported as new evidence for the team, not a re-derivation of his dataset. It also means
   that case's severity is environment-dependent (timeout 60/High on his run vs
   unhandled_5xx + slow here), so it should not be leaned on as a stable benchmark row.

2. **The honest non-improvement is confirmed empirically.** Perturbation failure rate is
   *identical* on V1 and V2 (45/377, .1194 both), and all 12 perturbation/homoglyph
   prediction-flip findings are "remaining". V2's application-layer defenses do not touch
   model-level typo sensitivity because no retraining was done, exactly as the brief says
   must be preserved rather than quietly omitted. Homoglyph flips persisting also matches
   Lamei's pre-registered `v2_passes_through` expectation (NFKC does not fold mixed-script
   homoglyphs). The 15 resolved findings are all genuine application-layer wins: whitespace
   and fullwidth normalisation, over-limit and oversized 5xx, and `extra_field`.

Bug found by real data and fixed in `c7c7d71`: a truncated JSONL row surfaced as a bare
`JSONDecodeError` naming neither file nor line. `load_results` now raises a `ValueError`
identifying file, line, offending text and likely cause, and still never skips the row.
The corruption itself was an orphaned background runner from a killed session colliding
with a fresh write; a clean re-run into a fresh directory produced 1,928/1,928 valid rows,
so it is **not** a defect in `runner/run.py` and should not be reported to Amin as one.

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
- REAL-RUN VALIDATION DONE (same session). Rather than wait for Amin's folder, we ran the
  suite ourselves: local uvicorn V1 on :8000 and V2 on :8001 (Rayyan's endpoints, executed
  not edited), model already cached, `python -m runner.run` per version into
  `results/khalid_validation/` (gitignored; NOT `results/` root, so Amin's incoming folder
  cannot be clobbered). Both versions: 1,928/1,928, coverage 1.0000,
  `termination_reason: completed`, matching planned fingerprint and manifest hash. V1 took
  44s, V2 50s. Runs were done sequentially, never in parallel, so CPU contention could not
  inflate latency and corrupt the 2s `slow` band that severity depends on.
  Both servers have since been shut down; no stray python processes remain.
  This substantially closes the "validated against real runner output" DoD item. It is our
  run, not Amin's artifacts, so his benchmark folder is still what the report must be
  written against.
- What the real run corroborated:
  - The six sub-0.6 baselines reproduce Amin's reported figures EXACTLY to four decimals:
    handwritten-neutral-4 0.4655, handwritten-neutral-0 0.4688, dataset-surprise-0 0.4906,
    handwritten-disgust-4 0.5072, handwritten-disgust-2 0.5228, dataset-surprise-5 0.5481.
    "36 of 42 baselines eligible" reproduces exactly. Amin's numbers are independently
    confirmed, not taken on trust.
  - 84 of V1's unhandled 500s are exactly two truncation subfamilies at 42 evidence ids
    each (`signal_end_over_limit`, `signal_start_over_limit`), precisely the concentration
    the brief warned would overstate a single defect under an unweighted rate. Grouping
    collapses them to 2 findings, not 84.
  - Health never failed on either version (`service_unavailable: 0` both), as the brief says.
  - Category rates reproduce the brief's stated trap: on V1 encoding has the highest RAW
    failure count (104) but only an 11.17% rate, while truncation is 52.38% and whitespace
    32.38%. Ranking by raw count would have named the wrong worst category.
  - The strongest before/after results: whitespace 32.38% -> 0.00%, truncation 52.38% ->
    2.38%, boundary 9.09% -> 0.00%. V2's NFKC + whitespace cleanup and length limit work.
  - The honest non-improvement is visible and preserved: perturbation is 45/377 = 11.94% on
    BOTH versions, identical, because no retraining was done. Homoglyph and homoglyph_greek
    flips also remain on V2, matching Lamei's `v2_passes_through` expectation.
  - Flip severities landed at 50.5-59.8 (Medium) on real confidences -- approaching but not
    reaching the 60 High boundary, which needs clean confidence of exactly 1.00.
- One genuine difference from Amin's reported run, stated plainly: our V1 returned a 500 on
  `malformed.oversized_10mb` where his timed out. That exactly reconciles the counts --
  ours shows V1 unhandled_5xx 91 / timeouts 0, his shows 90 / 1.
  **Correction to an earlier draft of this note: on our V2 the case did NOT time out.**
  The recorded row is `status_code 422`, `latency_band "slow"`, 4,013.8 ms, no error --
  V2 reached its length check and rejected cleanly. Our V1 row is `status_code 500`,
  `slow`, 2,487.7 ms. Neither version timed out on this hardware. See the
  "Real-run validation" section above for what that implies for the team.
  This case is timing- and machine-sensitive, which reinforces the brief's decision to
  record it as measured and treat its cause as out of scope. It is also why our run cannot
  substitute for his artifacts in the report.
- Next: (1) push `khalid/analysis` and open the PR for Ahsan (three commits: `a068b7d`,
  `c7c7d71`, plus this checkpoint). (2) When Amin's `results/full_20260909_135157/`
  artifacts arrive, run `analysis.analyze.run_analysis(...)` over them -- the report must
  be written against his benchmark run, not ours. Expect his oversized_10mb row to be a
  timeout on both versions, which the code already handles generically.
- Processes: none running. Both local uvicorn endpoints were shut down and ports 8000/8001
  confirmed released.

## Historical upstream checkpoint (origin/main 67034fc)

- Updated: 2026-09-09 13:52 +04:00 (Asia/Dubai), Claude Code.
- Active request: Ahsan authorized, on 2026-09-09, exactly this scope: correct the two
  `attacks/INTEGRATION_NOTES.md` examples (a task-specific exception to Lamei's ownership),
  run the existing full V1/V2 benchmark, validate its artifacts, and update this file.
  Explicitly NOT authorized: implementing analysis/report, changing application code or
  contracts, committing, pushing, or messaging teammates.
- Branch / observed HEAD: `ahsan/integration-notes-fixes` branched from `main` / `88ed695`.
  Both agents' uncommitted `HANDOFF.md` work was carried onto the branch intact, not reverted.
- Status of the documentation edits: **done, uncommitted.** Two lines in
  `attacks/INTEGRATION_NOTES.md` — line 36 now passes `truncation=False` alongside
  `add_special_tokens=True`; line 45 now writes `results/manifest.json`. `git diff --check`
  clean. No other file touched. Note `runner/run.py:52` still carries a now-stale comment
  about the notes saying `attack_manifest.json`; that is Amin's file and was left alone.
- Benchmark environment recorded before starting: implementation commit `88ed695`,
  Python 3.11.9, torch 2.5.1+cpu, transformers 4.46.0, fastapi 0.115.0, httpx 0.27.2,
  uvicorn 0.32.0, pydantic 2.9.2, Windows 10.0.26200. Model
  `j-hartmann/emotion-english-distilroberta-base` resolves `refs/main` to snapshot
  `0e1cd914e3d46199ed785853e12b57304e04178b` (a second cached snapshot,
  `7e9d7fe5...`, is `refs/pr/3017` and is not used). Cached; no download.
- Pre-run process check: no Python processes running, ports 8000 and 8001 free.
- Output root: `results/full_20260909_135157/` with `v1/`, `v2/` and `logs/`. Ignored by Git.
- Benchmark status: **both runs complete and validated.** Details below.
- Processes: none left running. V1 server PID 50516 and V2 server PID 28784 were both stopped
  by the driver; verified afterwards that no Python process remains and ports 8000/8001 are
  free (8000 briefly showed normal TIME_WAIT sockets with no owning process). One earlier
  orphan was cleaned up — see the false start below.
- Next actionable step: Ahsan decides whether to commit/PR the two-line documentation branch
  (not authorized yet), and whether to hand the artifact guide to Khalid (not sent).

### Independent readiness check — 2026-09-09 14:04 +04:00, Codex

- User asked whether Claude completed the work and whether Khalid can begin. Confirmed on
  `ahsan/integration-notes-fixes` / `88ed695`: exactly the two intended integration-note
  examples are corrected; HANDOFF.md and those notes remain uncommitted/unpushed.
- Independently parsed both full-run JSONL files and metadata, checked unique ordered case
  keys against planned/completed IDs, joined attacks to manifests, and hashed each manifest.
  Each version has 1,928 unique rows, 1,886 joined attacks, zero missing/skipped/limit-excluded,
  coverage 1.0, termination completed, matching planned fingerprints/settings/manifests and
  identical executed order. No failed health checks; V1 has 90 HTTP 500s, V2 has none; each
  has one timeout on malformed.oversized_10mb. Six clean baselines per version are below 0.6.
- Evidence: `results/full_20260909_135157/{v1,v2}/` plus runner log tails and local guide.
  `git diff --check` clean. No new benchmark or test run; no source/artifact edits or messages.
- Conclusion: Khalid can start analysis with these artifacts. User must share the full folder
  (including each manifest and metadata file and ARTIFACT_GUIDE.md) outside Git; git pull will
  not supply it. Corrected integration notes are not yet published, so specify manifest.json.
- Qualification for handoff/reporting: the 10 MB case timed out on both clients. The stored
  generic TimeoutError does not establish which server processing stage was reached. Claims
  below/in the guide that transfer/parsing prevented V2's length check are hypotheses, not
  verified measurements; Khalid should not use that causal explanation without more evidence.

### Full V1/V2 benchmark — 2026-09-09 13:54–13:58 +04:00, Claude Code

Commands (servers sequential, no `--reload`, each stopped before the next; no `--limit`,
`--skip` or `--no-tokenizer`; 10 MB case included; stock 10 s request / 2 s health timeouts):

```
.venv\Scripts\python.exe -m uvicorn endpoint.v1:app --host 127.0.0.1 --port 8000
.venv\Scripts\python.exe -m runner.run --target http://127.0.0.1:8000 --version v1 --out "results/full_20260909_135157/v1"
.venv\Scripts\python.exe -m uvicorn endpoint.v2:app --host 127.0.0.1 --port 8001
.venv\Scripts\python.exe -m runner.run --target http://127.0.0.1:8001 --version v2 --out "results/full_20260909_135157/v2"
```

V1 exit 0, 95.7 s. V2 exit 0, 66.4 s. Artifacts in `results/full_20260909_135157/`
(`v1/`, `v2/`, `logs/`, `validation_summary.json`, `ARTIFACT_GUIDE.md`). All gitignored.

**Both runs meet every completion criterion**, checked against the artifacts rather than the
runner's own console claim: planned 1,928, completed 1,928, missing/skipped/limit_excluded all
0, coverage_rate 1.0, `termination_reason: completed`, and 1,928 rows actually on disk per
version. Suite: 42 baselines + 1,886 attacks (33 standalone, 1,853 derived),
`boundary_source: tokenizer`, `max_tokens: 512`.

Comparability confirmed on four independent axes, not fingerprints alone: identical planned
fingerprint `7fcccf16989784ca...`, identical manifest SHA `0471bccbf293095d...` (the two
manifest files are also byte-identical on disk), identical effective settings, and identical
executed case-id sets. Validation found **zero problems**.

Integrity: all rows carry exactly the 14 `RunResult` fields; case keys unique; JSONL order
matches `case_ids.completed`; all 1,886 attack rows join to manifest entries; every 200 row
carries exactly 7 scores; no status-bearing row has an empty body.

Measured outcomes, reported separately — V1 then V2: HTTP 2xx 1,818 / 1,820; 4xx 19 / 107;
**unhandled 5xx 90 / 0**; timeouts 1 / 1; connection errors 0 / 0; failed health 0 / 0; health
ping retries 0 / 0. The service stayed healthy throughout both runs. V1's 90 500s are
truncation 84 (`signal_start_over_limit` 42, `signal_end_over_limit` 42), encoding 3, malformed
2 (`oversized_100kb`, `oversized_1mb`), boundary 1 (`length.plus_one`).

Status transitions across the 1,928 shared cases: 200→200 1,817; **500→422 87**; 422→422 16;
400→400 3; **500→200 3**; 200→422 1 (`malformed.extra_field`); None→None 1.

Three findings worth Ahsan's attention before the report:

1. `malformed.oversized_10mb` **timed out on both versions** (~9,993 ms, `status_code: null`).
   Do not report this as "V2 rejects the 10 MB case" — V2 returned no response at all.
   **Correction, 2026-09-09, Claude Code:** my original wording here and in the artifact guide
   claimed V2's length check was never reached because transfer and parsing consumed the
   deadline. Codex flagged that as unproven and was right; the claim is withdrawn from both
   files. Follow-up log inspection adds one fact — that request is the single `POST /predict`
   with no access-log line on each version (1,927 completed of 1,928 sent), so neither server
   finished a response — but the stored error is a generic client-side `TimeoutError` and does
   not identify the stage reached. The transformers over-length warning is emitted once per
   process, so its absence for this case is not evidence either. Treat the timeout as measured
   and its cause as unresolved; a causal claim needs server-side instrumentation this run did
   not collect.
2. The three `500→200` cases are all `encoding.compatibility_fullwidth.whole`. V2's Unicode
   normalization shrinks the token count back under the limit, so V2 *succeeds* rather than
   rejecting — a different mechanism from the 87 `500→422` cases and worth separating.
3. Baseline quality is now measured, closing a parked question: 6 of 42 baselines predict below
   the 0.6 flip threshold (min 0.4655), and 5 of 42 do not predict their intended label at all.
   Drift is measured against the clean prediction, so comparison stays valid, but flip
   denominators must exclude the six and no accuracy claim should rest on the baselines.

These are measured case-level differences. **Scored, suite-wide robustness rates still require
the analysis component** and the manifest's oracle/validity tiers; nothing here scores them.

**False start, for the record.** The first V1 attempt aborted immediately and orphaned uvicorn
PID 23932. Cause was the driver script, not the endpoint: PowerShell 5.1 wraps native stderr in
a `NativeCommandError`, so the tokenizer's expected over-length warning tripped
`$ErrorActionPreference = "Stop"`. No artifacts had been written and no inputs changed, so
nothing was overwritten to obtain coverage. The orphan was stopped, ports reconfirmed free, and
the driver rewritten to redirect output via `Start-Process` and stop its server in a `finally`
block. Recorded because the run directory's first timestamped attempt produced no `v1/` output.

Prepared but **not sent**: `results/full_20260909_135157/ARTIFACT_GUIDE.md`, a local artifact
guide for Khalid with paths, schema, provenance, coverage, the transition table and the
limitations above. Sending it needs separate authorization.

### Prior checkpoint — 2026-09-09 13:47 +04:00, Codex

- Active request at that time: document the verified pipeline/PR claims and prepare specific
  instructions
  for Claude. The preceding request explicitly deferred implementation of the proposed next
  steps. This turn authorizes the handoff update only, not documentation fixes elsewhere,
  new benchmark runs, downstream implementation, commits, pushes or teammate messages.
- Branch / observed HEAD: `main` / `88ed695f280acbdbb58683f04d8d562f185c0daa`.
  GitHub main was independently checked with `git ls-remote origin refs/heads/main` during
  claim verification and matched. Working tree has only `HANDOFF.md` modified: Claude's
  post-merge check was already uncommitted; this update preserves it and adds qualifications.
- Status: claim verification complete; proposed follow-up remains unexecuted. No new test
  suite or live benchmark was run during claim verification or this documentation turn.
  Only this handoff changed; it is uncommitted and unpushed. Validation: inspect this diff
  and run `git diff --check`; existing test evidence is recorded below.
- Completed prior task: six runner fixes committed/pushed as `5dea5e7`, PR #5 merged/pushed
  as `39fb79b`, final documentation pushed as `88ed695`. GitHub confirmed PR #5 merged at
  2026-09-09 13:33:32 +04:00. Ahsan's ownership/merge exception applied to that completed task;
  it does not authorize the new edits to Lamei's integration notes. PR branch retained.
- Next: user will give Claude the scoped execution brief. On takeover read this file and
  AGENTS.md, reconcile the uncommitted handoff, and act only on the user's new instructions.
- Processes: none started or left running by Codex in these last two turns. Earlier runner
  tests, full tests and smoke sessions completed and their servers were shut down.

### Post-merge independent check — 2026-09-09, Claude Code (read-only)

Confirmed on `main` at `88ed695`, tree clean, `HEAD == origin/main`:
`.\.venv\Scripts\python.exe -m pytest -q` -> **123 passed, 1 warning in 17.16s** (no offline
env vars set; real endpoint/model tests included). `contract.py` is byte-identical to `7a06f3d`.
`truncation=False` survives the async rewrite at all four call sites (`runner/run.py:205`,
`endpoint/model.py:39,63`, `endpoint/v2.py:76`). The merge diff touches only `runner/run.py`,
`tests/test_runner.py`, `runner/README.md` and `HANDOFF.md` — no ownership violations.
`results/conftest.py` sets `collect_ignore_glob = ["*"]` scoped inside ignored `results/`, so it
hides generated snapshots only and bypasses no tracked test.

Gap that matters for planning: **no real full-suite run exists on disk.** Live artifacts are
81-row smoke runs only (`results/runner_remediation/live_smoke/`). The single 1,928-row file is
`results/runner_review_e1997d1/full_mock_tmp/...`, a simulated-transport v1 check, not a real
endpoint run. So the project still has no measured V1-vs-V2 robustness numbers.

### Claim verification and qualifications — 2026-09-09 13:42–13:47 +04:00, Codex

- Verified the contract's raw file and both Git blobs have identical object hash
  `7414e19e122c0fa1e9f52565bfe2ef69903f62a7` using `git hash-object --no-filters contract.py`
  and `git rev-parse HEAD:contract.py 7a06f3d:contract.py`. All four explicit non-truncation
  sites and the four-file merge scope remain as Claude reported.
- Original PR: 38 runner tests, 102 total passes, and no tracked conftest.py. Current code:
  59 runner tests and 123 total passes from prior validation. Codex's own run was 15.57s;
  17.16s is Claude's separately reported duration. No inference tests were repeated for this
  read-only check. `git diff 5dea5e7 HEAD -- runner tests contract.py endpoint` was empty.
- `results/conftest.py` is an ignored, local discovery guard; it excludes no tracked tests.
  The tree was clean before Claude added his checkpoint, but is now dirty in HANDOFF.md only.
- Artifact inventory used `rg --files --hidden --no-ignore` for JSONL/run metadata throughout
  the checkout, then parsed/count-checked rows and inspected metadata and manifest file hashes.
  There are four real 81-row files: V1/V2 under each of
  `results/runner_review_e1997d1/live_smoke/` and `results/runner_remediation/live_smoke/`.
  The only 1,928-row artifact is the simulated V1 run under
  `results/runner_review_e1997d1/full_mock_tmp/test_full_real_suite_cli_contr0/`.
- No complete real V1/V2 pair was found in this checkout. Amin's claimed full runs remain
  unverified, not disproved: results are intentionally ignored by Git. Matching planned
  fingerprint `7fcccf16989784ca...` and manifest SHA `0471bccbf293095d...` are confirmed in
  the smoke files and on-disk manifests, but do not prove full execution.
- Qualification to Claude's preceding paragraph: real case-level measurements DO exist.
  Saved live rows confirm extra_field = V1 200 / V2 422; oversized_100kb and oversized_1mb =
  V1 500 / V2 422, with health true afterward. What is absent is a complete live benchmark
  and scored, suite-wide robustness rates. "Upstream done" means implemented/tested on the
  verified paths, not proven across a full real run.
- Runner ordering, incremental writes and input fingerprinting match the PR description.
  Prediction requests never retry. Health retries once only for transport errors/timeouts,
  using a fresh client and recording the count. Uvicorn can close connections on unhandled
  exceptions; this does not mean every HTTP 500 must cause the next health request to fail.
  Current failed preflight deliberately preserves old artifacts and publishes no new metadata.
- `analysis/analyze.py`, `compare.py`, `drift.py`, `severity.py` are three-line stubs;
  `report/generate.py` is also a stub. Their input-file integration remains unimplemented.
- Two stale examples in `attacks/INTEGRATION_NOTES.md`: line 45 uses `attack_manifest.json`
  although AGENTS.md:190 already mandates `manifest.json`; line 36's tokenizer.encode example
  omits explicit `truncation=False`. Runtime code is correct. These are proposed documentation
  corrections in Lamei's file, requiring the user's task-specific authorization for Claude.

### Proposed execution brief for Claude — not executed or authorized by this checkpoint

1. When the user assigns this work, obtain the task-specific scope from their message: correct
   only the two integration-note examples, run the existing full V1/V2 benchmark and validate
   its artifacts, and maintain HANDOFF.md. No analysis/report implementation or source changes
   to the runner/endpoint/attacks/contract; report unexpected blockers. Publication and teammate
   messages need separate authorization. Preserve both agents' current uncommitted handoff.
2. On a documentation feature branch, change the export example to
   `library.write_manifest("results/manifest.json")` and add `truncation=False` to the tokenizer
   example while preserving `add_special_tokens=True`. Inspect the diff and `git diff --check`.
3. Use the existing Python 3.11 `.venv`, same implementation/model/tokenizer/settings for both
   versions, no --reload, and run V1 then V2 against actual local Uvicorn endpoints. Check ports
   and existing processes first; record commands/PIDs and stop only servers started for this
   task. Use separate v1/v2 subdirectories under a fresh timestamped results directory so each
   version retains its own manifest.json, JSONL, metadata and logs. Record exact implementation
   commit, interpreter/dependency versions, available model revision/cache identity and timings.
4. Invoke `python -m runner.run` via `.venv` with explicit --target, --version and --out only.
   Do not pass --limit, --skip or --no-tokenizer. Include the 10 MB case. Retain the fixed
   ten-second request deadline and default two-second health deadline. Do not promise runtime
   based on smoke tests. If health fails, preserve the partial run and report it; do not alter
   inputs, increase timeouts or rerun over its evidence just to obtain complete coverage.
5. For each run check actual rows, contract fields, unique ordered case keys and manifest joins
   against planned/selected/completed/missing IDs. At unchanged suite inputs expect 42 baselines
   + 1,886 attacks = 1,928 planned. A complete run must actually have 1,928 recorded cases,
   zero missing/skipped/limit-excluded, coverage 1.0 and termination completed. Non-200 rows are
   observations and do not by themselves make the runner incomplete. Check seven scores on
   successful predictions, raw error bodies, health/timeout/connection/5xx counts separately.
6. Compare full planned fingerprints, both retained manifest hashes, effective settings and
   executed case coverage. Do not treat hashes alone as proof of comparability or missing cases
   as V2 fixes. Preserve and investigate discrepancies; do not fabricate matching metadata.
7. Prepare a local handoff for Khalid with explicit artifact paths, schema examples, provenance,
   coverage and limitations. Identify observed status/health differences without inventing
   vulnerability rates or implementing his analysis. Note that analysis must use the manifest,
   exclude unresolved REVIEW/DIAGNOSTIC cases from automatic vulnerability scoring, and apply
   the agreed clean-confidence >= 0.6 flip rule. Update this checkpoint with exact results and
   any remaining processes; do not commit results or send the package without authorization.

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
