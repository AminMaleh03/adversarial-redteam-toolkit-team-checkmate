## System V5.4 FINAL INTEGRATION - sequential-run bug fix + native Back navigation - Claude

- Updated: 2026-09-10T15:35:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `4e0057a` at session start (the V5.4 commit below, local-only, not pushed anywhere). This
  session's changes are folded into that same commit via `git commit --amend` once verified
  (explicit instruction: nothing pushed, so amend rather than a separate bugfix commit; do
  not amend V5.3 `6716107`, V5.2 `5eb8735`, or V5.1 `6b0bc9c`; confirmed `ahsan/v5-redlab` has
  no remote tracking branch/upstream before amending).
- Ahsan's real-browser manual testing of V5.4 found the custom Lab and Live Demo each work
  individually, but exposed a genuine release blocker plus two navigation gaps to close.

### CRITICAL: sequential Custom-Lab-then-Demo failure -- root cause found by reproduction, not guessed

- Reproduced first, exactly as instructed, **before** touching any code: a standalone script
  called the real `web.lab.run_custom_lab()` (genuine V1/V2 subprocesses, no mocks) followed
  immediately by the real `run_all.run_experiment(mode="demo", ...)`, in the same Python
  process, with no artificial delay. This reliably reproduced the reported failure on the
  first try: the demo's V1 and V2 both attacked successfully (162/1928 cases each, matching
  normal demo coverage), but the run then failed with
  ```
  ValueError: v1: planned attack IDs disagree with manifest
  ```
  raised from `analysis/validation.py:125` inside `validate_run()`, called from
  `run_analysis_and_report()` at the "analyzing" stage -- i.e. **after** both endpoints had
  already been attacked and torn down, not during V1/V2 process/port lifecycle at all. This
  explains Ahsan's observed symptom ("failure occurs around Testing the hardened endpoint"):
  that was simply the last stage message visible before the crash, not the actual point of
  failure.
- **The real mechanism** (confirmed by reading `attacks/metadata.py` and
  `analysis/validation.py:123-125` directly, then verifying with the reproduction above):
  `attacks.metadata._MANIFEST` / `_FINGERPRINTS` are plain **module-level dicts** that persist
  for the entire life of the long-running uvicorn web process (unlike the CLI, `python
  run_all.py`, which starts a fresh process every time and never hit this). `analysis
  /validation.py`'s `validate_run()` asserts an **exact set-equality** between a run's planned
  attack ids and the manifest's current keys:
  ```python
  planned_attacks = {key[7:] for key in sets["planned"] if key.startswith("attack:")}
  if planned_attacks != set(manifest):
      raise ValueError(f"{version}: planned attack IDs disagree with manifest")
  ```
  Before this session's fix, `web/lab.py`'s `select_lab_variants()` called
  `attacks.library.build_derived(baseline)` on an **ephemeral, unique-per-job baseline**
  (`baseline_id=f"lab.{job_id}"`), which permanently registered that job's ~9-44 unique
  attack ids into the same global `_MANIFEST` and never removed them. Since every Lab job
  uses a fresh `job_id`, these entries never match a demo/full run's own planned set and never
  get cleaned up on their own -- so after even **one** Lab job had ever run in the process,
  **every** Demo/Full run attempted afterward (regardless of how much later, or how many
  demo/full runs had already succeeded before that first Lab job) would fail at its analysis
  stage. This was a real, previously-undiscovered defect in the V5.4 feature itself, not a
  latent bug in `run_all.py`/`analysis/`/`attacks/` -- those modules' behavior is exactly as
  designed for a fresh-process CLI invocation; V5.4 was the first thing to ever call into
  `attacks.metadata` repeatedly across multiple logically-distinct "experiments" within one
  long-lived process.
- **Hypotheses explicitly investigated and ruled out by evidence** (per the brief's
  instruction not to select a cause without evidence): stale V2 process still alive, port 8001
  not released, process handle reuse, a cleanup race, the shared lock releasing before
  endpoint teardown finishes, and stale readiness/health state. None of these are the cause --
  `run_all.run_experiment()`'s per-version loop already calls `EndpointHandle.stop()`
  synchronously in a `finally` block **before** moving to the next version or returning (this
  was true before this session and needed no change), and a new
  `test_run_custom_lab_stops_each_endpoint_before_starting_the_next` regression test now
  pins that ordering explicitly. The failure reproduced with zero relationship to V1/V2
  process state: the demo's V1 and V2 both fully succeeded (real predictions, real coverage
  numbers) before the crash.
- **Fix** (`web/lab.py`, new `_isolated_attack_registry()` context manager wrapping
  `select_lab_variants()`'s call to `build_derived()`): snapshot
  `attacks.metadata._MANIFEST`/`_FINGERPRINTS` immediately before building a Lab job's
  variants, and restore them to that exact snapshot in a `finally` block immediately after --
  so a Lab job's registration is fully transient/invisible to the rest of the process, exactly
  matching the "ephemeral, never persisted" design already established for every other part
  of the Lab feature. **Deliberately does not touch `attacks/metadata.py`** (Lamei's folder,
  per `AGENTS.md`'s file-ownership rule) -- the fix lives entirely in `web/lab.py`, which only
  reads and temporarily mutates that module's already-existing module-level dicts from the
  caller's side, then puts them back exactly as found. Verified this is safe under the
  existing `JOB_LOCK`: only one experiment (Lab or Demo) is ever actually in progress
  process-wide, so there is no concurrent registration this could race with.
- **Reverse direction** (Demo/Full run's registrations, then a Lab job): was never actually
  broken -- Lab's own baseline ids are always unique per job and never collide with
  `baseline.json`'s fixed dataset ids, so `select_lab_variants()` already worked fine
  afterward. Confirmed by reproduction and by a new regression test
  (`test_full_suite_then_custom_lab_selection_still_works`) that runs lighter-weight than the
  forward-direction one, per the brief.
- **Regression tests added** (`tests/test_lab.py`): `test_custom_lab_registration_leaves_no_
  trace_in_global_manifest` (fast, pure, asserts the manifest is byte-for-byte unchanged
  after a Lab job); `test_custom_then_full_suite_manifest_still_matches_exactly` (reproduces
  the exact `planned_attacks == set(manifest)` invariant `analysis/validation.py` checks on
  every real run, using the real `attacks.library`/`attacks.metadata`/`run_all.build_full_
  suite` -- no network needed, since attack generation touches none); `test_full_suite_then_
  custom_lab_selection_still_works` (reverse direction); `test_run_custom_lab_stops_each_
  endpoint_before_starting_the_next` (lifecycle-ordering guard, mocked); `test_job_marked_
  complete_only_after_run_custom_lab_returns` (confirms the shared lock's "available again"
  state genuinely waits for the job function to return, not any earlier point).
- **Real sequential acceptance (not mocked)**, following the established project pattern that
  real end-to-end verification is a manual/local step each session, never a slow test added
  to the committed pytest suite (confirmed by inspecting `tests/test_run_all.py`, which mocks
  every V1/V2 interaction -- there is no precedent for a real-network test in this repo's
  suite): started `uvicorn web.app:app` on `127.0.0.1:7860` as a harness-tracked background
  task. Ran, with no artificial wait between steps: **A.** `GET /` 200. **B/C.** `POST
  /api/lab/run` with real text, polled to `complete` (real V1/V2, ~10s). **E/F.** `GET /` 200,
  then **immediately** `POST /api/run` (the exact previously-failing sequence). **G/H/I.**
  polled `/api/status` through `attacking_v1` -> `starting_v2` -> `attacking_v2` ->
  `generating_results` -> **`complete`** -- the demo run that previously failed here now
  succeeds completely, full report generated. **J.** fetched the real `result_url` (Demo
  Results page), 200. Then started a **third** job (another real custom Lab test)
  immediately after the demo completed, confirming the full **CUSTOM -> DEMO -> CUSTOM**
  lifecycle: also completed successfully with real, varied results (9 variants, 1 flip on V1
  neutralized to 0 flips on V2 for the `whitespace.interior_runs` case -- a genuine
  `MITIGATED_BY_V2` diagnosis with TV distance 0.0 on V2 vs 0.83 on V1). After the full
  sequence: `netstat` showed no `LISTENING` socket on 8000/8001; no orphan V1/V2 subprocess
  remained (`Get-CimInstance Win32_Process`); exactly one new `results/` directory existed
  (the one real demo run, cleaned up afterward); `GET /api/status` and `GET /api/lab/status
  /<id>` both correctly reported `"complete"` with no job stuck "running"; verified artifact
  hashes re-checked identical to the values recorded before this session.

### Sticky "Test Another Input" (Lab Results masthead)

- Moved from a single button at the bottom of the results page into the Lab masthead's nav
  cluster (`web/templates/lab.html`: `<button id="nav-test-another" class="button ghost
  nav-action" hidden>`), which is `position: sticky` (inherited from the existing `.masthead`
  rule -- no new sticky mechanism). `web/static/lab.js`'s `showInput()`/`showExecution()`/
  `showResults()`/`showFailure()`/`showBusy()` now each explicitly set
  `navTestAnother.hidden`, so it's visible **only** while viewing `#view-lab-results`, per the
  brief's "not overcrowded" instruction.
- The old bottom `<button id="lab-again-btn">` and its surrounding `.cta-row` were **removed
  entirely** -- one reset implementation (`resetToInput()`, extracted from the old handler
  body unchanged) is now called by exactly one control. `resetToInput()` still does the same
  four things as before: clears `sessionStorage`'s job token (`clearJobId()`), clears local
  result/text state, resets the textarea, and returns to `#view-lab-input` -- it has no
  access to demo state or verified artifacts at all, so it cannot touch either.
- The mobile hamburger-menu-close wiring (previously `primaryNav.querySelectorAll("a")`) was
  widened to `"a, button"` so the new `<button>` nav item also closes the mobile drawer on
  click, matching every `<a>` nav item's existing behavior.

### Native-style "&larr; Back" on every non-Home surface

- One shared behavior, defined identically (not "slightly different" per the brief's
  instruction) in three places, each wired the way that surface already wires its JS: `web
  /static/app.js` (`goBack()`, for the Demo execution view), `web/static/lab.js` (`goBack()`,
  for `/lab`'s masthead, covering all three Lab sub-views since they share one masthead), and
  a global `rlGoBack(event)` inside `report/template.html`'s/`report/demo_template.html`'s
  existing (`template.html`) or newly-CSP-permitted (`demo_template.html`, which previously
  had no `script-src` at all -- added `script-src 'unsafe-inline'`, mirroring the exact
  change V5.3 made to `template.html`) inline `<script>`, wired via `onclick="return
  rlGoBack(event)"` on the report pages since they have no other JS-wiring convention to
  match. Logic everywhere: if `window.history.length > 1` **and** `document.referrer` is
  same-origin, `event.preventDefault()` + `window.history.back()`; otherwise, the control's
  own `href="/"` navigates normally (also the correct, safe fallback with JavaScript
  disabled, and for a page opened directly or via a `target="_blank"` link, where
  `history.length` stays 1).
- **Placement, audited against every surface** (Home is the only one that must not show it):
  - `/lab` (input/execution/results, one shared masthead): `<a id="nav-back">&larr; Back</a>`
    added as the first `<nav>` item, before the existing "Back to Red Lab" -- both now appear,
    with distinct hrefs/semantics, per the brief's section 15.
  - Demo execution (`web/templates/index.html`'s `#view-execution`, the same URL as Home,
    `/`): since Home and Execution share one masthead/page, adding Back there would have
    meant conditionally changing the masthead's content between the two states -- risking
    exactly the kind of masthead inconsistency V5.4's first session just fixed. Instead,
    `<a id="exec-back" class="exec-back">&larr; Back</a>` lives inside `#view-execution`
    itself (top of `.execution-inner`, above the identity line), visible in both the running
    and failure sub-states, and the shared masthead stays byte-identical between Home and
    Execution.
  - Demo Results (`report/demo_template.html`): added as the first `<nav>` item, before the
    existing "Back to Red Lab".
  - Technical Report (`report/template.html`): added as the first `.downloads` item, before
    the existing "Back to Red Lab".
  - Home (`#view-home`): unchanged, no Back control anywhere in it -- confirmed by a new test
    scoped strictly to the `#view-home` HTML slice.
- **Back during active execution** (brief section 14): no cancel/abort call exists anywhere in
  this codebase for either Demo or Lab jobs (confirmed again this session, source-level), so
  clicking Back can never terminate a running experiment -- navigating away (or falling back
  to `/`) just stops that tab's own polling; the server-side job runs to completion regardless,
  and the existing load-time reattachment logic (unchanged) brings a visitor straight back
  into the live execution view if they return while it's still running.

### Tests

- New: 20 (10 in `tests/test_web.py`/`tests/test_lab.py`/`tests/test_report.py` combined for
  Back-navigation placement, the shared `goBack`/`rlGoBack` source pattern, CSP on the now-
  scripted demo report, and the sticky-action/removed-duplicate/reset-reuse/sessionStorage-
  clearing checks for "Test Another Input"; the 5 sequential-lifecycle regression tests
  described above). One pre-existing test needed a wording-only fix in this session's own new
  code, not the test itself: `test_app_js_has_no_cancel_handler` (a real, still-valid guard --
  no cancel feature was ever added) initially flagged a code **comment** in `app.js` that
  happened to contain the substring "cancels"; reworded the comment, the guard stays exactly
  as strict as before. Full suite:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **564 passed** (544 at session start + 20 new), 1 pre-existing Starlette/AnyIO warning.

### Verified benchmark isolation

- `analysis.json` SHA-256 `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`
  and `report.pdf` SHA-256
  `0853108d4939bab1ff2069a1e3dc42b8ad68b14096d12cfd1bfa81fbb56718ca` -- unchanged, re-checked
  after the full local sequential acceptance run and again after the containerized one. No
  re-render of `report.html` was needed this session (no template/generate.py change touches
  the verified artifact's rendering inputs this time). Full 1,928-case benchmark was not
  rerun.

### Docker

- Rebuilt `team-checkmate-v5-redlab:latest` from the unmodified `Dockerfile`. All four
  expensive layers (`apt-get`, `COPY requirements.txt .`, `pip install`, the pinned-model
  pre-download) reported `CACHED`; only `COPY . .` and the final `useradd`/`chown` step
  re-ran. Ran the freshly built image; confirmed `/healthz`, `/`, `/lab` all 200. Performed
  the **critical CUSTOM -> DEMO sequence inside the container**: a real Lab job completed,
  then a real Demo run started immediately afterward and completed successfully through
  `attacking_v1` -> `starting_v2` -> `attacking_v2` -> `complete` (the exact sequence that
  fails without this session's fix). Confirmed inside the container afterward: no `uvicorn`
  process for V1/V2 remained (`ps aux`); no `LISTEN`-state socket on port 8000 (state `06`
  TIME_WAIT entries only, confirmed by reading `/proc/net/tcp`'s state column directly, not
  just filtering by port); `/app/results` contained exactly the one expected demo run
  directory; `/app/artifacts/verified_full_report/{analysis.json,report.pdf}` SHA-256 hashes
  identical to the values recorded before this session. Container removed afterward. Did not
  run the full 1,928-case suite.

### Files changed this session

- **Modified**: `web/lab.py` (the `_isolated_attack_registry()` fix, `contextlib` import,
  `resetToInput`-equivalent reset logic unchanged), `web/templates/lab.html` (masthead Back +
  sticky Test Another Input, bottom duplicate button removed), `web/static/lab.js` (`goBack()`,
  `resetToInput()`, view-state toggling for the new nav button, widened mobile-menu-close
  selector), `web/templates/index.html` (`#exec-back` link inside the execution view),
  `web/static/app.js` (`goBack()`, wired to `#exec-back`; one comment reworded to avoid a
  false-positive "cancel" match), `web/static/app.css` (`.exec-back`, `.nav-action` styling
  only -- no color/layout-system change), `report/template.html` (`rlGoBack()` added to its
  existing single `<script>`, `&larr; Back` added first in `.downloads`), `report/demo_
  template.html` (CSP gained `script-src 'unsafe-inline'`, a new inline `<script>` defining
  `rlGoBack()`, `&larr; Back` added first in the masthead `<nav>`), `tests/test_web.py`,
  `tests/test_lab.py`, `tests/test_report.py`. **No changes** to `contract.py`, `endpoint/`,
  `runner/`, `analysis/`, `baseline/`, `attacks/` (confirmed -- the fix deliberately stays out
  of Lamei's folder), `run_all.py`, `report/generate.py`, `report/audit.html`,
  `report/style.css`, `web/app.py`, `web/templates/lab.html`'s underlying data/attack
  semantics, or any verified artifact file.
- **Not done / explicitly out of scope**: the V5.5 broader visual redesign (colors, cards,
  animation, artistic direction -- none of it touched), the full 1,928-case benchmark rerun,
  any push to GitHub `origin` or the `space` Hugging Face remote, any merge to `main`. `v4.0.0`
  /`bba3a7b`, the V5.1 commit `6b0bc9c`, the V5.2 commit `5eb8735`, and the V5.3 commit
  `6716107` are all untouched.
- **Manual visual review -- not performed by this session**: no browser display in this
  environment. The sticky masthead action's visual fit on desktop/mobile, the "&larr; Back"
  link's placement/spacing next to "Back to Red Lab" everywhere it now appears, and the demo
  execution view's new top-of-content Back link have all been verified structurally/via
  source and functionally via real HTTP/API sequences, not screenshot-checked. Ahsan should
  manually re-verify in a real browser: the Custom -> Demo -> Custom sequence from a real
  click-through (not just curl); the sticky Test Another Input staying visible while scrolling
  a long results page; that "&larr; Back" and "Back to Red Lab" read as two distinct, sensible
  actions rather than a confusing duplicate, on `/lab`, Demo Results, and the Technical
  Report; and that clicking Back mid-execution behaves sensibly (reattaches rather than
  looking broken).
- Next: Ahsan performs the manual visual/browser recheck above, then decides whether to
  proceed to V5.5 (final UI direction, integration/security review, responsive polish), V5.6
  (Hugging Face deployment/public visibility), or push `ahsan/v5-redlab`.

## System V5.4 - Live Red-Team Lab (Try Your Own Input) + navbar unification - Claude

- Updated: 2026-09-10T14:40:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `6716107` at session start (the closed V5.3 commit, local-only, not pushed anywhere). This
  session's changes are a **new** commit after V5.3, per explicit instruction not to amend
  `6716107` (V5.3), `5eb8735` (V5.2), or `6b0bc9c` (V5.1).
- Scope: (1) fix the masthead/navbar inconsistency across Home, Live Demo Results and
  Technical Report that V5.3 intentionally carried forward; (2) add "Try Your Own Input" -- a
  dedicated `/lab` page where a judge types a sentence and Red Lab derives a curated set of
  adversarial variants using the *existing* attack library, runs them against V1 and V2, and
  shows a deterministic mitigated/persists/regression/no-effect/inconclusive diagnosis. No
  `contract.py` change (frozen, unneeded), no `run_all.py` change (its
  `start_endpoint`/`EndpointHandle.stop()` primitives were already generic enough to reuse
  as-is), no change to the verified 1,928-case benchmark's underlying data, no full suite
  rerun, no push, no Hugging Face deploy, no broader visual redesign.

### Navbar unification (Part 1)

- Root cause established before touching anything (three parallel Explore-agent passes plus
  direct reads of `web/static/app.css`, `report/style.css`, and all three masthead templates):
  `web/static/app.css` and `report/style.css` are two fully independent stylesheets, hand-kept
  in sync only for the base color palette. Masthead height (`76px` vs `84px`), content width
  (`1100px` token vs hardcoded `1320px`), padding (`14px 24px` vs `25px 48px`), brand markup
  shape (`brand-text/brand-creator/brand-product` two-part vs a single-block `.brand` plus
  `brand-lines/brand-name/brand-version`), logo size (`44px` vs `30px`), nav-link typography
  (`13px/700` vs `12px/600`), and the brand-vs-nav right-alignment technique
  (`.brand{margin-right:auto}` vs `.masthead nav{margin-left:auto}`) all diverged.
- Unified via **new masthead-only tokens**, deliberately separate from `--rl-content-width`
  (which other layout still uses) so unifying the top bar could not silently change hero/body
  widths: `--rl-nav-height: 84px` (canonical value, adopted from the report side),
  `--rl-masthead-width: 1160px`, `--rl-masthead-pad-x: 32px`, `--rl-masthead-pad-y: 16px` --
  added identically to both `:root` blocks. `report/style.css`'s existing
  `--report-nav-height` is now an alias (`--report-nav-height: var(--rl-nav-height)`), so
  `report/template.html`'s inline scrollspy script (`getComputedStyle(...).getPropertyValue
  ("--report-nav-height")`) keeps working unchanged -- confirmed by the existing scrollspy
  tests still passing.
- Alignment technique standardized on `margin-left: auto` on the nav/action cluster (the
  report's existing technique) in both stylesheets; `.brand`'s `margin-right: auto` was
  removed from `web/static/app.css`.
- Brand markup unified: both report templates now render `{{ creator_name }}` (the same
  `CREATOR_NAME` constant `web/app.py` already imports from `report/generate.py`, i.e.
  `"Team Checkmate"`) inside `.brand-creator`/`.brand-product` spans under a `.brand-text`
  wrapper -- the exact same class names and two-part typography (10px/700/uppercase over
  14px/800) `web/templates/index.html`'s masthead already used, replacing the report-only
  `brand-lines`/`brand-name`/`brand-version` names and the literal hardcoded `"TEAM CHECKMATE"`
  string. Visually still reads as "TEAM CHECKMATE" everywhere via `.brand-creator`'s
  `text-transform: uppercase` -- confirmed by a new test
  (`test_reports_masthead_brand_shows_version_label`, updated to check for `creator_name`'s
  actual title-case value plus the CSS class, not a hardcoded uppercase literal) and by the
  re-rendered verified artifact.
- Logo size unified to `36px` (midpoint of the app's 44px and the report's 30px) with a shared
  `border-radius: var(--rl-radius-sm)` (the report previously hardcoded `6px`; `--rl-radius-sm`
  was added to `report/style.css`'s token block to match). Nav-link typography unified to
  13px/700/0.3px-letter-spacing/2px-bottom-border everywhere.
- Deliberately **not** changed: `.report-shell`'s own `1320px` max-width, `main`'s `1160px`,
  the report's mobile `order:`-based wrap strategy vs the app's hamburger-dropdown (two
  different, already-working responsive mechanisms -- brief required visual/typographic
  consistency, not identical DOM/JS mechanics), the report's print stylesheet structure (only
  its brand-related literal values were updated to match the renamed classes).
- Nav *content* on the two report pages was already correct per the brief's examples (`Back to
  Red Lab, Demo, Results, Method, Source JSON, View Detailed Report` /
  `Back to Red Lab, Source JSON, Download PDF`) -- no link changes needed there, only the
  shared stylesheet/markup edits above (one `report/style.css` edit fixes both pages at once,
  since `report/generate.py` inlines the same file into both).

### Home page (Part 2)

- `web/templates/index.html`: masthead nav gained `<a href="/lab" id="nav-try-lab">Try Your
  Own Input</a>` between Live Demo and Technical Report. Hero `.cta-row` gained a secondary
  `Try Your Own Input` button (`.button.secondary`) between `Run Live Demo` (primary) and
  `View Technical Report` (now `.button.ghost`, kept easily accessible as the supporting
  evidence path per the brief's hierarchy) -- no textarea/form on the homepage itself.

### Live Red-Team Lab architecture (Parts 3-5)

- **New module `web/lab.py`** -- owns everything Lab-specific: job state, curated attack
  selection, ephemeral experiment execution, metrics, diagnosis. Deliberately does **not**
  touch `run_all.py`; it imports and reuses `run_all.start_endpoint(version, out_dir) ->
  EndpointHandle` / `EndpointHandle.stop()` directly, which were already generic enough (no
  refactor needed, per the brief's "do not rewrite run_all.py wholesale").
- **API routes** (added to `web/app.py`, which stays a thin deployment layer delegating to
  `web/lab.py`): `GET /lab` (renders `web/templates/lab.html`), `POST /api/lab/run` (body
  `{"text": str}` only -- rejects non-dict/non-string/empty/whitespace-only/oversized with
  422; never accepts JSON, attack ids, URLs, file paths, or commands), `GET
  /api/lab/status/{job_id}`.
- **Ephemeral job model**: a fresh `BaselineCase(baseline_id=f"lab.{job_id}", ...)` is built
  in memory per submission (`build_lab_baseline`) -- required because
  `attacks.metadata.register()` raises on an `attack_id` collision with different content, and
  attack ids are derived from `baseline_id`. `send_case()` talks to the running V1/V2 process
  directly via `runner.run.Runner(target=url, version=version, writer=None)` -- reusing
  `Runner.send()`, `Runner.health_ok()`, and the module-level `parse_prediction()` (all
  pure/stateless with respect to disk) -- and builds a `contract.RunResult` manually, entirely
  bypassing `Runner._record`'s file-writing `ResultWriter` path. Nothing is ever written to
  `results/` or `artifacts/verified_full_report/`; confirmed structurally (new tests
  `test_custom_lab_run_never_writes_under_results_or_verified_artifacts`) and against the real
  filesystem during the local and containerized acceptance runs below. The only files a run
  touches are the two uvicorn boot logs `start_endpoint` already writes, into a
  `tempfile.mkdtemp()` directory (never `results/`), removed as soon as each endpoint stops.
- **Shared global job lock (concurrency, brief sections 8-9)**: `web/lab.py` defines
  `JOB_LOCK = threading.Lock()`; `web/app.py` now does `_job_lock = lab_module.JOB_LOCK`
  instead of constructing its own `Lock()` -- the **only** change made to existing demo logic,
  and it's lock-object identity only, so every pre-existing demo route/test is untouched and
  still passes unmodified. `POST /api/run` (demo) now also checks
  `lab_module.is_running_unlocked()` (a lock-free read of Lab's own state, safe because it's
  only ever called from inside a block that already holds the same lock object) and returns a
  distinct `{"status": "busy"}` at 409 if a Lab job is active, kept separate from demo's
  pre-existing "reattach to my own running job" 202 branch so that branch's behavior/tests are
  byte-for-byte unchanged. `web/lab.py`'s own `start_lab_job(text, demo_is_running)` takes a
  callable bound to `web/app.py`'s own `_job_state` check and invokes it *inside* the same
  `with JOB_LOCK:` block that also guards Lab's own state -- demo-vs-lab exclusion is therefore
  fully atomic (one lock, one critical section), not a best-effort check-then-act. Verified
  live against the real server (not just mocked): starting a real Lab job, then hitting both
  `POST /api/lab/run` and `POST /api/run` while it was active, returned `{"status":"busy"}`/409
  from both, with no leaked job id or text in either response.
- **Per-job security (brief section 8)**: `job_id = secrets.token_urlsafe(24)` (cryptographic,
  never sequential). `GET /api/lab/status/{job_id}` returns the real state only if the id
  matches the single current job exactly; any other id (wrong, stale, or simply made up) gets
  a generic `{"status": "not_found"}` 404 -- never a hint that a different job exists or what
  it contains. A stale progress callback from a superseded job (re-checked by `job_id` on every
  write) can never clobber a newer job's state.
- **sessionStorage reattachment (brief section 10)**: `web/static/lab.js` stores only the
  opaque `job_id` via `sessionStorage.setItem` (never `localStorage` -- confirmed by a source-
  level test that the served script contains no `localStorage.setItem`/`.getItem` call at
  all). On load, if a stored id exists, it's used to re-poll `/api/lab/status/{id}`; a 404 (bad
  token, expired, or server restarted since) clears storage and returns to the input form.
- **Curated attack selection (`CUSTOM_LAB_ATTACKS`, brief section 13)** -- one authoritative,
  documented constant in `web/lab.py`, matched against **real** `attacks.metadata
  .metadata_for(attack_id)` fields (`family`, `subfamily`, `dose`, `position`) after calling
  the real `attacks.library.build_derived(baseline)`, never guessed from the attack_id string
  or invented:
  | family | subfamily | match | friendly label |
  |---|---|---|---|
  | encoding | homoglyph | dose=3, middle | Cyrillic homoglyph substitution |
  | encoding | homoglyph_greek | dose=3, middle | Greek homoglyph substitution |
  | encoding | invisible_zero_width | middle | Invisible Unicode insertion |
  | perturbation | keyboard_typo | -- | Keyboard-adjacent typo |
  | perturbation | word_split | -- | Word-split perturbation |
  | perturbation | swap_adjacent | -- | Adjacent-letter swap |
  | whitespace | interior_runs | -- | Whitespace distortion |
  | whitespace | unicode_spaces | -- | Unicode space substitution |
  | truncation | signal_head_only | -- | Sentence truncation (head only) |

  9 variants for a normal-length sentence (confirmed live: the acceptance-test sentence
  yielded all 9); `signal_head_only` needs >=4 words and a couple of the encoding matches need
  a few eligible characters, so a very short input (e.g. 3 words) can yield as few as ~7 --
  still within the brief's "approximately 6-10." Every entry is genuinely derived from
  arbitrary text, `is_raw=False`, and excludes everything resource-heavy or non-text-driven:
  the 100KB/1MB/10MB oversized payloads, the deep-JSON-nesting ladder, all `type_confusion.*`
  and other `malformed.*` raw/malformed-body cases (hardcoded bodies, not derivable from
  arbitrary text at all), and the two over-limit truncation cases (large filler-padded text
  built specifically to probe the length boundary) are all excluded -- confirmed by a test
  asserting no `CUSTOM_LAB_ATTACKS` entry's family is `malformed`/`boundary` and no subfamily
  contains `type_confusion`/`oversized`/`deeply_nested`/`over_limit`.
- **Metrics** (`web/lab.py`, genuinely new -- confirmed via research that no
  distribution-distance code existed anywhere in the repo before this): `total_variation_distance
  (p, q) = 0.5 * sum(abs(p_i - q_i))` over the union of both label sets, range 0-1, `None` if
  either distribution is missing; `label_flipped` = exact top-label inequality, no confidence
  gate (the Lab is exploratory, not the verified benchmark -- deliberately not reusing
  `analysis/drift.py`'s 0.6-confidence-gated flip rule, per the brief's explicit instruction
  not to silently reuse benchmark thresholds where they aren't semantically appropriate);
  `confidence_change` returns `{clean, attacked, delta}`.
- **Diagnosis** (`web/lab.py:diagnose`, deterministic, rule-based, never an LLM): per endpoint,
  `_adverse(clean, attacked)` is `True` if the attacked response 5xx'd or failed to connect,
  or if the label flipped relative to that *same endpoint's own* clean reference; `None` if the
  clean reference itself wasn't a usable 200; otherwise `False`. Then: both `None` ->
  `INCONCLUSIVE`; V1 adverse and V2 not -> `MITIGATED_BY_V2`; both adverse ->
  `PERSISTS_AFTER_HARDENING`; V1 not adverse but V2 is -> `V2_REGRESSION`; neither ->
  `NO_MATERIAL_EFFECT`. TV distance is computed and shown per variant but never gates the
  diagnosis (brief section 18: it's a displayed continuous measurement, not a trigger). Every
  branch has a dedicated fixture-based test in `tests/test_lab.py`.
- **Remediation mapping** -- flat `dict[str, str]` in `web/lab.py` (`REMEDIATION`), using the
  brief's exact section-19 wording for `MITIGATED_BY_V2`/`PERSISTS_AFTER_HARDENING`/
  `V2_REGRESSION`, plus two short additional entries for `NO_MATERIAL_EFFECT`/`INCONCLUSIVE`.
- **Diff highlighting** reuses `run_all.highlight_diff_html()` unchanged (its `html.escape`
  based escaping is unconditionally safe for arbitrary input) -- only its docstring was updated
  to note it's now also called with judge-supplied text, not just our own generated attack
  text. The server embeds the two pre-escaped `<mark class="demo-mark">`-wrapped strings under
  explicitly-named JSON fields (`diff_original_html`/`diff_attacked_html`); `web/static/lab.js`
  is the *only* place in the whole feature that ever sets `.innerHTML`, and only for those two
  named fields (verified by a source-level regex test) -- every other user-influenced string
  (attack labels, error text, the original input itself) goes through `.textContent`/`el()`
  helper functions, never raw HTML.
- **Frontend** (`web/templates/lab.html`, `web/static/lab.js`, a delimited "Live Red-Team Lab"
  CSS section appended to `web/static/app.css`): three mutually-exclusive views
  (`#view-lab-input`/`#view-lab-execution`/`#view-lab-results`) using the same `hidden`-
  attribute + `[hidden]{display:none!important}` mechanism `index.html`/`app.css` already
  established, reusing the `.execution-view`/`.progress-bar`/`.stage-list`/`.version-card`
  visual language. `LAB_STAGE_ORDER` = preparing -> starting_v1 -> clean_v1 -> attacking_v1 ->
  starting_v2 -> clean_v2 -> attacking_v2 -> analyzing -> complete, driven entirely by real
  backend stage callbacks (no fake timer). `web/static/lab.js` is a separate file from
  `app.js` (which is untouched) with its own small duplicated mobile-nav-toggle handler (same
  markup ids, ~10 lines) since `lab.html` doesn't load `app.js`. Accessibility: labelled
  textarea with `aria-describedby` tying in a live char counter and a `role="alert"` error
  region, `aria-live="polite"` execution heading, `role="progressbar"` with real
  `aria-valuenow`/`aria-valuetext`, diagnosis shown as a text-labelled badge (never color
  alone), expandable probability/diff detail via native `<details>`/`<summary>`.

### Tests

- New `tests/test_lab.py` (34 tests): route/form checks; server-side empty/whitespace/oversized/
  non-string/missing-field rejection (422); a source-level regex test that `lab.js` only ever
  sets `.innerHTML` for the two trusted diff fields and never touches `localStorage`; job-id
  format/uniqueness; status scoping (wrong id -> 404, never leaks another job's text); shared-
  lock busy behavior in both directions (lab-vs-lab, lab-vs-demo, demo-vs-lab) plus a regression
  guard that plain demo-vs-demo reattachment is unaffected by the lock-aliasing change;
  deterministic/safe/genuinely-text-derived attack selection; TV-distance formula/range/
  identity/missing-data; one fixture per diagnosis rule; a real (mocked-network) run through
  `run_custom_lab()` checking real summary counts and zero TV distance for identical
  distributions; and two tests confirming a run never writes under `results/`/verified
  artifacts and that its temp directories are removed.
- `tests/test_web.py`: replaced the old guardrail test (`test_home_page_has_no_v54_custom
  _input_ui`, which asserted "Try Your Own Input" was *absent*) with
  `test_home_page_links_to_v54_live_red_team_lab` (asserts presence + `href="/lab"` + still no
  inline `<textarea>`); `test_home_navigation_has_required_links` updated for the 4th nav link;
  added `test_static_css_masthead_tokens_match_report_stylesheet`.
- `tests/test_report.py`: `test_reports_masthead_brand_shows_version_label` updated (checks
  `creator_name`'s real value + the CSS class, not a hardcoded uppercase literal); added
  `test_reports_masthead_brand_uses_shared_class_names_with_web_app` and
  `test_report_style_css_masthead_tokens_match_web_app`.
- Full suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **544 passed** (507 at session start + 37 new), 1 pre-existing Starlette/AnyIO warning.

### Verified artifact re-render (same pattern as V5.1-V5.3, not a new benchmark)

- `analysis.json` SHA-256 recorded before touching anything:
  `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`. Since this session's
  `report/template.html`/`report/demo_template.html` markup changed (brand class renames),
  `artifacts/verified_full_report/report.html` was re-rendered via
  `report.generate.render_html(mode="full")` against that same, byte-unchanged `analysis.json`
  -- only `export_meta.json`'s `report.html` hash entry was updated to match. Re-checked
  **after**: `analysis.json` and `report.pdf` hashes both byte-identical to before
  (`12d47b35...` and `0853108d4939bab1ff2069a1e3dc42b8ad68b14096d12cfd1bfa81fbb56718ca`
  respectively) -- confirmed again, a third time, after the full local + containerized
  acceptance testing below, still unchanged. The re-rendered `report.html` contains exactly one
  `class="brand-text"` and zero occurrences of the old `brand-lines`/`brand-name`/`brand-version`
  class names.

### Real local acceptance test (not mocked)

- Started `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uvicorn web.app:app` on `127.0.0.1:7860`
  (as a harness-tracked background task, after an earlier attempt accidentally left a stale
  pre-fix server process running on the same port across separate shell invocations --
  caught and corrected before drawing any conclusions from it; see the temp-cleanup note
  below for what that stale-process detour actually revealed). Confirmed `GET /`, `GET /lab`,
  `GET /healthz` all 200 against the real served bytes.
- Ran **three** real end-to-end custom Lab tests via `POST /api/lab/run` against real V1/V2
  uvicorn subprocesses (not mocked), including the brief's suggested sample sentence
  ("I feel calm and happy about finishing this project."): each moved through real stage
  transitions (`starting_v1` -> ... -> `complete`, ~6-11s total per run), returned real
  label/confidence/all_scores for both clean references, real per-variant TV distances (e.g.
  the whitespace/zero-width variants showed **TV distance exactly 0.0 on V2 but nonzero on
  V1** for the calm/happy sentence -- V2's whitespace-collapse and normalization genuinely
  neutralizing those perturbations end-to-end, a real demonstration of the feature's purpose),
  and a real, varied diagnosis distribution on a different (negative-sentiment) sentence: 9
  variants tested, 3 V1 flips, 2 V2 flips, 1 mitigated-by-V2, 2 persisting, 6 no-material-
  effect -- not a degenerate all-one-value result.
- Confirmed via `GET /api/lab/status/{job_id}` with a deliberately wrong id: 404
  `{"status":"not_found"}`, no data leaked.
- **Live concurrency check** (not just the mocked pytest version): started one real Lab job,
  then while it was active, `POST /api/lab/run` (a second, different sentence) and `POST
  /api/run` (demo) both returned `{"status":"busy"}` at HTTP 409, with no job id or either
  sentence's text present in either response body.
- **Temp-directory cleanup -- a real bug found and fixed this session**: the first two "real"
  acceptance attempts appeared to leave `redlab_lab_v1_*`/`redlab_lab_v2_*` directories behind
  in the OS temp folder after completion. Root-caused with an isolated repro script
  (`start_endpoint` + immediate `stop()` + `shutil.rmtree` with the error surfaced instead of
  swallowed): Windows raised `PermissionError [WinError 32] ... being used by another process`
  on the log file for a few seconds even after the subprocess had fully exited and
  `EndpointHandle.stop()` (which explicitly closes the log handle) had returned -- most likely
  real-time antivirus scanning the freshly-written log file, with the lock duration varying
  with system load. Fixed in `web/lab.py` (`_cleanup_temp_dir`/`_try_rmtree`/
  `_cleanup_temp_dir_background`): a few quick inline retries cover the common (no-lock) case
  at effectively zero cost; if still locked, the remaining retries continue in a background
  daemon thread so a slow OS-level lock never adds latency to the judge-facing job. These log
  files never contain user text (confirmed by inspecting their contents -- plain uvicorn
  request/health log lines only), so a delayed cleanup was always a tidiness issue, never a
  privacy one, but "removed immediately" per the brief is still honored in the common case and
  closely approximated (typically within seconds) under load. **Separately**, the *apparent*
  continued failure after this fix was itself traced to a second, unrelated mistake: `kill
  %1`/`%2` job-control references do not persist across separate Bash tool invocations in this
  harness (each is a fresh shell), so earlier "restart the server" steps had failed to kill
  the previous process, and curl requests were silently still hitting the stale, pre-fix
  server the whole time. Caught via `Get-CimInstance Win32_Process`, both stray processes
  force-killed by PID, and the acceptance test re-run cleanly afterward (confirmed via a
  harness-tracked background task instead of an ad-hoc `&`) with immediate, successful
  cleanup on every subsequent run. `tests/test_lab.py`'s own cleanup test uses a `FakeHandle`
  with no real subprocess/lock, so it was unaffected either way and continued passing
  throughout.
- Confirmed via `netstat -ano` and `Get-CimInstance Win32_Process`: no `LISTENING` socket on
  8000/8001 and no stray python/uvicorn processes after every run in this session, including
  the concurrency check's in-flight job once it finished. Confirmed via directory listing that
  `results/` gained no new entries from any Lab run (only the pre-existing historical demo run
  directories already in that folder from earlier sessions/this session's own unrelated demo-
  route testing). Verified artifact hashes re-checked unchanged after all of the above (see
  above). Stopped the web app process afterward via the harness's task-stop mechanism.

### Docker

- Rebuilt `team-checkmate-v5-redlab:latest` from the unmodified `Dockerfile`. All four
  expensive layers (`apt-get`, `COPY requirements.txt .`, `pip install`, the pinned-model
  pre-download) reported `CACHED`; only `COPY . .` and the final `useradd`/`chown` step
  re-ran. Ran the freshly built image on host port 7861; confirmed over real HTTP: `/healthz`
  200, `/` 200, `/lab` 200, `/verified-full/report.html` 200.
- Ran **one real containerized custom-Lab test** end to end (`POST /api/lab/run` -> polled to
  `complete`). Confirmed inside the container: no lingering uvicorn process (`ps aux`), no
  listening socket on 8000/8001 (`/proc/net/tcp`), `/app/results` completely empty (zero
  entries), and `/app/artifacts/verified_full_report/{analysis.json,report.pdf}` SHA-256
  hashes identical to the values recorded before this session started. Container removed
  afterward. Did not run the full 1,928-case suite.

### Files changed this session

- **Added**: `web/lab.py`, `web/templates/lab.html`, `web/static/lab.js`, `tests/test_lab.py`.
- **Modified**: `web/app.py` (shared `JOB_LOCK` alias, `/lab` route, `/api/lab/run` +
  `/api/lab/status/{job_id}` routes, a distinct lab-active busy branch on `/api/run`),
  `web/templates/index.html` (nav link + hero CTA), `web/static/app.css` (masthead token
  unification + new Lab-specific CSS section), `report/style.css` (masthead token/brand-class
  unification, mirrored from `web/static/app.css`), `report/template.html` and
  `report/demo_template.html` (brand markup class rename only), `run_all.py`
  (`highlight_diff_html`'s docstring only -- no behavior change), `tests/test_web.py`,
  `tests/test_report.py`, `artifacts/verified_full_report/report.html` + `export_meta.json`
  (re-rendered view only, evidence untouched). **No changes** to `contract.py`, `endpoint/`,
  `runner/`, `analysis/`, `baseline/`, `attacks/`, `report/generate.py`, `report/audit.html`,
  `web/static/app.js` (demo execution JS untouched), or the `Dockerfile`.
- **Not done / explicitly out of scope**: the full 1,928-case benchmark rerun, any push to
  GitHub `origin` or the `space` Hugging Face remote, any merge to `main`, and the later,
  separately-briefed broader Red Lab visual redesign (V5.5). `v4.0.0`/`bba3a7b`, the V5.1
  commit `6b0bc9c`, the V5.2 commit `5eb8735`, and the V5.3 commit `6716107` are all untouched.
- **Manual visual review -- not performed by this session**: no browser display in this
  environment. Everything above (masthead alignment/spacing at a real viewport, the Lab page's
  layout on mobile/tablet, the diagnosis badges' color contrast, the variant cards' responsive
  stacking) is structural/HTTP/API-level verification -- the *functional* correctness was
  confirmed against real V1/V2 endpoints end to end (see above), but the visual presentation
  itself has not been screenshot-checked. Ahsan should manually verify in a real browser:
  masthead consistency across Home/Live Demo Results/Technical Report/Lab at a real viewport;
  the Lab input form, execution progress, and results view (clean cards, variant cards, diff
  highlighting, diagnosis badges) on desktop and mobile; that "Test Another Input" and a page
  refresh mid-run both behave as expected in a real browser tab (not just via curl).
- Next: Ahsan performs the manual visual/browser review above, then decides whether to proceed
  to V5.5 (final integration, security review, responsive acceptance, later visual/UI polish),
  V5.6 (Hugging Face deployment/public visibility), or push `ahsan/v5-redlab`.

## System V5.3 CLOSED - final manual-review fixes - Claude

- Updated: 2026-09-10T07:35:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `497d239` at session start (the V5.3 commit below, local-only, not pushed anywhere). This
  session's changes are folded into that same commit via `git commit --amend` once verified
  (explicit instruction: keep V5.3 as one clean logical commit after V5.2; do not amend
  `5eb8735` (V5.2) or `6b0bc9c` (V5.1); confirmed `ahsan/v5-redlab` still unpushed before
  amending).
- Ahsan's real-browser manual review of V5.3 found several concrete bugs and presentation
  issues to close before V5.3 is done. All were root-caused against the actual rendered
  output before fixing, not patched by guesswork.
- **Demo Results masthead concatenation -- root cause found**: this session's own V5.3 edit
  had deleted `.masthead nav { display: flex; gap: 25px; margin-left: auto; }` from
  `report/style.css` (it looked unused after the Technical Report's masthead dropped its
  `<nav>` element in favor of the sidebar toggle) -- but `report/demo_template.html` still
  uses a `<nav>` with four `<a>` tags written back-to-back with no whitespace between them
  in the source (`</a><a href=...>`, relying entirely on flex `gap` for spacing). Without
  `display: flex`, a `<nav>` defaults to block and its inline `<a>` children render flush
  against each other with zero space -- exactly the "Back to Red LabDemoResultsMethod"
  concatenation Ahsan saw. Restored the rule (plus `flex-wrap: wrap` and a two-value `gap:
  18px 25px` for row/column spacing if it wraps) and the matching mobile override
  (`.masthead nav { order: 3; width: 100%; margin: 0; }`, also accidentally deleted). Both
  were only ever needed by the demo report -- the Technical Report's masthead has no `<nav>`
  element at all since V5.3 started, so this change has zero effect there.
- **Sidebar collapse control moved to a sticky, non-scrolling header**: `<aside id=
  "report-toc">` is now a flex column with two children -- `.toc-sticky-head` (the collapse
  button on desktop, the drawer's title/close bar on mobile; `flex: none`, never scrolls)
  and `#toc-scroll` (`flex: 1 1 auto; min-height: 0; overflow-y: auto`, holding the actual
  `<nav class="toc-nav">`). The outer `<aside>` itself changed from `max-height` +
  `overflow-y: auto` directly on it to a fixed `height: calc(100vh - var(--report-nav-
  height))` with `display: flex; flex-direction: column` -- so the collapse button (desktop)
  and the drawer's close button (mobile) are always visible regardless of how long the TOC
  list is or how far it's been scrolled internally, while the report itself scrolling still
  keeps the whole sidebar pinned via the existing `position: sticky` on the aside. No JS
  changes were needed for this -- `#toc-collapse` and `#toc-close` are still the same IDs,
  only their position in the DOM/layout moved.
- **Evidence & Audit reading order -- actual DOM order inspected, not assumed**: read
  `report/template.html`'s real `{% for s in versions %}` loop in the `#appendix` section
  before touching anything. It emits, per version, the audit `<details>` immediately
  followed by that same version's validity `<details>`, and only then moves to the next
  version -- i.e. the real order is `v1-audit, v1-validity, v2-audit, v2-validity,
  provenance` (confirmed by index-position in a real rendered report, and now pinned by a
  test that independently sorts those five IDs by their actual position and asserts that
  order). The sidebar's Evidence & Audit group previously listed `v1-audit, v2-audit,
  v1-validity, v2-validity` -- reordered to match reading order exactly. Nothing in
  `audit.html` or the underlying data changed.
- **Evidence & Audit scrollspy -- real root cause found, not patched around**: the observer
  callback used to do `entries.forEach(entry => { if (entry.isIntersecting) { ... setActive
  ... } })`, which overwrites the active link for *every* intersecting entry in whatever
  order a single `IntersectionObserver` callback batch happens to deliver them -- not
  necessarily reading order. The five Evidence & Audit targets are collapsed `<details>`
  elements (only their `<summary>` line tall, since none carry the `open` attribute) sitting
  close together, so several of them can legitimately be simultaneously intersecting the
  trigger band at once; whichever one the browser listed last in that batch silently won,
  which does not reliably correspond to the one actually nearest the top of the viewport.
  Rewrote the observer to track a persistent `Map` of `target -> isIntersecting` and, on
  every callback, resolve the active link to the **document-order-last currently-
  intersecting** target -- a standard, robust scrollspy pattern that is correct regardless
  of batch delivery order or how many short targets overlap. Also replaced the old
  viewport-percentage `rootMargin: "-15% 0px -70% 0px"` with a fixed pixel offset read from
  the same `--report-nav-height` custom property the sticky masthead uses
  (`getComputedStyle(...).getPropertyValue("--report-nav-height")`, falling back to 84 if
  unavailable) so the trigger line sits right under the actual top bar instead of an
  arbitrary viewport fraction -- addressing the brief's "sticky-header offset" hypothesis as
  a contributing factor. `targets` are now also sorted by real DOM position
  (`compareDocumentPosition`) rather than trusting sidebar-list order to already match it,
  so this class of bug (sidebar order silently drifting from DOM order, as literally just
  happened above) can't quietly break the scrollspy again. `aria-current="location"` moves
  with the resolved active link exactly as before; nothing about *what* triggers a false
  positive was patched with a hack (no "force the clicked element permanently active").
- **Evidence & Audit anchor quality**: all five targets (`v1-audit`, `v1-validity`,
  `v2-audit`, `v2-validity`, `provenance`) already lived on real, content-bearing, unique
  container elements (the `<details>` themselves and the `.provenance` div) -- no ID needed
  moving to a different element. Added `scroll-margin-top: var(--report-nav-height)`
  directly to `.audit-details` and `.provenance` (belt-and-suspenders alongside the existing
  document-level `scroll-padding-top: 100px`) so anchor-jumping to any of them, including
  via the browser's native `<details>`-reveal behavior, always clears the sticky top bar.
- **Analysis Schema 2 presentation cleaned up**: removed the `<div class="hero-meta">
  <span>Analysis schema 2</span></div>` pill that sat directly in the report's hero next to
  the big title -- exactly the "marketing badge" treatment the brief flagged. The schema
  version is still recorded, once, as plain metadata text in the Evidence Bundle
  (`#provenance`): reworded from "Analysis schema 2 · Report format 1" to "Analysis schema
  v2 · Report format v1" (same change applied to the demo report's equivalent Source
  section). "Red Lab v5.0" (the product version) is unaffected and remains wherever it
  already appeared -- the two concepts were never conflated in code, only in that one
  hero-badge's visual prominence, which is now gone.
- **Remediation architecture confirmed preserved, not altered**: both layers are untouched
  -- each finding card's own `<div class="remediation">` (unchanged, unchanged text) and the
  V5.3-added collected `#remediation` section (still the same deduplicated, verbatim list).
  The collected section's intro paragraph already explained the relationship ("repeated
  verbatim from the finding it supports... collected here for a single reference list") from
  when it was first added, so no further wording change was needed -- verified this session
  with a new test that renders both, from the same finding data, and confirms the
  finding-level block appears before `#remediation` and the exact remediation text appears
  in both places unaltered.
- **No broader visual redesign performed**: the Red Lab red/charcoal/paper/success/warning
  token system, the existing panel/table/finding-card visual language, and the overall V5
  aesthetic direction were not touched beyond the specific fixes above. No new color
  balance, decorative motif, animation, or "more premium" visual direction was introduced or
  inferred. **Broader Red Lab visual polish remains intentionally deferred. Do not infer or
  implement a new visual direction until a future explicit implementation brief defines it.**
- **Tests**: added 11 tests to `tests/test_report.py` -- the demo masthead's `.masthead nav`
  rule has `display: flex` and a `gap`; the Evidence & Audit sidebar order is asserted
  against an independently-computed real DOM order (not hardcoded to "what the sidebar
  already says"); all five Evidence & Audit anchor IDs exist exactly once; both
  `.audit-details` and `.provenance` carry `scroll-margin-top: var(--report-nav-height)`;
  the scrollspy's target set comes from *every* `[data-toc-link]` (not a top-level-only
  subset) and the script contains the persistent-Map/`compareDocumentPosition` fix, with
  `aria-current` wired into the same `setActive` function used for everything else; the
  collapse control sits inside `.toc-sticky-head`, which closes in the DOM before `#toc-
  scroll` opens; `.toc-scroll` alone carries `overflow-y: auto` (the outer `.report-toc`
  does not); mobile drawer markup (`toc-toggle`/`toc-backdrop`/`toc-close`) is intact; no
  V5.4 UI exists; the hero no longer contains "Analysis schema" text at all, while the
  Evidence Bundle contains "Analysis schema v2" and "Red Lab v5.0" (both, correctly, as
  distinct concepts); the remediation architecture test above. Full suite:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **507 passed** (496 at session start + 11 new), 1 pre-existing Starlette/AnyIO warning.
- **Verified full-report re-render** (same pattern as every prior V5.x session, not a new
  benchmark): `analysis.json`'s SHA-256 recorded before rendering and re-checked after --
  byte-identical. Only `report.html` was regenerated and copied into
  `artifacts/verified_full_report/`; `export_meta.json` got only that one hash field
  updated; `report.pdf`'s hash was independently re-checked against `export_meta.json`
  afterward and still matches (never opened for writing). Confirmed on the real updated
  artifact: zero duplicate IDs, sidebar Evidence & Audit order matches real DOM order, no
  `<div class="hero-meta">` element remains, exactly one "Analysis schema v2" occurrence.
- **Real local acceptance test** (not mocked): started `uvicorn web.app:app` on
  `127.0.0.1:7860`; confirmed `/` 200. Verified over real HTTP against the actual served
  bytes: `GET /verified-full/report.html` 200 with `id="toc-collapse"` appearing before
  `id="toc-scroll"` in the document and the sidebar's Evidence & Audit anchors in the
  corrected order; `GET /verified-full/analysis.json` 200 `application/json; charset=utf-8`
  with no `content-disposition`; `GET /verified-full/report.pdf` 200. Stopped the web app
  afterward.
- **Manual visual review -- not performed by this session**: no browser display in this
  environment. The demo masthead spacing, the sidebar's sticky-header behavior at a
  realistic laptop viewport height, and the scrollspy actually highlighting the correct
  Evidence & Audit item as you scroll past it (or click it) were all fixed at the root cause
  and verified structurally/via CSS and JS source, not confirmed by looking at the page.
  Ahsan should manually re-verify: the demo report's masthead links read cleanly with real
  spacing; the sidebar's Collapse button stays visible at the top of the sidebar area as the
  report and the TOC list are scrolled independently; clicking through all five Evidence &
  Audit items (and scrolling past them) correctly moves the active/current indicator each
  time, in both directions.
- **Docker**: rebuilt `team-checkmate-v5-redlab:latest` from the unmodified `Dockerfile`. All
  four expensive layers reported `CACHED`; only `COPY . .` and the final `useradd`/`chown`
  step re-ran. Confirmed over real HTTP: `/healthz` 200, `/` 200, `/verified-full/
  report.html` 200, `/verified-full/analysis.json` inline JSON with correct headers.
  Container removed afterward; did not run the full 1,928-case suite.
- **Files changed this session**: `report/style.css` (restored `.masthead nav` rules,
  sidebar sticky-head/scroll split, `scroll-margin-top` on Evidence & Audit targets),
  `report/template.html` (sidebar markup restructure, Evidence & Audit sidebar reorder,
  scrollspy rewrite, hero-meta badge removal, schema-wording fix), `report/demo_template.html`
  (schema-wording fix only), `tests/test_report.py` (11 new tests),
  `artifacts/verified_full_report/report.html` + `export_meta.json` (re-rendered view only,
  evidence untouched), this file. **No changes** to `web/app.py`, `web/static/`,
  `web/templates/`, `run_all.py`, `contract.py`, `report/generate.py`, `report/audit.html`,
  `endpoint/`, `runner/`, `analysis/`, `baseline/`, or `attacks/` -- confirmed via `git diff`
  before committing. `git diff --check`: clean (only pre-existing LF/CRLF warnings).
- **Not done / explicitly out of scope**: V5.4 (Try Your Own Input), V5.5, V5.6, and any
  broader Red Lab visual redesign (color balance, new decorative motifs, motion/animation,
  a more "premium" identity) -- all intentionally deferred; none of it was inferred or
  speculatively implemented this session. No push to GitHub `origin` or the `space` Hugging
  Face remote. No merge to `main`. `v4.0.0`/`bba3a7b`, the V5.1 commit `6b0bc9c`, and the
  V5.2 commit `5eb8735` are all untouched.
- Next: Ahsan performs the manual visual/browser review above, then decides whether to
  proceed to V5.4, V5.5, a future visual-polish brief, or push `ahsan/v5-redlab`.

## System V5.3 - interactive technical report / complete sidebar - Claude

- Updated: 2026-09-10T07:20:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `5eb8735` at session start (the closed V5.2 commit, local-only, not pushed anywhere). This
  session's changes are a **new** commit after V5.2, per explicit instruction not to amend
  `6b0bc9c` (V5.1) or `5eb8735` (V5.2).
- Scope: restructure the *presentation and navigation* of `report/template.html` (the full
  Technical Report only -- `report/demo_template.html` untouched) around the same evidence.
  No attack/runner/analysis/severity/finding-grouping/remediation-semantics/`contract.py`
  changes; no benchmark rerun; no change to any calculated number. V5.2's live-demo
  execution UX (`web/app.py`, `/api/run`, `/api/status`, reattachment, retry, redirect) was
  not touched. V5.4 (custom input) and V5.6 (HF deployment) untouched.
- **Information architecture** (inspected the actual current `report/template.html` and
  `report/audit.html` before designing anything -- the sidebar below covers exactly what
  already exists, nothing invented): Overview (the hero, then a new `#experiment` section
  introducing V1 and V2 individually **before** the comparison) -> Measured Outcomes ->
  Findings -> a new Remediation section -> Method -> Evidence & Audit. 22 real sidebar
  anchors total; every one was verified (by a test and by inspecting a real rendered report)
  to resolve to an actual `id` in the document, and every `id` in the whole page is unique.
- **Opening restructure**: the hero is unchanged in spirit (`TECHNICAL REPORT`, no
  "Robustness under pressure" -- that phrase has been gone since V3) but gained a
  `.report-kicker` tagline ("Adversarial Input Red-Teaming Toolkit") and a tighter one-
  sentence deck. Immediately after it, a new `#experiment` section states **"Same underlying
  AI model"** in bold, then a `.endpoint-pair` of two cards -- `#v1-intro` (rust/red accent,
  its real limitations: no length guard, no strict types, no exception hardening, no
  normalization) and `#v2-intro` (green accent, the real four defenses) -- each showing two
  genuine top-line stats pulled from the *existing* per-version context
  (`versions[0]`/`versions[1]`: `coverage.coverage_rate`, `drift.flip_rate` -- no new Python,
  no invented numbers). The "What changed after hardening?" verdict/withheld block (now
  `id="comparison"`, previously no id) comes strictly after both intro cards, both in DOM
  order and via a test asserting exactly that (`overview < v1-intro < v2-intro < comparison`
  as byte offsets in the rendered HTML). "V1 — Unhardened Endpoint" / "V2 — Hardened
  Endpoint" now appear as the *only* two label strings used anywhere for each endpoint
  (verified: `Hardened version`/`Protected API` phrasing tested absent).
- **Pipeline relocated**: the `Clean baseline → Attack library → V1/V2 runner → Manifest +
  results → Analysis → This report` flow diagram moved from the old opening straight into a
  new `#pipeline` panel inside Method (`#method`), first of three Method panels (Pipeline,
  Four Defenses `#defenses`, Interpretation Limits `#interpretation-limits`). It appears
  exactly once (tested). No Method subsections beyond these three were invented -- the brief
  explicitly required grounding the sidebar in what genuinely exists, and Method currently
  has no separate written content on baseline/dataset internals, attack-library internals,
  runner internals, or confidence/flip logic as distinct sections (that logic is explained
  inline in the drift-panel captions, unchanged), so no fabricated sidebar entries were added
  for them.
- **New Remediation section** (`#remediation`, between Findings and Method): a Jinja-only,
  zero-Python-change addition. Walks every finding across both versions
  (`{% for s in versions %}{% for e in s.entries %}`) and collects `e.finding.remediation`
  strings into a deduplicated list (`{% set remediations = [] %}` + the standard Jinja
  `list.append()`-inside-a-loop pattern, which works because the list *object* is mutated,
  not rebound), rendered verbatim -- the exact same text already shown per-finding, just
  collected once for reference. An empty-findings run renders a calm fallback sentence
  instead of an empty list (covered by the `data` fixture's default zero-findings case).
- **Findings navigation**: `#findings` gained per-version wrapper `<div id="v1-findings">`/
  `<div id="v2-findings">` around the existing (unmodified, still severity/score-sorted)
  register and finding-index nav, so the sidebar can link straight to each version's
  register. Individual finding cards keep their existing stable `id="{{ e.anchor }}"`
  (`finding-v1-1`, etc., unchanged). Deliberately did **not** restructure the finding list
  into resolved/remaining sub-groups in the DOM -- that would require re-deriving which of
  two independent status-tagging code paths (`e.comparison.status` for V1's own groups vs.
  V2 groups that also matched V1) applies to a given card, and a subtle mistake there risks
  silently dropping or duplicating a finding in a "verified" artifact. The existing verdict
  block already shows the authoritative resolved/remaining/new/inconclusive counts; the
  sidebar's "Findings" entry points there via `#comparison`, and the register itself is one
  click away, unchanged.
- **Evidence & Audit** (`#appendix`, renamed heading text from "Audit Appendix"): the second,
  previously-un-anchored `<details>` per version ("evidence validity and unscored
  observations": review queue, diagnostic observations) gained `id="v1-validity"`/
  `id="v2-validity"`; the existing `id="{{ s.version }}-audit"` details (category eligibility,
  baseline exclusions, per-flip evidence) and the provenance/hashes block (now
  `id="provenance"`, previously un-anchored) round out this group. Nothing in `audit.html`
  or the actual data shown was changed.
- **Desktop sidebar**: `.report-shell` is a real two-column CSS grid
  (`grid-template-columns: 280px 1fr`), not an overlay -- `<aside id="report-toc">` and
  `<main id="report-main">` are its two grid children, so the sidebar can never cover the
  report; toggling `.toc-collapsed` on `.report-shell` switches the first column to 56px and
  the main column reflows to fill the rest (`.report-shell > main { min-width: 0; }`
  prevents a long attack-ID/hash from forcing grid blowout and horizontal scroll). The
  sidebar is `position: sticky; top: var(--report-nav-height)` (a new, explicit
  `--report-nav-height: 84px` custom property, paired with `.masthead { min-height:
  var(--report-nav-height) }` so the sticky offset is deterministic rather than guessed) and
  scrolls its own contents independently once taller than the viewport
  (`max-height: calc(100vh - var(--report-nav-height)); overflow-y: auto`).
- **Mobile drawer** (`<=760px`, the stylesheet's existing breakpoint -- no new one
  introduced): `.report-shell` drops to `display: block`; `.report-toc` becomes `position:
  fixed`, off-canvas (`transform: translateX(-100%)`), toggled by the top bar's new
  `#toc-toggle` "Contents" button (`aria-expanded`/`aria-controls="report-toc"`, mobile-only
  via `display:none` outside the breakpoint) with a `#toc-backdrop` behind it and a
  `#toc-close` button inside. Selecting a link closes the drawer (desktop clicks do not).
  Escape closes it from anywhere on the page. Focus moves into the drawer (`#toc-close`) on
  open and back to the toggle button on close. Report tables/finding cards/evidence hashes
  were not touched by this -- their existing `overflow-wrap: anywhere` / responsive rules
  from V4/V5.1 are unaffected since the drawer only exists in the sidebar's own fixed layer.
- **Collapsible TOC groups**: each of the six top-level groups (Overview / Measured Outcomes
  / Findings / Remediation / Method / Evidence & Audit) has its own `.toc-group-toggle`
  button (`aria-expanded`/`aria-controls`) independent of the mobile drawer's open/closed
  state; all default expanded. Subsection counts were kept deliberately modest (2-5 real
  entries per group, 22 total) rather than one entry per finding card, per the brief's
  explicit "meaningful grouped navigation, not hundreds of entries" instruction.
- **Scrollspy**: a single `IntersectionObserver` (rootMargin `-15% 0px -70% 0px`, no
  polling/scroll-event listener) watches every element the sidebar actually links to;
  whichever one is nearest the top of the viewport gets `.is-active` **and**
  `aria-current="location"` on its sidebar link -- the accent is `var(--rl-red)` (tested
  directly against the CSS rule, not just eyeballed) plus a bold-weight/left-border change,
  never color alone. Clicking a sidebar link relies on the browser's native same-page anchor
  navigation (unchanged `href="#id"`) plus the page's existing `scroll-behavior: smooth`,
  which is now gated behind `@media (prefers-reduced-motion: no-preference)` (previously
  unconditional -- a small, safe, correctness fix made while already touching this rule for
  the brief's explicit reduced-motion requirement). The drawer's slide transition and the
  TOC-group chevron rotation are separately neutralized under `prefers-reduced-motion: reduce`.
- **CSP change (deliberate, necessary, narrowly scoped)**: the report's
  `<meta http-equiv="Content-Security-Policy">` previously had no `script-src` at all, so
  `default-src 'none'` blocked *any* script execution -- correct when the report had no
  script. Since V5.3 adds one, the CSP now includes `script-src 'unsafe-inline'` alongside
  the existing `style-src 'unsafe-inline'`. Still no external script (or style, or anything
  else) source of any kind, no `eval`, nothing else in the policy changed (tested: the CSP
  string contains no `http` and no `eval`). WeasyPrint never executes `<script>` when
  rendering `report.pdf` -- confirmed by a real PDF render (see below) producing the same
  49-page output as before this session, script tag present in the source but inert.
- **Visual system**: reused the established Red Lab tokens only; V1 accents stayed
  rust/red (`var(--rl-danger)`), V2 green (`var(--rl-success)`), the new endpoint-intro
  cards and remediation list reuse the existing `.panel`/`.notice` visual language rather
  than introducing a new component style. No existing data component (category-table,
  finding cards, bar charts, audit `<details>`) was redesigned.
- **Tests**: added 14 tests to `tests/test_report.py` (old marketing hero/CLI wording
  absent; V1 and V2 introduced before `#comparison`, in that DOM order; the "Same underlying
  AI model" statement exists; V1/V2 labels are the *only* phrasing used, exactly twice each;
  the pipeline lives inside Method, once, never in the opening; Findings and Evidence
  sidebar entries exist; the sidebar has >=15 entries and **every** `href="#x"` resolves to a
  real `id="x"` in the same rendered document, with no duplicate IDs anywhere on the page --
  checked against a real finding-populated fixture, not just the empty default; desktop
  collapse and mobile drawer controls exist with correct `aria-*` wiring; the print CSS
  hides the sidebar/backdrop/toggle and returns `.report-shell` to `display: block`; Source
  JSON/Home/Download PDF remain present and correctly attributed; the grid's
  `min-width: 0` overflow guard is present; the active-nav-link rule uses
  `var(--rl-red)`, not teal; the CSP contains `script-src 'unsafe-inline'` and nothing
  externally reachable). One **pre-existing** test needed updating for the same reason the
  V3 session once updated the "zero `<img>` tags" XSS test for the new legitimate logo:
  `test_xss_and_template_syntax_are_plain_text` used to assert zero `<script>` tags
  anywhere; it now asserts exactly one (the report's own, static, repository-owned script),
  and separately asserts the untrusted `<script>alert(1)</script>` payload never appears
  inside that one real script's body (only inside its own HTML-escaped rendering elsewhere
  on the page). While fixing this I also caught and fixed a real self-inflicted bug: a CSS
  comment I wrote literally contained the text `<script>` as prose, which made the test's
  first naive `result.index("<script>")` match the *comment*, not the real tag -- reworded
  the comment and made the test search only after `</style>` so this class of mistake can't
  silently recur. Full suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
  .venv/Scripts/python.exe -m pytest -q`: **496 passed** (483 at session start + 13 net new
  in the V5.3 block), 1 pre-existing Starlette/AnyIO warning.
- **Verified full-report re-render** (same pattern as V5.1/V5.2, not a new benchmark):
  `analysis.json`'s SHA-256 was recorded (`12d47b3...`) **before** rendering and re-checked
  **after** -- byte-identical, confirmed by reading the file fresh from disk post-render, not
  assumed. Only `report.html` was regenerated (via `report.generate.render_html(mode="full")`
  against that same, untouched `analysis.json`) and copied into
  `artifacts/verified_full_report/`; `export_meta.json` got only its `report.html` hash
  field updated. `report.pdf`'s SHA-256 was independently re-checked against
  `export_meta.json` after the HTML swap and still matches -- the original verified PDF was
  never opened for writing. Confirmed on the real updated artifact (not just the test
  fixture): 22 sidebar targets, all resolving, zero duplicate IDs, zero occurrences of
  "Robustness" or "run_all.py".
- **PDF safety check**: separately rendered a full bundle (HTML **and** PDF) from
  `results/repro_1/report/analysis.json` to a **temporary scratch location** (never touching
  the preserved verified PDF) to confirm the new grid/sidebar/script markup doesn't break
  WeasyPrint -- succeeded, 49 pages, matching prior sessions' page counts for this same
  source data; the print media query's `display: block` override was exercised for real
  here, not just asserted in a unit test.
- **Real local acceptance test** (not mocked): started `uvicorn web.app:app` on
  `127.0.0.1:7860`; confirmed `/` and `/healthz` 200. Ran a live-demo smoke check via a real
  `POST /api/run` (no execution code changed this session, so a full run wasn't strictly
  required by the brief, but one was already in flight by the time of the smoke check and
  was let finish rather than abandoned mid-job) -- completed normally, V5.2's stage sequence
  unaffected. Verified over real HTTP: `GET /verified-full/report.html` 200 with the sidebar
  (`id="report-toc"`), the Home link (present twice), and the `#experiment` section all
  present in the actually-served bytes; `GET /verified-full/analysis.json` 200
  `application/json; charset=utf-8` with no `content-disposition` (the V5.1 route,
  unaffected); `GET /verified-full/report.pdf` 200. Confirmed via `netstat` that ports
  8000/8001 had no `LISTENING` socket after the run; stopped the web app; deleted the
  throwaway `results/hf_demo_*` directory.
- **Manual visual review -- not performed by this session**: no browser display in this
  environment. Everything above (sidebar grid columns not overlaying content, the drawer's
  actual slide animation, scrollspy highlighting as you scroll, the collapse rail's visual
  width) is structural/CSS-source/HTTP-level verification, not a screenshot-level
  confirmation of how it *looks*. Ahsan should manually check, in a real browser: desktop --
  the sidebar sits beside the report and collapses to a narrow rail without covering
  content, clicking a sidebar link highlights it as you scroll past that section; mobile --
  the Contents button opens a drawer over a backdrop, closes on Escape/backdrop-click/link-
  click, and the report's tables/finding cards still read fine with the drawer closed;
  print/PDF preview -- confirm the sidebar and Contents button genuinely disappear and the
  report reads full-width.
- **Docker**: rebuilt `team-checkmate-v5-redlab:latest` from the unmodified `Dockerfile`. All
  four expensive layers (`apt-get`, `COPY requirements.txt .`, `pip install`, the pinned-
  model pre-download) reported `CACHED`; only `COPY . .` and the final `useradd`/`chown` step
  re-ran. Ran the freshly built image and confirmed over real HTTP: `/healthz` 200, `/` 200,
  `/verified-full/report.html` 200, `/verified-full/analysis.json` 200
  `application/json; charset=utf-8` (no attachment header), `/verified-full/report.pdf` 200.
  Container removed afterward; did not run the full 1,928-case suite; the image itself was
  left built.
- **Files changed this session**: `report/template.html` (full restructure -- sidebar,
  masthead simplification, experiment/remediation sections, wrapper IDs, inline script),
  `report/style.css` (sidebar/drawer/scrollspy rules, endpoint-intro/remediation styles,
  reduced-motion guards, print-safety additions -- original mobile-breakpoint rules were
  preserved, merged alongside the new mobile-drawer rules in the same `@media (max-width:
  760px)` block, not replaced), `tests/test_report.py` (14 new tests + 1 updated pre-existing
  test + a `re` import), `artifacts/verified_full_report/report.html` +
  `export_meta.json` (re-rendered view only, evidence untouched), this file. **No changes**
  to `report/demo_template.html`, `report/generate.py`, `report/audit.html`, `web/app.py`,
  `web/static/`, `web/templates/`, `run_all.py`, `contract.py`, `endpoint/`, `runner/`,
  `analysis/`, `baseline/`, or `attacks/` -- confirmed via `git diff` before committing.
  `git diff --check`: clean (only pre-existing LF/CRLF warnings).
- **Not done / explicitly out of scope**: V5.4 (Try Your Own Input), V5.5 (final
  integration/hardening/responsive acceptance), V5.6 (Hugging Face deployment/public
  visibility). No push to GitHub `origin` or the `space` Hugging Face remote. No merge to
  `main`. `v4.0.0`/`bba3a7b`, the V5.1 commit `6b0bc9c`, and the V5.2 commit `5eb8735` are
  all untouched.
- Next: Ahsan performs the manual visual/browser review above (desktop sidebar behavior,
  mobile drawer, print/PDF preview), then decides whether to proceed to V5.4, V5.5, or push
  `ahsan/v5-redlab`.

## System V5.2 CLOSED - final visual polish - Claude

- Updated: 2026-09-10T06:50:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `64de35f` at session start (the V5.2 commit below, local-only, not pushed anywhere). This
  session's changes are folded into that same commit via `git commit --amend` once verified
  (explicit instruction: keep V5.2 as one clean logical commit after V5.1; do not amend V5.1
  `6b0bc9c`; confirmed `ahsan/v5-redlab` still has no upstream ref on `origin` or `space`
  before amending).
- Ahsan's real-browser manual review of V5.2 found four issues to close before V5.2 is done:
  the execution view leaking onto the idle home page, developer/CLI wording in judge-facing
  pages, a visually weak completion state, and an inconsistent top navigation. Scope stayed
  presentation-only: no attack/runner/analysis/severity/remediation/`contract.py` changes,
  no benchmark rerun; V5.3/V5.4/Hugging Face deployment untouched.
- **Root-caused and fixed the critical idle-home bug**: `#view-execution` carried the
  `hidden` attribute in the server-rendered HTML the whole time, but `.execution-view {
  display: flex; ... }` (an author-stylesheet class rule) has the exact same CSS specificity
  as the browser's own UA-stylesheet rule `[hidden] { display: none }` -- and any author rule
  beats a UA rule at equal specificity regardless of the `hidden` attribute being present.
  So the execution view was rendering, visible, under the hero on every fresh page load.
  Fixed with one global safeguard in `web/static/app.css` (added right after the `*` reset):
  `[hidden] { display: none !important; }`, plus a code comment establishing this as the one
  place "hidden means gone" is decided -- no future element may add a competing `display`
  override for something toggled via the `hidden` attribute instead. Verified live: fresh
  `GET /` now serves `<section id="view-execution" ... hidden>` with the safeguard rule
  present in the served CSS, and the rendered HTML's "Launching adversarial test…" text
  exists only inside that now-actually-hidden section (this was never a text-presence bug --
  the markup was always structurally correct; only the CSS cascade was wrong).
- **Removed all user-facing developer/CLI wording**: `report/demo_template.html` had two
  literal `<code>python run_all.py --mode full</code>` instructions visible in the rendered
  Live Demo Results page (the partial-suite banner and the Method section). Both now say
  "Technical Report" instead, and link to it via the existing `detailed_report` context
  (`{% if detailed_report and detailed_report.available %}`, the same field the masthead's
  "View Detailed Report" link already uses -- no new data plumbing) when that artifact is
  present, plain text otherwise -- never a CLI instruction either way. A source-level Jinja
  comment on line 10 still says `run_all.py` (`{# ... which run_all.py pre-escapes itself #}`)
  -- that is a template *comment*, stripped by Jinja before rendering and never reaches a
  browser, so it was deliberately left alone (developer documentation, not product UI).
  `web/templates/index.html`'s CTA caption dropped "inside this container" for "against both
  endpoint configurations" -- product language, no deployment/container internals implied.
  Grepped every user-facing template (`report/*.html`, `web/templates/*.html`) for
  `run_all.py`, `python run_all`, "inside this container", `localhost`/`127.0.0.1`,
  `filesystem` after the fix: zero remaining hits outside that one Jinja comment.
- **Completion heading hierarchy**: this was already using the same `#exec-heading` element
  and `.exec-heading` CSS class as every in-progress stage message (`execHeading.textContent
  = "Experiment complete"`, not a separate/smaller element) -- the "visually weak" impression
  Ahsan saw was very likely a symptom of the idle-home bug above (the still-visible 60-76px
  hero wordmark competing with/dwarfing the 34px execution heading in the same viewport).
  Hardened it anyway with a small, restrained, semantic touch: `#view-execution` gains an
  `is-complete` class on completion, which colors the heading and the progress fill
  `var(--rl-success)` green (matching the existing V2/healthy semantic used everywhere else
  in the product) -- no animation, no confetti. The class is cleared in
  `activateExecutionView()` so a Retry after a later failure, or a fresh run, doesn't start
  in a stale "complete" color.
- **Navbar visual consistency** (explicitly NOT the V5.3 sidebar restructuring): the report
  masthead (`report/style.css`, both templates) previously showed only "TEAM CHECKMATE" (or
  "TEAM CHECKMATE / DEMO") with no Red Lab version label, unlike the web app's masthead which
  already showed both lines. Both report templates' `.brand` now renders a `.brand-lines`
  column with `.brand-name` ("TEAM CHECKMATE") and `.brand-version` ({{ product_version_label
  }}, i.e. "Red Lab v5.0") -- reusing the context variable `render_html` already passed in,
  no Python changes needed. Nav-link hover treatment was unified across the web app and the
  reports: both now use a charcoal-by-default, `var(--rl-red)`-on-hover-or-`aria-current`
  text color with a modest 2px bottom border (transparent by default, red on hover/active) --
  previously the report's nav links inherited the global `a { color: red }` rule and were
  red-by-default rather than accented-on-interaction, a small but real visual mismatch with
  the web app's charcoal-default nav. The report's `.button`-class links (Download PDF, View
  Detailed Report) are explicitly excluded from the new border/color rule via `:not(.button)`
  so the existing solid dark button styling is untouched. No content-width, nav-height, or
  logo-size changes were made to the report masthead (all flagged as V5.3-scale restructuring
  risk, especially given `report/style.css`'s existing print/pagination tuning) -- this was
  kept to the smallest safe adjustment that unifies identity and interaction color/underline
  only. The web app's `.primary-nav a` gained the matching bottom-border treatment and
  `aria-current="page"` on the Home link.
- **Navbar behavior**: the web app's "Live Demo" nav item no longer just scrolls to `#run`.
  `web/static/app.js` gained `goToLiveDemo()`, which checks `/api/status` first -- if a run
  is already active it reattaches via the exact same `activateExecutionView()`/`applyState()`
  path the reattach-on-load logic already uses (no visible reset to 0%), otherwise it calls
  the exact same `startRun()` the main CTA and Retry button use. No second, parallel
  run-launch code path was introduced (single source of truth, per the brief); the backend's
  existing single-job lock is untouched and remains the authoritative guard against a real
  second `run_experiment()` call regardless of which UI element triggered the request. The
  anchor's `href="#run"` is kept as a no-JS graceful-degradation fallback; the JS handler
  calls `preventDefault()` and takes over when script is available.
- **Tests**: added 5 to `tests/test_web.py` (the `[hidden] { display: none !important; }`
  safeguard is present in served CSS; the Home nav link carries `aria-current="page"`; "inside
  this container" is absent from the home page; exactly one `#exec-heading` element exists
  server-side and `app.js` writes both the running-stage message and the literal "Experiment
  complete" string to it, never a second/smaller element; `app.js` defines `goToLiveDemo()`
  reusing `startRun(triggerEl)` rather than a duplicated run-start path) and 4 to
  `tests/test_report.py` (the demo report never contains `run_all.py`/`python run_all`; the
  partial-suite banner and Method section point to "Technical Report" -- with a real link
  when `detailed_report.available` is set, plain text otherwise -- never a CLI instruction
  either way; both report masthead brands show "TEAM CHECKMATE" and "Red Lab v5.0"). Full
  suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **483 passed** (474 at session start + 9 new), 1 pre-existing Starlette/AnyIO warning.
- **Preserved verified artifact re-rendered again** (same pattern as V5.1, not a new
  benchmark): `report/template.html`/`report/style.css` changed (masthead brand + nav
  styling), so `artifacts/verified_full_report/report.html` was stale relative to them.
  Re-rendered *only* `report.html` from the same, byte-verified `analysis.json` (SHA-256
  unchanged) through the current `report.generate.render_html(mode="full")`, then updated
  only the `report.html` entry in `export_meta.json` to the new file's hash. Confirmed by
  hash before/after: `analysis.json` and `report.pdf` are byte-for-byte unchanged; only
  `report.html`'s hash (and the file itself) changed, and `export_meta.json` was updated to
  match it exactly.
- **Real local acceptance test** (not mocked): started `uvicorn web.app:app` on
  `127.0.0.1:7860`. Confirmed over real HTTP, against the actual served files: fresh `GET /`
  serves `<section id="view-execution" ... hidden>` with the CSS safeguard present in the
  served `/static/app.css`, no "inside this container" text, and `aria-current="page"` on the
  Home nav link. Ran one real demo experiment via `POST /api/run` (genuine V1/V2 uvicorn
  processes, ~36s); the served `report.html` contains zero `run_all.py`/`python run_all`
  occurrences, two "Technical Report" mentions (banner + Method section), and the masthead
  brand shows "Red Lab v5.0"; `analysis.json` still returns `application/json; charset=utf-8`
  with no `content-disposition` (the V5.1 dedicated route, unaffected by this session).
  Confirmed via `netstat` that ports 8000/8001 had no `LISTENING` socket after completion.
  Stopped the web app process afterward; deleted the throwaway `results/hf_demo_*` directory.
- **Manual visual review -- still not performed by this session**: no browser display in this
  environment. Everything above is structural/HTTP-level verification of the actual root
  cause and its fix, not a screenshot-level confirmation that the page now *looks* right.
  Ahsan should re-verify in a real browser: fresh `/` shows nothing but the home hero (no
  "LIVE DEMO / Launching adversarial test…" ghosting through underneath), the completion
  state's green accent reads clearly, the navbar looks consistent across the home page, the
  execution screen, and a generated Live Demo Results / Technical Report page, and that the
  "Live Demo" nav item behaves sensibly whether idle or mid-run.
- **Docker**: rebuilt `team-checkmate-v5-redlab:latest` from the unmodified `Dockerfile`. All
  four expensive layers (`apt-get`, `COPY requirements.txt .`, `pip install`, the pinned-
  model pre-download) reported `CACHED`; only `COPY . .` and the final `useradd`/`chown` step
  re-ran. Ran the freshly built image, confirmed `/healthz` and `/` both 200 and the served
  home page still has the (now correctly hidden) execution view, then removed the container.
  Did not run a second containerized full demo this session (the local real demo run plus the
  full test suite were judged sufficient, per the brief's explicit "optional" wording); the
  image itself was left built. Did not run the full 1,928-case suite.
- **Files changed this session**: `web/static/app.css` (the `[hidden]` safeguard, nav
  bottom-border treatment, `is-complete` accent), `web/static/app.js` (`goToLiveDemo()`,
  `is-complete` class handling), `web/templates/index.html` (`aria-current="page"`, CTA
  caption wording, `nav-live-demo` id), `report/style.css` (masthead brand-lines/version,
  unified nav-link hover/active treatment), `report/template.html` and
  `report/demo_template.html` (masthead brand markup, CLI-wording removal in the demo
  template), `tests/test_web.py` and `tests/test_report.py` (9 new tests),
  `artifacts/verified_full_report/report.html` + `export_meta.json` (re-rendered view only,
  evidence untouched), this file. No changes to `web/app.py`, `run_all.py`, `contract.py`,
  `endpoint/`, `runner/`, `analysis/`, `baseline/`, or `attacks/` -- confirmed via `git diff`
  before committing. `git diff --check`: clean (only pre-existing LF/CRLF warnings).
- **Not done / explicitly out of scope**: V5.3 (technical-report restructuring, V1-left/
  V2-right layout, interactive-book sidebar -- the report masthead changes here were
  deliberately limited to brand text and nav-link color, never content-width/nav-height/logo
  size or a sidebar), V5.4 (Try Your Own Input), V5.5, V5.6. No push to GitHub `origin` or
  the `space` Hugging Face remote. No merge to `main`. `v4.0.0`/`bba3a7b` and the V5.1 commit
  `6b0bc9c` are both untouched.
- Next: Ahsan performs the manual visual/browser review above, then decides whether to
  proceed to V5.3, V5.4, or push `ahsan/v5-redlab`.

## System V5.2 - full-screen live-demo execution UX - Claude

- Updated: 2026-09-10T06:10:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `6b0bc9c` at session start (the closed V5.1 commit, local-only, not pushed anywhere). This
  session's changes are a **new** commit after V5.1, per explicit instruction not to amend
  `6b0bc9c`.
- Scope: only the dedicated full-screen live-demo execution UX. No attack/runner/analysis/
  severity/remediation/`contract.py` changes; no re-run of the 1,928-case benchmark; `POST
  /api/run`, `GET /api/status`, the single-active-job lock, and `run_all.run_experiment()`
  itself were not touched -- this is a client-side/template presentation change consuming the
  same existing API. V5.3 (report restructuring/sidebar), V5.4 (custom input), Hugging Face
  deployment/visibility were explicitly not touched.
- **Architecture**: `web/templates/index.html` now has two mutually exclusive top-level
  views inside `<main>`: `#view-home` (the existing hero/CTA, unchanged content) and a new
  `#view-execution` (`hidden` by default), both rendered server-side on every `GET /`.
  `web/static/app.js` is the only thing that decides which one is visible, via the `hidden`
  DOM attribute -- there is no new route and no server-side view state; `/` still always
  renders both, idle-by-default, matching the existing V4 "never redirect a fresh visitor
  into a previous result" contract. No React/Vue/Svelte introduced; still FastAPI + Jinja +
  vanilla JS, per the brief's explicit constraint.
- **Home -> execution transition** (`startRun()` in `app.js`): on click, immediately (before
  `POST /api/run` resolves) hides `#view-home`, un-hides `#view-execution`, resets the
  progress bar/stage list, sets the status heading to "Launching adversarial test…", and
  moves focus to that heading (`tabindex="-1"` + `.focus()`) -- satisfies the accessibility
  focus-management requirement and gives an immediate startup state even before the network
  round-trip completes. A `launching` boolean (not the old disabled-button check, since the
  button is now hidden) prevents a double-click from firing two `POST /api/run` calls; the
  backend's existing single-job lock is unchanged and is still the authoritative guard against
  two overlapping experiments (verified unchanged: `test_second_start_during_active_run_
  returns_same_job_not_a_new_one` still passes).
- **Execution screen content** (`#view-execution`): identity line ("Team Checkmate / Red Lab
  v5.0"), a static "LIVE DEMO" functional-title eyebrow, and one dynamic `<h1 id="exec-heading"
  aria-live="polite">` that carries the real stage message (`STAGE_LABELS[stage]` from
  `web/app.py`, unchanged single source of truth -- the template loops `stage_order`/
  `stage_labels` exactly as V4 did, no second copy of stage names introduced). Below it: a
  `role="progressbar"` bar with real `aria-valuemin/valuemax/valuenow` (updated from
  `state.percent`, never a fake incrementing timer), a plain-language percent label, the
  existing `<ol class="stage-list">` (done/active/future distinguished by both color AND a
  text glyph via existing `::before` content -- checkmark for done, triangle for active --
  colorblind-safe, unchanged from V4), and two small "V1 -- Unhardened Endpoint / No
  application-layer hardening" and "V2 -- Hardened Endpoint / Input validation, length
  controls, exception handling and normalization" cards plus a "Same underlying AI model in
  both cases" note -- static product copy (like the report templates' existing "four
  defenses" list), not derived from the run itself.
- **Completion transition**: on `status: complete`, the heading becomes "Experiment complete",
  the bar fills to 100%, and after a fixed `COMPLETE_REDIRECT_DELAY_MS = 900`ms
  `window.location.href = state.result_url` -- the real backend-returned URL, never
  constructed or guessed client-side. A `redirectTimer` guard stops a second poll response
  from scheduling a duplicate navigation.
- **Failure experience**: on `status: failed`, `showFailure()` hides the progress/stage-list/
  version-card block (`#exec-body`), shows `#exec-failure` with the heading replaced by
  "LIVE DEMO FAILED", the backend's existing safe public error string in a `role="alert"`
  paragraph (unchanged backend message, still never a traceback/path -- see V4's
  `test_failed_job_exposes_safe_message_not_a_traceback`), a real "Retry Live Demo" button
  that calls the same `startRun()`/`POST /api/run` path again, and a plain "Back to Red Lab"
  link (`href="/"`, a full reload, not a SPA route -- simplest safe option per the brief).
  No cancel button anywhere (verified by a test asserting no "cancel" text/id exists in either
  the rendered execution view or the served `app.js`).
- **Reattachment on load**: `app.js`'s existing startup `GET /api/status` fetch now calls
  `activateExecutionView()` (view switch only, not a fake "Launching…" reset) followed by
  `applyState(state)` when `status === "running"` -- a mid-run page refresh or a second
  visitor lands directly in the live execution view showing the *actual* current stage, not
  a re-synced fake one. `complete`/`failed`/`idle` are left alone on load (no branch handles
  them) so a fresh visitor after a run has finished still sees the ordinary home page,
  preserving the V4 "never auto-redirect a fresh visitor into old results" contract exactly.
- **Accessibility**: `role="progressbar"` + `aria-valuemin`/`aria-valuemax`/`aria-valuenow`
  (kept live-updated) plus a dynamic `aria-valuetext` ("65%, Testing the hardened endpoint");
  `aria-live="polite"` on the status heading so stage changes are announced without moving
  focus repeatedly; `role="alert"` on the failure message so it's announced assertively;
  focus moves to the status heading exactly once, on the home->execution transition; the
  mobile hamburger nav's `aria-expanded`/`aria-controls` markup is untouched. A
  `@media (prefers-reduced-motion: no-preference)` guard wraps the one-off 0.18s fade-in
  applied when `#view-execution` becomes visible; the fade is CSS-only and never delays the
  real `POST /api/run` call (the fetch fires synchronously from the same click handler,
  independent of any CSS animation timing).
- **Visual system**: reused the existing Red Lab tokens only (`--rl-red`/`--rl-charcoal`/
  `--rl-paper`/`--rl-surface`/`--rl-muted`/`--rl-border`/`--rl-success`/`--rl-danger`) --
  no teal, no gradients, no neon. V1 card gets a `var(--rl-danger)` left accent, V2 a
  `var(--rl-success)` one, matching the same V1=red/V2=green semantic used everywhere else
  in the product (reports, stage-list `.done` color). The execution view is
  `min-height: calc(100vh - var(--rl-nav-height))` so the current stage is visible without
  scrolling on an ordinary desktop viewport, per the brief; on narrow viewports the version
  cards stack vertically and the heading shrinks (existing 760px breakpoint, no new one
  introduced).
- **Mobile navbar**: untouched structurally -- `web/static/app.js`'s hamburger toggle logic
  and `web/templates/index.html`'s masthead markup are identical to V5.1; the existing
  `test_home_has_mobile_menu_toggle_markup` test still passes unmodified.
- **Tests**: added 11 tests to `tests/test_web.py` covering: the home page renders both views
  with only `#view-execution` carrying `hidden`; the execution view's stage list uses the
  real `STAGE_ORDER`/`STAGE_LABELS` from `web/app.py` (not a duplicated/hardcoded list); the
  progressbar's ARIA attributes are present; the V1/V2 context cards and the same-model note
  are present; no "cancel" text anywhere in the execution view or in the served `app.js`; the
  failure block exposes Retry + Back-to-Red-Lab; no V5.4 "Try Your Own Input"/`<textarea>`
  exists yet; and four tests reading the served `app.js` source to confirm it still calls the
  real `/api/run`/`/api/status` endpoints (never re-implementing runner/analysis logic
  client-side), still performs the two required view-toggle assignments and the
  running-only reattachment check, still redirects using `state.result_url` (never a
  constructed path), and defines no cancel handler. These are deliberately structural/
  source-level checks, not full-HTML-string or CSS-pixel assertions, per the brief -- this
  repo has no headless-browser test runner, so JS *execution* itself is not exercised in
  pytest; the real-HTTP acceptance run below is what actually exercises the click-through
  behavior end to end (as far as `curl` can, i.e. the API sequence a real click drives, not
  the pixels). Full suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe
  -m pytest -q`: **474 passed** (463 at session start + 11 new), 1 pre-existing Starlette/
  AnyIO warning.
- **Real local acceptance test** (not mocked): started `uvicorn web.app:app` on
  `127.0.0.1:7860`, confirmed the freshly served home page still renders `#view-execution`
  with `hidden` present by default, then ran one real demo experiment via `POST /api/run`
  (genuine V1/V2 uvicorn processes, ~39s). Polled `/api/status` for real until `complete`,
  confirmed the exact same eight-stage sequence V4/V5.1 already established still fires
  unchanged (this session did not touch `run_all.py`). Verified over real HTTP: the served
  `report.html` 200; `analysis.json` 200 `application/json; charset=utf-8` with no
  `content-disposition` (the V5.1 dedicated route, unaffected by this session); the copied
  `detailed/report.html` (verified full report) 200; "Back to Red Lab" present twice in the
  generated report. Confirmed via `netstat` that ports 8000/8001 had no `LISTENING` socket
  after completion (only expected `TIME_WAIT`); stopped the web app process afterward and
  deleted the throwaway `results/hf_demo_*` directory (gitignored regardless).
- **Manual visual review -- explicitly not performed by this session**: this environment has
  no browser display, so no screenshot-level visual inspection of the execution screen, the
  transition, the completion redirect, or mobile layout was possible or is being claimed.
  Everything above is a structural/HTTP-level check. Ahsan should manually verify, in a real
  browser: desktop -- home, the instant on-click transition (home hero fully gone, no
  scrolling needed to see the current stage), the V1 and V2 attack stages, and the completion
  state's brief pause before redirecting; mobile -- the execution screen at a narrow width
  (stacked version cards, no horizontal overflow), the progress bar, the stage timeline, and
  that the hamburger nav still behaves correctly while a run is active.
- **Docker**: rebuilt `team-checkmate-v5-redlab:latest` from the unmodified `Dockerfile`. All
  four expensive layers (`apt-get`, `COPY requirements.txt .`, `pip install`, the pinned-
  model-revision pre-download) reported `CACHED`; only `COPY . .` and the final `useradd`/
  `chown` layer re-ran. Ran the freshly built image (`docker run -d -p 7863:7860 ...`),
  confirmed `/healthz` and `/` both 200 and the home page still serves the hidden execution
  view, then ran one **real containerized** demo end to end via `POST /api/run` (~24s),
  confirmed the served `report.html` and `analysis.json` (correct headers) over HTTP, and
  checked `docker exec ... cat /proc/net/tcp` for lingering listeners: only one `LISTEN`
  entry (`0x1EB4` = 7860, the web app itself); every `0x1F40`/`0x1F41` (8000/8001) entry was
  `TIME_WAIT`, confirming V1/V2 were shut down cleanly inside the container too. Container
  removed afterward (`docker rm -f`); the image itself was left built. The pre-existing
  `team-checkmate-v4:latest` image was not touched. Did not run the full 1,928-case suite
  (per instruction).
- **Files changed this session**: `web/templates/index.html` (new `#view-home`/
  `#view-execution` structure), `web/static/app.js` (rewritten state machine: view
  activation, launching/redirect guards, failure/retry handling, unchanged mobile-nav
  toggle code), `web/static/app.css` (new `.execution-view`/`.exec-*`/`.version-card` rules,
  removed the now-orphaned `.progress-panel`-specific rules, added the reduced-motion-guarded
  fade), `tests/test_web.py` (11 new tests), this file. **No changes** to `web/app.py`,
  `run_all.py`, `contract.py`, `report/`, `endpoint/`, `runner/`, `analysis/`, `baseline/`,
  or `attacks/` -- confirmed via `git diff` before committing. `git diff --check`: clean
  (only pre-existing LF/CRLF warnings).
- **Not done / explicitly out of scope**: V5.3 (technical-report restructuring, V1-left/
  V2-right layout, interactive-book sidebar), V5.4 (Try Your Own Input / custom-input
  engine), V5.5 (final integration/hardening/responsive acceptance), V5.6 (Hugging Face
  deployment/public visibility). No push to GitHub `origin` or the `space` Hugging Face
  remote. No merge to `main`. The V5.1 commit `6b0bc9c` was not amended -- this is a new
  commit on top of it, per explicit instruction.
- Next: Ahsan performs the manual visual/browser review above (desktop + mobile), then
  decides whether to proceed to V5.3, V5.4, or push `ahsan/v5-redlab`.

## System V5.1 CLOSED - final polish - Claude

- Updated: 2026-09-10T05:55:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `54e428a` at session start (the prior V5.1 checkpoint commit below, local-only, not pushed
  anywhere). This session's changes are folded into that same commit via `git commit --amend`
  once verified (explicit instruction: keep V5.1 as one clean logical commit; do not amend if
  it turns out to already be pushed -- confirmed not pushed to `origin` or the `space` HF
  remote before amending, see below).
- Ahsan manually reviewed V5.1 in a real browser and found presentation/behavior issues to close
  out before V5.1 is done. Scope was explicitly presentation/serving only: no attack, runner,
  analysis, severity, remediation, or `contract.py` changes; no re-run of the 1,928-case
  benchmark; V5.2 (full-screen live-demo UX), V5.3 (report restructuring/sidebar), V5.4 (custom
  input), V5.5, V5.6 explicitly deferred and not touched.
- **Color-scheme consistency**: removed the entire `@media (prefers-color-scheme: dark)` block
  from `web/static/app.css` (the only file that had one -- `report/style.css` never had one).
  Red Lab now renders with one deterministic warm-paper/charcoal/red identity regardless of the
  viewer's OS theme; `color-scheme: light` was already set and is kept. No theme selector was
  added (out of scope, explicitly deferred).
- **Mustard partial-suite banner**: `.partial-banner` in `report/style.css` no longer fills the
  whole panel with `var(--rl-warning)`. It's now `var(--rl-surface)` with a `var(--rl-border)`
  border and a 4px `var(--rl-red)` left accent; heading/body text use the charcoal/muted tokens;
  only the small eyebrow label ("LIVE DEMO RUN -- PARTIAL SUITE") keeps the amber warning color
  as a small status accent, per the brief's "amber as accent, not the whole panel" instruction.
  The partial-suite disclaimer copy itself is unchanged.
- **Demo failure-rate table**: `report/demo_template.html`'s category-comparison table now
  reuses the full report's exact proven markup instead of a thinner one-off: a `.panel-heading`
  with a `.legend` (V1/V2 color dots), "V1 · Unhardened"/"V2 · Hardened" column headers, and a
  `.bar-track`/`.bar` element per V1/V2 cell (same classes `report/style.css` already styles and
  makes responsive at 760px for the full report). No CSS was duplicated; no percentages/counts
  changed -- confirmed by a new test asserting a modified fixture's rate still renders as
  `25.00%` / `1 / 4` / `width: 25.0%` together.
- **Source JSON real HTTP bug -- root cause found, not just markup-inspected**: a real local
  `POST /api/run` demo run followed by `curl -D -` on the generated `analysis.json` showed the
  *live* demo report already served clean headers (`content-type: application/json`, no
  `content-disposition`) even before this session's changes -- the actual reproducible bug was
  in `artifacts/verified_full_report/report.html` (the preserved V3/V4-era Technical Report
  artifact), whose Source JSON anchor still had `<a href="analysis.json" download>`, a leftover
  from before the V3 session dropped that attribute on the live templates. That stale artifact
  is exactly what `/verified-full/report.html` serves (see the next item), so "Technical
  Report -> Source JSON" was the one real path that forced a download in a browser.
  Independent of that root cause, `web/app.py` also gained two small, explicitly path-restricted
  routes (`GET /results/{run_name}/report/analysis.json`, `GET /verified-full/analysis.json`)
  registered *before* their corresponding `StaticFiles` mounts, so they take routing priority
  for exactly that one filename. Each reads the file directly and returns
  `Content-Type: application/json; charset=utf-8` with no `Content-Disposition` header ever,
  independent of the host OS's `mimetypes` registry (Starlette's default `StaticFiles` never set
  an attachment header here either -- verified by reading `starlette/staticfiles.py`/
  `responses.py` -- but the dedicated route makes the guarantee explicit and testable rather
  than incidental). `run_name` path traversal is blocked via `Path.resolve()` +
  `is_relative_to(RESULTS_ROOT)`; this is not a generic arbitrary-file endpoint -- it only ever
  serves a file literally named `analysis.json` under the existing results/verified-full
  locations. JSON bytes are read and returned unmodified. Verified live via `curl -D -` against
  both routes after rebuilding and restarting the app: `content-type: application/json;
  charset=utf-8`, no `content-disposition`, correct byte counts.
- **Technical Report target -- investigated, not guessed**: confirmed by grepping the served
  artifact that `/verified-full/report.html` (linked from the home page and from every
  generated report's "View Detailed Report") is **the preserved static verified artifact**,
  not a freshly rendered page -- it still said `<title>Robustness report | Team Checkmate</title>`
  and had zero `home-link` occurrences, meaning it predated even the V3 session's nav/title
  changes, despite `HANDOFF.md` recording it as regenerated in V4. Per the brief: did not
  re-run the benchmark, did not touch `analysis.json`'s data, and did not alter the original
  `report.pdf`. Instead, re-rendered *only* `report.html` from the exact same, byte-verified
  `artifacts/verified_full_report/analysis.json` (SHA-256 confirmed identical to
  `results/repro_1/report/analysis.json`, the original verified run) through the *current*
  `report.generate.render_html(mode="full")`, then updated only the `report.html` entry in
  `export_meta.json` to the new file's hash (confirmed: `analysis.json` and `report.pdf`
  hashes in that file are unchanged, and `report.pdf`'s actual SHA-256 was verified unchanged
  before and after). The regenerated page now shows the current Red Lab identity (compact
  identity line, `page-title`, V1/V2 pills, Home link, current partial-banner/category-table
  CSS) and has zero occurrences of "Robustness" or a `download`-attributed Source JSON link.
  This is a "smallest safe adjustment," per the brief's explicit allowance to re-render a view
  from preserved verified evidence without touching the evidence itself. V5.3's full
  restructuring (sidebar, book navigation) was explicitly not done here.
- **Timing promise removed**: `web/templates/index.html`'s CTA caption changed from "Takes
  under a minute. Runs entirely inside this container." to "Executes a real curated attack
  subset inside this container." No duration claim anywhere on the page now.
- **Red Lab identity cleanup (review)**: grepped `web/static/app.css` and `report/style.css`
  for decorative teal/green remnants. `web/static/app.css` has none (confirmed clean before
  this session, from V5.1's first pass). `report/style.css` keeps the `--teal`/`--coral`
  variable *names* (a deliberate V5.1 decision to avoid a risky full rewrite of a heavily-tuned
  stylesheet) but every remaining usage found (`.v1-dot`/`.v2-dot`, `.bar.v1`/`.bar.v2`,
  `.badge.v1`/`.badge.v2`, `.drift-panel .big-stat`, `.denominator`) is semantically tied to
  V1 (danger/red) or V2 (success/green), not decorative branding -- no further changes made,
  since the brief explicitly says not to blindly replace every green value.
- **Mobile responsiveness**: reviewed after the above changes; the new demo category-table
  markup reuses the exact classes (`.rate-label`, `.bar-track`, `.category-table`) the existing
  760px media query in `report/style.css` already makes responsive for the full report, so no
  new mobile CSS was needed. `web/static/app.css`'s hamburger nav, `aria-expanded` toggling, and
  responsive hero were not touched by this session's changes (only color values changed, via
  the dark-mode-block removal) and were not re-broken -- existing mobile-menu tests still pass.
- **Tests**: added 3 tests to `tests/test_report.py` (partial-banner is no longer a mustard
  panel with only a CSS-token check, not a screenshot; demo category table has the V1/V2
  legend + header text + one `bar-track` per V1/V2 cell; a modified fixture proves the bar
  width and displayed percent/count stay in sync and data-derived) and 7 to `tests/test_web.py`
  (no timing promise on the home page; `/static/app.css` has no
  `prefers-color-scheme` media query; the Red Lab CSS tokens are still served; the new
  `/results/.../analysis.json` route returns `application/json; charset=utf-8` with no
  `content-disposition`; the same route blocks a `..` path-traversal attempt and returns 404
  without leaking a sibling file's content; a missing run returns 404 without a
  content-disposition header; `/verified-full/analysis.json` returns the same clean headers).
  Full suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **463 passed** (453 at session start + 10 new), 1 pre-existing Starlette/AnyIO warning.
- **Real local acceptance test** (not mocked): started `uvicorn web.app:app` on `127.0.0.1:7860`
  against this checkout, ran one real demo experiment via `POST /api/run` (`run_all.run_experiment
  (mode="demo", ...)`, genuine V1/V2 uvicorn processes, completed in ~22s), then verified over
  real HTTP with `curl`: `GET /` 200 with the timing promise absent and the new CTA copy
  present; `GET /healthz` 200; `GET .../report.html` 200 `text/html; charset=utf-8`;
  `GET .../analysis.json` 200 `application/json; charset=utf-8`, no `content-disposition`
  (both via the new dedicated route); `GET .../report.pdf` 200 `application/pdf`; the served
  report's "View Detailed Report" link and its target both returned 200; `GET
  /verified-full/report.html` has zero occurrences of "Robustness" or a downloadable Source
  JSON link; `GET /verified-full/analysis.json` 200 with the same clean headers. Confirmed via
  `netstat` that ports 8000/8001 had no `LISTENING` socket after the run finished, matching
  every prior session's verification; the throwaway `results/hf_demo_*` directories this
  produced were deleted afterward (gitignored regardless). The web app process itself was
  stopped after verification (`taskkill`), confirmed off port 7860.
- **Docker**: rebuilt `team-checkmate-v5-redlab:latest` from the same `Dockerfile` (untouched
  this session). All four expensive layers (`apt-get`, `COPY requirements.txt .`,
  `pip install`, the pinned-model-revision pre-download) reported `CACHED`; only `COPY . .`
  and the final `useradd`/`chown` layer re-ran, as expected for a source-only change. Ran the
  freshly built image (`docker run -d -p 7862:7860 ...`), confirmed `/healthz` and `/` both
  return 200, then removed the container (`docker rm -f`). Did not run a second full live-demo
  smoke test through the container this session (the local, non-Docker real demo run above plus
  the full test suite were judged sufficient per the brief's "optional" wording for this step);
  the image itself was left built. The pre-existing `team-checkmate-v4:latest` image was not
  touched.
- **Files changed this session** (on top of the prior V5.1 checkpoint below, same branch, still
  entirely local): `web/static/app.css`, `report/style.css`, `report/demo_template.html`,
  `web/templates/index.html`, `web/app.py`, `tests/test_report.py`, `tests/test_web.py`,
  `artifacts/verified_full_report/report.html` (re-rendered view only),
  `artifacts/verified_full_report/export_meta.json` (one hash field updated to match). No
  change to `contract.py`, attack/runner/analysis code, `endpoint/v1.py` or `endpoint/v2.py`,
  severity/remediation logic, or `results/repro_1`'s original `analysis.json`
  (byte-for-byte confirmed unchanged; `artifacts/verified_full_report/analysis.json` and
  `report.pdf` likewise confirmed byte-for-byte unchanged by hash before/after).
  `git diff --check`: clean (only pre-existing LF/CRLF warnings).
- **Not done / explicitly out of scope**: V5.2 (full-screen live-demo execution UX), V5.3
  (technical-report restructuring, dedicated V1-left/V2-right layout, interactive-book sidebar),
  V5.4 (Try Your Own Input), V5.5 (final integration/hardening/responsive acceptance pass),
  V5.6 (Hugging Face deployment/public visibility). No push to GitHub `origin` or the `space`
  Hugging Face remote (both remotes were only inspected via `git remote -v`/`git branch -vv`,
  never written to). No merge to `main`.
- **Commit**: confirmed `ahsan/v5-redlab` at `54e428a` has no upstream tracking ref (unlike
  `ahsan/report`/`main`/`runner-amin`, which do) -- i.e. not pushed anywhere -- before amending
  this checkpoint's changes into that same commit. New HEAD hash is recorded in this session's
  final chat report to Ahsan (not duplicated here to avoid this file going stale the moment a
  future session amends again).
- Next: Ahsan re-reviews in a real browser (including the regenerated Technical Report and the
  demo category-comparison table on both desktop and mobile widths), then decides whether to
  push `ahsan/v5-redlab` to `origin` and/or proceed to V5.2.

## System V5.1 checkpoint - Claude (Red Lab brand + design system + nav foundation)

- Updated: 2026-09-10T05:25:00+04:00, Claude Code; branch `ahsan/v5-redlab`, observed HEAD
  `bba3a7b` at session start (System V4, tagged `v4.0.0` -- untouched, unmoved this session).
  A local commit is created at the end of this checkpoint; it is **not** pushed anywhere.
- Scope: this is V5.1 only -- Red Lab branding, a shared design-token system, responsive
  navigation, naming cleanup ("Run Live Attack Test" -> "Run Live Demo"), and consistent page
  identity across the web app and both generated reports. Explicitly deferred: the V5
  custom-input engine, the full-screen live-demo UX (V5.2), the technical report's collapsible
  sidebar restructuring (V5.3), "Try Your Own Input" (V5.4), final responsive/hardening pass
  (V5.5), and Hugging Face deployment / Space visibility (V5.6) -- none of that was touched.
  No push to Hugging Face, no merge to `main`, no edits to `contract.py`, attack definitions,
  runner semantics, analysis thresholds, severity logic, the model, or its pinned revision.
- Real Red Lab logo: `Red Lab Adversarial Testing Redefined.png` (1254x1254 PNG, supplied by
  Ahsan directly into the repo root before this session) is read verbatim and embedded as a
  `data:` URI on the home page, the same pattern already used for the Team Checkmate logo --
  neither logo was recreated, redrawn, or resized destructively (both keep their real aspect
  ratio; display size is controlled by CSS `height`/`width`/`object-fit: contain` only).
  `web/app.py` gained `_red_lab_logo_data_uri()` (a `_data_uri(path, label)` helper shared with
  the existing Team Checkmate one) which raises `RuntimeError` naming the expected path if the
  asset is ever missing, matching the existing "stop and report, never substitute a
  placeholder" convention. The old "C." placeholder mark is gone from both report templates
  (replaced by the real embedded Team Checkmate logo `<img>`, done in the prior V3 session) and
  was never used on the web app at all.
- Design tokens: added the exact token set the brief specified (`--rl-red #b4232f`,
  `--rl-charcoal #17191d`, `--rl-paper #f5f2ea`, `--rl-surface #fffdfc`, `--rl-muted #667078`,
  `--rl-border #d8d2c8`, plus `--rl-success #2e7d4f`, `--rl-warning #9a6b12`, `--rl-danger`
  same value as `--rl-red`) to **both** `report/style.css` and `web/static/app.css`, defined
  identically so the web app and generated reports read as one product. `web/static/app.css`
  was rewritten directly onto the new tokens (it is small and entirely owned by V4/V5, so no
  legacy names were worth preserving). `report/style.css` is large and has been tuned across
  several prior sessions (print pagination, exact severity-badge colors, etc.), so there
  `--ink`/`--muted`/`--paper`/`--line` became straight aliases to the new tokens (each only
  ever meant one thing) and the old `--teal`/`--coral` variables -- which used to do double
  duty as both "general brand accent" and "V1-vs-V2 semantic color" -- were kept as names but
  repointed (`--teal` -> `--rl-success`, `--coral` -> `--rl-danger`) with the handful of
  general-brand-accent usages (links, the hero accent word, button hover, the audit-appendix
  expand links) individually overridden to `--rl-red` directly so they don't turn green under
  the new mapping. Net effect verified by grep: `web/static/app.css` now has zero occurrences
  of "teal"; `report/style.css` keeps the variable *names* `--teal`/`--coral` (avoiding a large
  risky rewrite of a heavily-tuned stylesheet) but the literal teal hex color is gone from
  everywhere it renders -- V1/V2 dots, bars and badges now read danger-red/success-green
  (matching their actual meaning: V1 unhardened = at-risk, V2 hardened = mitigated), and the
  demo report's partial-suite banner moved from a repurposed "V1-danger" red to
  `--rl-warning` amber, which is the actually-correct semantic for a "partial suite, read with
  caution" notice.
- Single source of truth for product strings: `report/generate.py` gained
  `CREATOR_NAME = "Team Checkmate"`, `PRODUCT_NAME = "RED LAB"`,
  `PRODUCT_TAGLINE = "Adversarial Testing Redefined"`, `PRODUCT_VERSION_LABEL = "Red Lab
  v5.0"`; `web/app.py` imports these same four constants rather than redeclaring them, so the
  version label can never drift between the web app and the two report templates.
- Home page (`web/templates/index.html` + `web/static/app.css`): full redesign. Masthead now
  shows Team Checkmate (logo + name) and "Red Lab v5.0" plus a responsive nav
  (Home -> `/`, Live Demo -> `#run` anchor on the CTA row, Technical Report -> the verified
  full report, `target="_blank"`) that collapses into a compact toggle button below 760px
  (`web/static/app.js` toggles a `.open` class and `aria-expanded`, closing on link click).
  Hero shows the brand hierarchy the brief specified (Team Checkmate small/above, RED LAB as
  the large wordmark, tagline below) next to the large, responsive Red Lab logo (120px desktop,
  76px mobile -- deliberately not a tiny icon), the concise explanation paragraph from the
  brief (used near-verbatim), and both CTAs: primary "Run Live Demo" (renamed from "Run Live
  Attack Test" everywhere user-facing, including the JS failure/reset fallback text -- internal
  `run_experiment(mode="demo", ...)` naming was not touched, per the brief's explicit
  instruction not to rename internal functionality for presentation), secondary "View Technical
  Report" next to it. The CTA row is a plain flex container so a third button (V5.4's "Try Your
  Own Input") can be added later without restructuring the hero -- no non-functional button was
  added now. "Try Your Own Input" is not exposed anywhere.
- Page identity on internal pages: both report templates (`report/demo_template.html`,
  `report/template.html`) had their large marketing hero replaced with the compact pattern the
  brief specified -- a small `Team Checkmate / Red Lab v5.0` identity line, then a functional
  `<h1 class="page-title">` ("LIVE DEMO RESULTS" / "TECHNICAL REPORT", ~40px, not 76px), then
  V1/V2 identified explicitly as colored pills ("V1 -- Unhardened Endpoint" danger-red,
  "V2 -- Hardened Endpoint" success-green). The demo report's old "Robustness, live." and the
  full report's old "Robustness under pressure." are both gone; neither template contains the
  word "Robustness" anymore (verified by test and by grepping a real generated report). The
  tagline itself ("Adversarial Testing Redefined") was deliberately NOT repeated on these pages,
  per the brief's "only the home page heavily features the tagline" instruction -- it appears
  in the footer's small provenance line as part of the product name, not as hero copy.
- Global navigation: both report templates gained a `.home-link` nav item ("&larr; Back to Red
  Lab", `href="/"`) in their existing masthead nav, alongside the demo report's existing
  Demo/Results/Method anchors and the full report's existing Results/Findings/Method anchors
  (neither set of section anchors was removed or restructured -- V5.3 owns that). The same link
  (plus a second copy) was added to each template's footer. This link is root-relative (`/`):
  it resolves correctly when the report is served through the web app's `/results/...` mount
  (the primary distribution path now) and is a graceful no-op rather than a crash when a report
  is opened as a standalone local file with no server behind `/` -- documented as a known,
  accepted limitation of the dual offline-file/web-served distribution model, not something
  V5.1 was asked to solve.
- Source JSON: both templates' masthead "Source JSON" link, and the equivalent inline
  `analysis.json`/`export_meta.json` links in each report's Source/provenance section, dropped
  the `download` attribute and gained `target="_blank" rel="noopener"` -- opens the JSON in a
  new tab instead of forcing a save-as dialog. The JSON content/bytes themselves are completely
  unchanged (this is a rendering-attribute change only, nothing in `report/generate.py`'s
  actual JSON serialization was touched). No custom JSON viewer was added (out of scope, not
  justified as trivial).
- Crash-gap warning de-emphasis carried over correctly: `demo_evidence.crash_status_note` (a
  V3-era field) still renders as a small `<p class="caption crash-note">` inside the featured
  failure card, not a prominent banner; `literal_crash_case_available` is untouched in the
  underlying JSON; the featured-failure interpretation text and the Method section's explicit
  crash/unavailability caveat are both unchanged. Verified again this session against a real
  generated report (see below).
- Full test suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest
  -q`: **453 passed** (445 at session start + 8 new: 4 in `tests/test_report.py` covering
  Home-link/Source-JSON-new-tab/Team-Checkmate-credit-and-Red-Lab-version, one existing test
  rewritten for the new demo hero copy; 5 in `tests/test_web.py` covering the Red Lab version
  label, nav links, mobile-menu toggle markup, technical-report new-tab attributes, and the
  rewritten branded-welcome-page test asserting the OLD wording is gone, not just that new
  wording is present). No test in `tests/test_run_all.py`, `tests/test_analysis.py`,
  `tests/test_runner.py`, `tests/test_endpoint.py`, `tests/test_attacks.py`, or
  `tests/test_baseline.py` was touched -- none of that code changed.
- Live verification (real run, not synthetic fixtures): started the actual web app locally
  (`uvicorn web.app:app`, outside Docker) and drove a real `POST /api/run` -> a genuine
  `run_experiment(mode="demo", ...)` against real local V1/V2 endpoints, completed in ~29s.
  Fetched the actual generated `report.html` over HTTP and grep-verified, against the real
  file (not a template render in isolation): the embedded logo, "LIVE DEMO RESULTS" heading,
  both V1/V2 endpoint-identity pills, the Home-link back to Red Lab, "Red Lab v5.0", the
  complete absence of "Robustness" and "in one minute", Source JSON's new-tab attributes, the
  sticky-masthead CSS rule, and the de-emphasized crash note -- all eleven checks passed
  against real output. Both endpoints' ports (8000/8001) and the web app's port (7860) were
  confirmed free again afterward; the throwaway `results/hf_demo_*` run directory was deleted
  (gitignored, not committed regardless).
- Docker: rebuilt with `docker build -t team-checkmate-v5-redlab:latest .` (tagged separately
  from the existing `team-checkmate-v4:latest` image, which was left untouched). **All four
  expensive layers reported `CACHED`**: apt-get (Pango/Harfbuzz), `pip install`, and the
  pinned-model-revision pre-download -- only `COPY . .` (0.1s) and the final `useradd`/`chown`
  layer re-ran, exactly the caching behavior the Dockerfile's layer ordering is designed for.
  Ran a real container (`docker run -d -p 7861:7860 team-checkmate-v5-redlab:latest`), waited
  for `/healthz`, then drove one real live demo run through it end-to-end via `POST /api/run`
  (completed in ~19s, `status: complete` with a real `result_url`) -- a short smoke test, not
  the full 1,928-case benchmark. Container removed afterward (`docker rm -f`); the image itself
  was left built. Docker Desktop had to be started fresh this session (it was not running); no
  other Docker state on the machine was touched.
- Not done / explicitly out of scope this session: V5.2 (full-screen live-demo UX transition),
  V5.3 (technical-report restructuring + the complete collapsible interactive-book sidebar --
  V5.1 only added a single Home nav link, not a sidebar), V5.4 (the custom-input engine / "Try
  Your Own Input"), V5.5 (final integration/hardening pass), V5.6 (Hugging Face deployment /
  flipping the Space to Public). The Hugging Face Space itself was not touched or pushed to.
- Files changed (all on `ahsan/v5-redlab`, nothing on `main`, nothing pushed): `report/
  generate.py`, `report/style.css`, `report/template.html`, `report/demo_template.html`,
  `web/app.py`, `web/static/app.css`, `web/static/app.js`, `web/templates/index.html`,
  `tests/test_report.py`, `tests/test_web.py`. `Red Lab Adversarial Testing Redefined.png`
  (new, supplied by Ahsan) is untracked in git, same status as `Team Checkmate Logo.png` has
  had since V3/V4 -- neither logo has been `git add`ed by any session; that decision is left
  to Ahsan. A local commit for this checkpoint follows immediately after this entry, per the
  explicit instruction to commit locally but not push.
- Next: Ahsan reviews the diff and the live app (desktop + mobile viewport) before deciding on
  V5.2. `git log` on `ahsan/v5-redlab` will show this commit ahead of `bba3a7b`; `v4.0.0`
  remains recoverable and unmoved at `bba3a7b` for comparison/rollback.

## System V4 Docker validation + pre-Hugging-Face freeze checkpoint - Claude

- Updated: 2026-09-10T03:35:00+04:00, Claude Code; branch `ahsan/report`, observed HEAD
  `c507033` (unchanged prior to this session's commit; see the commit recorded below).
- Ahsan manually completed the first real Docker verification (build + run + full manual
  walkthrough of the welcome page, live demo, generated report, source JSON/PDF, and the
  verified full report -- all confirmed by Ahsan). This session's task: reorder the
  Dockerfile for build-cache efficiency, re-validate with Docker Desktop (now installed
  and running), scan the repo for secrets/machine paths before any Hugging Face upload,
  check Git remotes, and produce one clean local commit of the validated V3+V4 state.
  Explicitly not authorized to push anywhere (GitHub or Hugging Face) this session.
- Dockerfile reordered (smallest change, no logic/dependency/model changes): `COPY . .`
  moved to AFTER the pinned-model download step, so the order is now
  apt packages -> `COPY requirements.txt .` -> `pip install` -> ENV -> pinned model/
  tokenizer download -> `COPY . .` -> non-root user/chown -> healthcheck/CMD. The
  `useradd`/`mkdir /app/results`/`chown -R` step, previously before `COPY . .`, now runs
  after it (chowns the freshly copied source too) -- the only other change, needed
  because reordering the copy changes what needs chowning. Model name/revision, pinned
  dependency versions, V1/V2 semantics, attack/runner/analysis/report code and
  `contract.py` are all untouched.
- Docker Desktop discovered at a non-standard, per-user install path (`C:\Users\ahsan\
  AppData\Local\Programs\DockerDesktop\resources\bin\`), not on this shell's PATH by
  default; `docker-credential-desktop.exe` (needed for registry auth) lives in the same
  directory. Both `docker.exe` and that directory had to be referenced/added to PATH
  explicitly for this session's PowerShell commands to work -- worth knowing for any future
  session on this machine.
- Full test suite re-run before the rebuild:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **445 passed** (unchanged from the V4 session), 1 pre-existing Starlette/AnyIO warning.
- Real `docker build -t team-checkmate-v4 .` against the reordered Dockerfile: succeeded
  (exit 0). Confirmed from the build's own step-by-step output (not inferred): steps
  2-5 (apt packages, `WORKDIR`, `COPY requirements.txt .`, `pip install`) all hit
  `CACHED` against Ahsan's own prior manual build, since those layers are unchanged;
  step 6 (pinned model/tokenizer download) ran for real (468.2s, ending with the expected
  `model cached at pinned revision` line) because its position in the layer graph changed;
  step 7 (`COPY . .`) then completed in 0.1s; step 8 (`useradd`/chown) in 1.2s. This is
  direct evidence the reorder achieves its goal: an ordinary source-only change would now
  invalidate only steps 7-8, never the expensive dependency-install or model-download
  layers.
- Ran the freshly built image as a detached container
  (`docker run -d --name team-checkmate-v4-test -p 7860:7860 team-checkmate-v4`) and
  smoke-tested it for real, inside the container, not mocked: `GET /` 200 with the real
  logo `data:` URI and "Run Live Attack Test" present; `GET /healthz` 200; `GET
  /verified-full/report.html` 200 (the existing V3 verified artifact, unmodified);
  `GET /static/app.css` 200; one real `POST /api/run` demo experiment -- genuine V1/V2
  uvicorn processes started inside the container, the curated attack subset sent, real
  analysis and report generation -- completed in ~19s with the documented stage sequence
  observed live via `/api/status` polling; the resulting `report.html`, `analysis.json`,
  `report.pdf`, and the copied `detailed/report.html` (verified full report) all returned
  200 through the container's `/results/...` mount, and the served report.html contains
  the "View Detailed Report" link. Checked for V1/V2 cleanup via `docker exec ... cat
  /proc/net/tcp` (no `ps` binary in the slim image): only one `LISTEN` (0x1EB4 = 7860, the
  web app) and `TIME_WAIT` remnants on 0x1F40/0x1F41 (8000/8001) -- no lingering V1/V2
  listener after the run, matching the host-level verification from the prior session.
  Did **not** run the full 1,928-case benchmark (per instruction). Container then stopped
  and removed (`docker stop`/`docker rm team-checkmate-v4-test`, confirmed gone via
  `docker ps -a`); the throwaway `results/hf_demo_20260909_232412_2fef5e/` directory this
  produced was deleted (nothing else under `results/` touched). The `team-checkmate-v4`
  image itself was left in the local Docker image cache (not requested to be removed).
- Repository-state and secret/path scan before commit: `git status --short`, `git diff
  --stat`, and `git diff --check` all match the expected V3+V4 file set with only
  pre-existing LF/CRLF warnings (no whitespace errors). Scanned every tracked-or-untracked-
  non-ignored file (`git ls-files --cached --others --exclude-standard`) for HF-token-
  shaped strings (`hf_[A-Za-z0-9]{20,}`), AWS-key-shaped strings, PEM private-key headers,
  and generic `api_key=`/`secret=`/`password=` patterns: zero matches. No `.env` file
  anywhere in that same file set. Grepped the new/changed deployment files (`Dockerfile`,
  `.dockerignore`, `web/`, `run_all.py`, `README.md`, `HANDOFF.md`) for Windows absolute
  paths (`C:\Users`/`C:/Users`): the only hits were inside `web/__pycache__/*.pyc`
  (compiled bytecode embedding this machine's build path), confirmed gitignored via
  `git check-ignore -v` and absent from `git status` -- they will never be committed.
  Confirmed present and untouched: `contract.py` (no diff), `Team Checkmate Logo.png`
  (167,449 bytes), and all four files under `artifacts/verified_full_report/` (the
  existing verified full report from the V3 session, not regenerated). Confirmed
  `results/` remains fully gitignored (`git check-ignore -v results/`), so no run output
  from any of this session's live demo runs was ever a candidate for committing.
- Git remotes: only `origin` exists, pointing to
  `https://github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate.git` (both
  fetch and push). No Hugging Face remote was added this session -- Ahsan's instruction
  was to prepare the repo (Dockerfile + README Space front matter, already done in the V4
  session) and stop before pushing anywhere. The existing GitHub remote was not touched.
- Committed (not pushed): all of this session's V4 changes plus the still-uncommitted V3
  session's work, together, as one commit -- see the commit hash recorded in the final
  report given to Ahsan in chat. No `--no-verify`, no amend of history predating this
  session.
- Not done / explicitly out of scope per this task: no push to GitHub or Hugging Face
  (stopped as instructed), no V5 work, no redesign, no new branding. No fresh 1,928-case
  full benchmark was run. Docker Desktop's discovered non-standard install path (above)
  may need to be added to this machine's persistent PATH if a future session should not
  have to rediscover it.
- Next: Ahsan reviews the commit, decides when to push to GitHub `origin`, and separately
  creates/authenticates the Hugging Face Space remote (`ahsan-141117/team-checkmate-
  adversarial-redteam-toolkit`, a protected Docker Space) using their own credentials --
  this session deliberately did not request, store, or handle any Hugging Face token. See
  the final report in chat for the exact recommended command sequence for that push.

## System V4 checkpoint - Claude

- Updated: 2026-09-10T02:35:00+04:00, Claude Code; branch `ahsan/report`, observed HEAD
  `c507033` (unchanged; nothing committed this session).
- Ahsan (the user) assigned System V4: Hugging Face Docker deployment as a thin web layer
  around the existing, validated V1-V3 pipeline. Explicit constraints: reuse
  `run_experiment()` in-process (never shell out to `run_all.py`), no Gradio/Streamlit/
  React/Node/Redis/Celery/database, single uvicorn worker with an in-process job lock, no
  fresh 1,928-case benchmark. Not authorized to commit/push.
- New `web/` package (not owned by any existing component folder per AGENTS.md's
  ownership table -- root-level orchestration/deployment, same status as `run_all.py`):
  `web/app.py` (FastAPI app), `web/templates/index.html` (welcome page), `web/static/
  app.css`, `web/static/app.js`. No attack/runner/analysis/report logic duplicated --
  `web/app.py` imports `run_all` and calls `run_all.run_experiment(mode="demo", ...)`
  directly from a background `threading.Thread`.
- `run_all.py` changes (smallest reasonable, per the brief): added `_emit_progress(callback,
  stage, message)` and an optional `progress_callback=None` parameter on both
  `run_experiment()` and `run_analysis_and_report()`. Emits exactly the eight required
  real-transition stages (`initializing, starting_v1, attacking_v1, starting_v2,
  attacking_v2, analyzing, generating_results, complete`) at the locations the brief
  specified -- verified by reading each call site, not just by test. Every existing caller
  (the CLI, prior tests) omits the callback and is unaffected; confirmed by running the
  pre-existing `tests/test_run_all.py` suite unchanged in behavior plus new tests added
  alongside it.
- Job manager (`web/app.py`): module-level dict guarded by one `threading.Lock`.
  `POST /api/run` returns the *current* active job (202, same `run_name`) if one is
  already `running` instead of starting a second `run_experiment()` -- verified with a
  real concurrent double-POST against a live background run (see below), not just mocks.
  Run names are server-generated only (`hf_demo_<UTC timestamp>_<6 hex chars>`); the
  public API accepts no path, mode, or run-name input from the client anywhere. A failed
  job (`_run_job`'s broad `except Exception`) is logged server-side via
  `logging.exception` and exposes only a fixed public message, never a traceback or
  exception text, to `/api/status`.
- Result serving: `/results` is mounted as `StaticFiles(directory=run_all.RESULTS_ROOT)`
  (created if missing at import time); on completion the job stores
  `result_url = "/results/<relative report.html path>"`, computed via
  `Path.relative_to`, so it is portable inside Docker/Hugging Face with no absolute or
  Windows path ever exposed. `/verified-full` is mounted from
  `run_all.VERIFIED_FULL_REPORT_DIR` (`artifacts/verified_full_report/`, already
  untracked-but-present from the V3 session) only if that directory exists, matching the
  existing "View Detailed Report" guard pattern in the demo template -- no new full
  1,928-case run was executed to produce it; the already-verified V3 artifact is reused
  as-is. `/healthz` only returns a static liveness payload; it never starts V1/V2.
- Welcome page (`web/templates/index.html` + `web/static/app.css`): real logo via a
  same-pattern `_logo_data_uri()` in `web/app.py` (reads `Team Checkmate Logo.png` at the
  repo root directly, not importing report/generate.py's private helper), rendered at
  64px (vs the report masthead's 30px) using the same CSS custom-property palette as
  `report/style.css` (`--ink/--muted/--paper/--line/--teal/--coral`) for visual
  consistency, with its own responsive stylesheet (not shared with the report bundle).
  Hero copy matches V3: "Robustness, live." Nav has a single secondary "View Detailed
  Report" link (hidden if the verified artifact is absent). `/api/status` is polled once
  on page load specifically so a second visitor arriving mid-run sees live progress
  instead of the idle welcome state -- confirmed structurally (`web/static/app.js`'s
  initial fetch) and live (see below).
- Progress UI: real stage list + a progress bar mapped to the brief's suggested
  stage-boundary percentages (5/15/30/50/65/82/92/100), advanced only on actual
  `/api/status` stage changes via 1.5s polling -- no fake continuous animation. On
  `status: complete`, the client redirects to `result_url` (the real generated demo
  report, not a separately rebuilt JS results view).
- Dockerfile (root): `python:3.11-slim-bookworm`, installs only `libpango-1.0-0`,
  `libpangoft2-1.0-0`, `libharfbuzz-subset0` (no GTK/desktop set) for WeasyPrint, installs
  `requirements.txt` unmodified/unpinned-upgraded, pre-downloads the pinned model/tokenizer
  revision (`j-hartmann/emotion-english-distilroberta-base` @
  `0e1cd914e3d46199ed785853e12b57304e04178b`, same constants as `endpoint/model.py`) at
  build time while network is available, then sets `HF_HUB_OFFLINE=1`/
  `TRANSFORMERS_OFFLINE=1` for runtime so the container never depends on network access to
  load the model. Creates uid-1000 `user`, chowns `/app` after the model download, runs as
  that non-root user. `HEALTHCHECK` uses `urllib.request` (no `curl` dependency) against
  `/healthz`. Final `CMD` is exactly `uvicorn web.app:app --host 0.0.0.0 --port 7860` with
  no `--workers` flag (defaults to one). `.dockerignore` excludes `.git/.venv/__pycache__/
  results/` etc. but does not touch `artifacts/`, the logo, `contract.py`, or any
  component folder.
- README.md: added Hugging Face Space YAML front matter (`sdk: docker`, `app_port: 7860`,
  the project title/emoji) at the very top, ahead of the existing substantive README
  content (not replaced), plus a new "Deployment (System V4)" section with the local-
  uvicorn and Docker-build/run commands. No other README content removed.
- Tests: `tests/test_run_all.py` gained 3 tests (existing callers unaffected by the new
  optional parameter; the full 8-stage sequence emitted by `run_experiment()` in the
  documented order; `run_analysis_and_report()` itself emits exactly `analyzing` then
  `generating_results`, verified against the real function with only its analysis/report
  collaborators mocked, not the function itself). New `tests/test_web.py` (9 tests, all
  mocking `run_all.run_experiment` -- no real ML experiment runs in the unit suite):
  branded welcome page incl. the real logo `data:` URI, `/healthz`, idle initial status,
  202 running state on start, a second concurrent POST returning the *same* job (asserted
  via a call-count of 1 against a real background thread blocked on a `threading.Event`,
  not just state inspection), real progress-callback stages reaching `/api/status`,
  successful completion exposing a portable `result_url`, a failed job exposing a safe
  message with the original exception text/paths asserted absent, and a fresh run being
  allowed after the previous one completes. Full suite:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **445 passed** (433 before this session + 12 new), 1 pre-existing Starlette/AnyIO
  warning, unrelated to this change.
- Live verification without Docker (Docker Desktop/CLI is not installed on this machine --
  confirmed via both the Bash tool and PowerShell; `docker`/`docker version` resolve to
  "command not found" in both, so the Docker-specific steps below could not be run here):
  started `uvicorn web.app:app` locally on `127.0.0.1:7860` against this checkout
  (no container). Verified live, for real, not mocked: `GET /` 200 with the real logo
  `data:` URI and "Run Live Attack Test" present; `GET /healthz` 200; `GET /static/app.css`
  200; `GET /verified-full/report.html` 200 (the existing V3 artifact, unmodified); two
  full real `POST /api/run` demo experiments end to end -- each a genuine `run_experiment
  (mode="demo")` starting real V1/V2 uvicorn processes, sending the real curated attack
  subset, analyzing, and generating a report -- both completed in ~18-23s with the exact
  documented stage sequence observed live via repeated `/api/status` polls
  (`initializing -> starting_v1 -> attacking_v1 -> starting_v2 -> attacking_v2 -> analyzing
  -> generating_results -> complete`, percents 5/15/.../100 matching `STAGE_PERCENT`); the
  second POST fired 1s after the first, live, while the first was still `attacking_v1`/
  `starting_v1`, returned the *same* `run_name`, proving the single-active-run lock holds
  against real concurrency, not only mocks; after the second run finished, a fresh POST
  was accepted again (new job allowed post-completion). After the first run's completion,
  `GET` on the served `result_url`, its `analysis.json`, its `detailed/report.html`
  (the copied verified full report), and its `report.pdf` all returned 200; the served
  report.html itself contains the sticky `.masthead` and the real "View Detailed Report"
  link, confirming the V3 report experience travels through the web layer unchanged.
  After each run, confirmed via `netstat` that ports 8000/8001 had no LISTENING socket
  (only expected `TIME_WAIT` remnants) while 7860 remained up -- endpoint cleanup held
  under real concurrency exactly as `run_experiment()`'s existing `try/finally` already
  guaranteed. The local `uvicorn` process was then stopped and confirmed off port 7860;
  the two throwaway `results/hf_demo_*` directories this produced were deleted (nothing
  else under `results/` was touched). `git diff --check`: clean (only pre-existing
  LF/CRLF warnings, no whitespace errors).
- Not done / explicitly out of scope or blocked: **the actual `docker build`/`docker run`
  steps (System V4 section 21) were not performed -- Docker is not installed on this
  machine.** Everything Docker-independent was verified as above (same code path the
  container would run, since `web/app.py` and `run_all.py` have no Docker-specific
  branching), but the Dockerfile itself (apt package availability on `python:3.11-slim-
  bookworm`, the build succeeding, the image's non-root user/permissions, the
  `HEALTHCHECK` actually passing under Docker) is unverified and is the single biggest
  remaining risk before an actual Hugging Face Space upload. No fresh 1,928-case full
  benchmark was run (per instruction). Nothing committed or pushed. Working tree now also
  has `Dockerfile`, `.dockerignore`, `web/` (new) and this file plus `README.md` modified,
  on top of the prior V3 session's uncommitted work (`run_all.py`, `report/*`,
  `artifacts/verified_full_report/`, `Team Checkmate Logo.png`, etc. -- all still
  uncommitted, still pending Ahsan's review per the V3 checkpoint below).
- Next: Ahsan reviews the diff; if a Docker Desktop/Engine is available on some machine,
  run `docker build -t team-checkmate-v4 .` then `docker run --rm -p 7860:7860
  team-checkmate-v4` and repeat the section-21 checklist against `http://localhost:7860`
  to close the one unverified item above, then decide when to commit/push and whether to
  proceed to an actual Hugging Face Space upload.

## System V3 checkpoint - Claude

- Updated: 2026-09-10T00:10:00+04:00, Claude Code; branch `main`, observed HEAD `c507033`
  (unchanged; nothing committed this session).
- Ahsan (the user) assigned System V3: real logo, sticky navbar, de-emphasized crash-gap
  warning, demo-only exclusion of `malformed.oversized_10mb` (hardware-timing-sensitive at
  the 10s deadline), a stable "View Detailed Report" link to a canonical verified full
  benchmark, and hero copy fix ("Robustness, live." replacing the unverified "in one minute"
  promise). Not authorized to commit/push. Per explicit instruction, the two 1,928-case full
  reproducibility benchmarks were **not** rerun for this template/CLI-only change.
- Logo: the real `Team Checkmate Logo.png` at the repo root (1024x1024 PNG) is read once and
  embedded as a base64 `data:` URI by `report/generate.py::_logo_data_uri()` (lru-cached),
  used in the masthead of both templates via `<img class="brand-logo">`, replacing the old
  "C." placeholder mark entirely. Verified WeasyPrint's custom `deny_resource` url_fetcher
  (which unconditionally rejects any other fetch -- the report's long-standing "no external
  resources" invariant) does not get invoked for `data:` URIs, so PDF rendering needed no
  changes to that security boundary; only added `img-src data:;` to each template's CSP meta
  tag. This makes the logo travel inside every generated report.html/report.pdf with zero
  relative-path or asset-folder dependency -- confirmed by grepping the actual generated
  `results/v3_demo_check/report/report.html` and its copied `detailed/report.html` for the
  embedded data URI and for the absence of any absolute Windows path. If the source PNG is
  ever missing, `_logo_data_uri()` raises `RuntimeError` naming the expected path rather than
  falling back to a placeholder (verified by test).
- Demo-only exclusion: `run_all.py` gained `DEMO_EXCLUDED_ATTACK_IDS =
  ("malformed.oversized_10mb",)`, passed to the runner as `--skip` (already a supported,
  unrelated-to-scoring runner flag) only when `mode == "demo"`; full mode always passes an
  empty skip list. The attack itself, its registration, its manifest entry, and its presence
  in `--mode full` are untouched -- verified live: `malformed.oversized_10mb` is present in
  the demo run's `manifest.json` and its `run_meta_v1.json` skipped-case list, but absent from
  `results_v1.jsonl`/`results_v2.jsonl`. Demo coverage dropped from 163 to **162** planned
  cases as a direct, fully dynamic consequence (never hardcoded anywhere).
- Crash-gap de-emphasis: `run_all.py::build_demo_evidence` now splits what was one `notes`
  list into `crash_status_note` (the expected, calm "no service unavailability observed"
  explanation -- present every run where `literal_crash_case_available` is false) and
  `notes` (reserved for genuine anomalies: no failure/flip example found). The demo template
  renders `crash_status_note` as a small `<p class="caption crash-note">` folded into the
  featured-failure card, not the large `.notice.warning` box the old "Literal crash/
  unavailability demonstrated: NO" line used. `literal_crash_case_available` itself, and the
  crash/unavailability distinction in the Method section, are unchanged.
- Sticky navbar: `.masthead` is `position: sticky; top: 0; z-index: 20;` with an explicit
  `background: var(--paper)` (shared `report/style.css`, so both templates get it for free);
  `html { scroll-padding-top: 100px; }` (was 24px) keeps every anchor target clear of the bar;
  `@media print { .masthead { position: static; ... } }` neutralizes it for PDF/print, where
  paged media has no persistent viewport anyway.
- Verified full-report artifact: inspected `results/repro_1/` and `results/repro_2/` (both
  already-verified 1928/1928-both-versions, `planned_match`/`manifest_match`/
  `whole_suite_comparable` all true, from the prior session) and picked `repro_1` as the
  canonical source -- both were equally valid, `repro_1` chosen as the first of the two.
  **No new benchmark was run.** Re-rendered (not re-analyzed) its already-validated
  `analysis.json` through the current `report.generate.generate_report(..., mode="full")`
  into a new stable location, `artifacts/verified_full_report/{report.html, report.pdf,
  analysis.json, export_meta.json}` -- this picks up the current template (logo, sticky nav,
  no Demo Highlights) without touching the underlying RunResult/analysis data at all.
- Portable "View Detailed Report" link: `run_all.py::run_analysis_and_report` checks whether
  `artifacts/verified_full_report/report.html` exists *before* rendering (to decide the link's
  visibility/href), embeds `{"available": bool, "relative_href": "detailed/report.html"}` as a
  `detailed_report` key in the report JSON (sibling to `demo_evidence`), then -- only after
  `report.generate.generate_report` has created the fresh `report_dir` (which must not
  pre-exist) -- copies the whole artifact tree into `report_dir / "detailed"`. The demo
  masthead's old "Download PDF" action is now "View Detailed Report" (`target="_blank"
  rel="noopener"`, href `detailed/report.html`); it simply doesn't render if the artifact
  doesn't exist yet on a fresh checkout. The demo's own short PDF still exists at
  `report/report.pdf` (5 pages, unchanged) and Source JSON is untouched.
- Full mode (`report/template.html`): removed the entire "Demo Highlights" section and its
  nav link that the prior session had added there -- per this task's explicit instruction 12,
  full mode is now audit-only again (Results/Findings/Method/Appendix), demo mode owns the
  concrete-example story. `render_html` still receives `demo_evidence` in its context (unused
  by the full template, harmless with Jinja `StrictUndefined`, which only errors on access).
  No page-count number is mentioned anywhere in the UI (per instruction 10); it moved around
  only as a side effect of removing that section (47 pages for the freshly rendered artifact
  vs 49 before, not surfaced to users).
- Verified live, end to end, both runs also confirming reproducible determinism against each
  other: `python run_all.py --mode demo --run-name v3_demo_check` and `--run-name
  v3_demo_noopen --no-open` (both exit 0, identical real results: featured failure
  `malformed.oversized_100kb` V1 500 -> V2 422; featured flip fear 0.618 -> anger 0.842 via
  `homoglyph_greek`, same as the prior session's runs -- oversized_10mb's absence doesn't
  change which example gets featured). Checked directly against the generated files (not
  eyeballed): logo data-URI present exactly once per page including the copied `detailed/`
  copy; old `.mark` placeholder gone from markup; hero reads "Robustness, live." with "in one
  minute" absent; sticky CSS present with print override; nav is Demo/Results/Method with no
  Findings link; downloads show "View Detailed Report" (not "Download PDF") linking to
  `detailed/report.html` with `target="_blank"`; `detailed/report.html` has 43 finding cards,
  the Findings nav link, and no absolute paths; demo PDF 5 pages vs detailed PDF 47 pages
  (WeasyPrint `len(HTML(...).render().pages)`); the real Cyrillic/Greek homoglyph correctly
  wrapped in `<mark class="demo-mark">`; crash-status note renders as a caption, not inside a
  `.notice.warning` box, and the old prominent line is gone; coverage banner reads "162 of
  1,928 planned cases executed" (dynamic, matching the actual reduced count). Could not
  visually confirm the OS actually opened a browser window (no display in this session) --
  verified structurally instead (see the `test_cli_opens_browser_by_default_but_not_with_no_
  open` test and the live `--no-open` run's clean exit with no fallback message).
- Added tests: `tests/test_run_all.py` (new file, 6 tests) covering `run_suite`'s `--skip`/
  `--limit` argv construction, and `run_experiment()` wiring for both modes (mocking the
  endpoint lifecycle and report generation) proving demo mode's skip list is exactly
  `DEMO_EXCLUDED_ATTACK_IDS` and full mode's is empty, and that `run_experiment()` itself
  never calls `webbrowser.open` regardless of mode -- plus a CLI-level test proving `main()`
  calls it exactly when `--no-open` is absent. `tests/test_report.py` gained 8 more V3 tests
  (real logo embedded + placeholder gone in both modes, missing-logo asset raises and is
  restored via `cache_clear()`, sticky/print CSS assertions, hero wording, crash-note
  presentation, genuine-anomaly notes still render as warnings, detailed-report link present/
  absent). One pre-existing test (`test_xss_and_template_syntax_are_plain_text`) needed
  updating: it used to assert zero `<img>` tags anywhere as an XSS-safety check, which the
  new legitimate logo `<img>` now trips; changed to assert exactly one `<img>` tag, that its
  `src` is the trusted `data:image/png;base64,` prefix, and that the injected `file:` payload
  never became a second image. Full suite:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **433 passed** (419 before this session + 14 new), 1 pre-existing Starlette/AnyIO warning.
- Processes: both endpoints started/stopped correctly for `v3_demo_check` and
  `v3_demo_noopen`; confirmed after each run that ports 8000/8001 have no LISTENING socket and
  no stray `python.exe`/`uvicorn` process remains.
- Not done / explicitly out of scope: Docker, Hugging Face, web UI, deployment config. No
  fresh full 1,928-case benchmark was run this session (by instruction). Nothing committed or
  pushed. Working tree now also has `artifacts/verified_full_report/` (new, untracked --
  contains a rendered report/PDF, a decision on whether to commit this is left to Ahsan),
  `report/demo_template.html`, `run_all.py`, `report/generate.py`, `report/style.css`,
  `tests/test_report.py`, `tests/test_run_all.py`, and this file modified/added on top of the
  prior two sessions' uncommitted work. `Team Checkmate Logo.png` itself is also untracked
  (the user added it directly; not touched or modified by this session, only read).
- Next: Ahsan reviews the diff, opens `results/v3_demo_check/report/report.html` in an actual
  browser to visually confirm the sticky nav, logo, and "View Detailed Report" flow, decides
  whether `artifacts/verified_full_report/` and `Team Checkmate Logo.png` should be committed,
  and authorizes commit/push when ready.

## Demo-report polish checkpoint - Claude

- Updated: 2026-09-09T23:30:00+04:00, Claude Code; branch `main`, observed HEAD `c507033`
  (unchanged; nothing committed this session).
- Ahsan (the user) assigned follow-up polish: demo mode's report was structurally the same
  large forensic document as full mode. This task separates presentation by mode while
  reusing the same runner/analysis/report infrastructure and design system, adds CLI browser
  auto-open (CLI-only, never in `run_experiment()`), and `--no-open`. Not authorized to
  commit/push; explicitly told not to rerun the two 1,928-case full experiments for a
  template/CLI-only change, so full mode was verified by regenerating a report from the
  existing real `results/repro_1/report/analysis.json` rather than a fresh benchmark run.
- New `report/demo_template.html`: a single-page judge-facing report. Nav is
  Demo/Results/Method only (no Findings link); downloads keep Source JSON + Download PDF.
  Sections: a coral "LIVE DEMO RUN -- PARTIAL SUITE" banner (actual `X of Y planned cases
  executed` from `versions[0].coverage`, never hardcoded), Demo Highlights (same featured
  failure/flip cards as before, now with the Unicode change visually marked -- see below),
  a compact Demo-subset comparison (resolved/remaining/new tiles, a small operational table,
  the existing compact category table, and "Excluded by demo limit: N cases" sourced from
  `coverage.limit_excluded` with unmatched/unavailable counts shown as numbers only, never
  enumerated), a short Method/Limitations panel, and a condensed Source JSON provenance block.
  No finding-register loop, no audit appendix, no per-case ID listings anywhere in this
  template. `report/generate.py` gained `TEMPLATE_BY_MODE = {"full": "template.html", "demo":
  "demo_template.html"}` and a `mode="full"` parameter on `render_html`/`generate_report`/the
  CLI (`--mode`); both templates read the identical schema-v2 JSON, so no analysis/scoring
  code changed. `report/style.css` (shared by both templates) gained `.partial-banner`,
  `.metrics-row`/`.metric-tile`, and `mark.demo-mark`; nothing existing was renamed or removed.
- Unicode highlight (real data, not fabricated): `run_all.py` gained `highlight_diff_html()`,
  which HTML-escapes both strings via `difflib.SequenceMatcher` opcodes and wraps only the
  differing span(s) in `<mark class="demo-mark">`, once, in Python -- the template renders the
  two resulting fields (`original_html`/`attacked_html`) with Jinja's `safe` filter. Verified
  against a real live demo run: the actual differing pair was `'o'` (U+006F) -> `'ο'` (U+03BF
  GREEK SMALL LETTER OMICRON), both correctly wrapped in the rendered HTML.
- Browser auto-open is CLI-only, per the explicit separation the task required:
  `run_experiment()` in `run_all.py` still only returns a structured result (now including
  `report_html`/`report_pdf` path keys); `webbrowser.open(...)` is called exclusively inside
  `main()`, after `run_experiment()` returns, guarded by a new `--no-open` flag (default:
  open). A failed/unavailable browser controller prints a fallback message and still exits 0;
  it never fails the run. Verified structurally (code path, not a visual screenshot -- this
  session cannot observe an actual window): `--no-open` runs never reach the `webbrowser.open`
  call at all (confirmed by reading the guarded branch), and the without-flag runs hit it with
  no exception and no fallback message printed, meaning `webbrowser.open()` returned truthy.
- Verified live, end to end: `python run_all.py --mode demo --run-name final_demo_check`
  (163/1928 cases both versions, 1,765 limit-excluded, real featured failure
  `malformed.oversized_100kb` V1 500 -> V2 422, real featured flip fear 0.618 -> anger 0.842
  via `homoglyph_greek`) and `--run-name final_demo_noopen --no-open` (exit code 0, identical
  real results, no browser call reached). Both demo reports: nav has exactly Demo/Results/
  Method (no Findings), zero `<article class="finding">` elements, zero `id-list`/
  `audit-details` elements in the document body (those class names exist only in the shared,
  otherwise-unused CSS -- confirmed by checking content after `</style>`), the real Cyrillic/
  Greek homoglyph correctly wrapped in `<mark class="demo-mark">`, "Excluded by demo limit:
  1,765 cases" with no enumerated IDs. Demo PDF: **5 pages** (WeasyPrint `len(HTML(...)
  .render().pages)`, both the live run and a synthetic fixture agree). Full mode, regenerated
  from `results/repro_1/report/analysis.json` (no fresh benchmark run): nav still has
  Findings, 43 finding cards render, 49 pages (was ~46 before this session; the extra pages
  are the Demo Highlights section added in the prior session, unchanged here, not a
  regression -- full mode is otherwise exactly as before).
- Added 7 tests to `tests/test_report.py` (`demo_data` fixture + `demo_evidence_fixture()`)
  covering: demo mode omits the finding register and the id-list, demo nav omits Findings,
  the Unicode `<mark>` renders unescaped while enumerated hidden IDs never appear, full mode
  still renders its finding register/Findings nav link, `render_html` rejects an unknown
  `mode`, and a real-PDF test asserting `demo_pages < full_pages <= 6` (skipped automatically
  where WeasyPrint/GTK is unavailable, same pattern as the existing PDF tests). Full suite:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest -q`:
  **419 passed** (413 before this session + 7 new, minus 1 double-counted by a `-k` filter
  quirk during a targeted run -- the full-suite total is what matters and is exact), 1
  pre-existing Starlette/AnyIO warning.
- Processes: both endpoints started/stopped correctly for `final_demo_check` and
  `final_demo_noopen`; confirmed after each that ports 8000/8001 have no LISTENING socket and
  no stray `python.exe`/`uvicorn` process remains. `results/final_demo_check/`,
  `results/final_demo_noopen/` were generated this session (gitignored, not committed).
  Template smoke-test scratch directories (`results/demo_tpl_check2*`,
  `results/full_mode_regen_check/`) were generated then deleted; none left on disk.
- Not done / explicitly out of scope: Docker, Hugging Face, web UI, `check_reproducibility.py`.
  No fresh full 1,928-case benchmark was run this session (per the task's explicit
  instruction); full mode's correctness rests on the regenerated-from-existing-data check
  above plus the unchanged `analysis`/`compare`/`severity`/runner code paths. Nothing was
  committed or pushed. Working tree now also has `report/demo_template.html` (new),
  `run_all.py`, `report/generate.py`, `report/style.css`, `tests/test_report.py`, and this
  file modified/added on top of the prior session's uncommitted work, pending Ahsan's review.
- Next: Ahsan reviews the diff, opens `results/final_demo_check/report/report.html` and
  `results/final_demo_check/report/report.pdf` to confirm the demo experience visually, and
  authorizes commit/push when ready.

## Pre-deployment orchestration checkpoint - Claude

- Updated: 2026-09-09T23:00:00+04:00, Claude Code; branch `main`, observed HEAD `c507033`
  (unchanged; nothing committed this session).
- Ahsan (the user, working directly) assigned the final pre-deployment task: a single-command
  full/demo orchestrator, featured demo evidence surfaced in the report, model revision
  pinning, and a two-run reproducibility check. Explicitly out of scope: Docker, Hugging Face
  deployment code, a web UI, `check_reproducibility.py`. Not authorized to commit/push; nothing
  was committed.
- New root file `run_all.py`: orchestrates existing components only (`baseline.load`,
  `attacks.library`, `runner.run.main`, `analysis.analyze.run_analysis_from_dir`,
  `report.generate.generate_report`) -- no attack/runner/analysis/report logic duplicated.
  Starts/stops uvicorn for V1 then V2 (no `--reload`), waits on `/health`, runs the shared
  suite via the runner's existing CLI entry point called in-process, then analysis and report.
  Exposes `run_experiment(mode, run_name=None) -> dict` as the reusable, prompt-free, path-
  relative entry point for a future deployment UI. `--mode demo` sends every standalone attack
  plus every derived attack for the first 2 baselines -- the count is computed from the real
  built suite at run time (`compute_demo_attack_limit`), not a hardcoded case number, so it
  cannot silently drift from `attacks/`. `--run-name` isolates output under `results/<name>/`;
  omitted defaults to a UTC timestamp. Confirmed demo mode finishes in well under a minute.
- Demo evidence is real data only, never fabricated: `run_all.py` rebuilds the full attack
  suite in-process (same deterministic call the runner makes) to recover `AttackCase`
  original/attacked text that `RunResult` does not persist, cross-references it with the
  actual `RunResult` rows and the analysis JSON's finding groups, and writes
  `results/<run>/demo_evidence.json`. Selection is ranked, not hand-picked: featured failure
  prefers `service_unavailable` > `unhandled_5xx` > `timeout` > `connection_failure` (only ever
  literal-crash-labeled when a `service_unavailable` group actually exists); featured flip
  prefers a `homoglyph`/`homoglyph_greek` subfamily, else the largest confidence swing. An
  HTTP 5xx with the service still healthy afterward is always labeled "unhandled server error,"
  never "crash" -- verified in the rendered HTML both times.
- Report changes (`report/generate.py`, `report/template.html`, `report/style.css`): a "Demo
  Highlights" section renders near the top of the report (right after the hero, before the
  verdict) when `analysis.json` carries a `demo_evidence` key; absent for old bundles without
  it. Extra top-level JSON key does not break `validate_report`'s strict schema (checked: it
  requires listed fields present, never rejects additional keys). Verified by injecting a
  synthetic `demo_evidence` block into the existing accepted `results/checkmate-final/
  analysis.json` and rendering both HTML-only and full PDF (WeasyPrint) without template
  errors (Jinja `StrictUndefined`), then again against two live runs' real output.
- `endpoint/model.py`: pinned `MODEL_REVISION = "0e1cd914e3d46199ed785853e12b57304e04178b"`
  for both the tokenizer and model `from_pretrained` calls. Verified against the actual local
  Hugging Face cache with `huggingface_hub.scan_cache_dir()` (not memory/guess): `refs/main`
  resolves to exactly this commit; the only other cached revision is `refs/pr/3017`, unused.
  This is Rayyan's file; edited as a task-specific exception the user's brief explicitly called
  for (pin the exact revision), same pattern as the earlier authorized `truncation=False` fix.
- Coverage audit against the official required areas (read-only inspection of `attacks/`,
  `runner/`, `analysis/`, `contract.py`; no attack-library changes made or proposed):
  malformed/oversized YES (`attacks/malformed.py`), boundary values YES (`attacks/boundary.py`
  string/length boundaries), **type confusion YES** -- already implemented as
  `boundary.type_confusion.{null,number,boolean,list,nested_object}` via `_raw_typed_case`,
  oracle `request_should_be_rejected_cleanly`, so nothing was missing and nothing was added;
  adversarial perturbations YES (`attacks/perturbation.py`, TextBugger-derived + natural
  noise); encoding/Unicode YES (`attacks/encoding.py`: homoglyph, homoglyph_greek, zero-width,
  deletion/backspace, fullwidth/ligature NFKC controls, bidi, null byte); automated runner,
  response/error/latency capture, severity-ranked findings, and remediation-tied-to-findings
  all YES (`runner/run.py`, `analysis/severity.py`, `analysis/analyze.py`,
  `contract.Finding.remediation` required field).
- Reproducibility: ran `python run_all.py --mode full --run-name repro_1` then, with no source
  changes, `--run-name repro_2`. Both completed: 1,928/1,928 coverage both versions both runs,
  identical planned-suite fingerprint and manifest SHA (`0471bccbf293095d...`, matching every
  prior real run recorded in this file), `whole_suite_comparable: true` both times. Flip rates
  identical to 16 significant figures (V1 218/1370 = 0.159124..., V2 112/1373 = 0.081573...)
  and all six category failure rates byte-identical between the two runs. `git diff` on the two
  runs' `analysis.json` isolates exactly one differing finding-group triple:
  `(malformed, oversized_10mb, {unhandled_5xx, slow_response, timeout})`. This reproduces,
  independently and for the third time this project, the hardware-timing sensitivity already
  documented above (`malformed.oversized_10mb` sits right at the 10s deadline): V1 500s on it
  consistently in both runs (91 unhandled 5xx, identical, both runs); V2 sometimes completes
  just under 10s with a non-5xx status (repro_1: resolves the 5xx group, adds a shared
  slow_response group) and sometimes exceeds it (repro_2: 5xx group becomes `unavailable`/
  inconclusive since V2 gave no status code to evaluate against, and a new V2-only `timeout`
  group appears). This is exactly the brief's listed acceptable variance
  ("machine-load-sensitive timeout behavior"), not a change in conclusions -- resolved count
  stayed 15/15; only remaining (14 vs 13) and newly-appearing (0 vs 1) moved by exactly this
  one case. All other 14 finding groups' status is identical across both runs. Verified with a
  standalone diff script, not eyeballed; see `results/repro_1/` and `results/repro_2/`
  (gitignored) for the raw evidence.
- Full test suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m pytest
  -q`: **413 passed**, 1 pre-existing Starlette/AnyIO warning, both before and after the two
  live runs. No test file was changed this session (no new tests added for `run_all.py` --
  the two live full runs plus the demo run plus the template smoke tests are the verification
  evidence; consider adding `tests/test_run_all.py` as a follow-up if the team wants orchestration
  covered by the suite rather than only by these live runs).
- Processes: both endpoints were started/stopped correctly by `run_all.py` for every run
  (demo smoke test, repro_1, repro_2); confirmed after each that ports 8000/8001 have no
  LISTENING socket and no stray `python.exe`/`uvicorn` process remains. `results/
  demo_smoke_test/` was generated then deleted (throwaway verification only);
  `results/repro_1/`, `results/repro_2/`, and `results/demo_tpl_check*/`(deleted) were
  generated during this session -- all gitignored, none committed.
- Not done / explicitly out of scope per the brief: Docker, Hugging Face Space config, a web
  UI, GitHub Actions deployment, cross-run comparison tooling, `check_reproducibility.py`.
  `run_all.py` has no automated tests of its own yet (see above). Nothing was committed or
  pushed; working tree has `run_all.py` (new), `endpoint/model.py`, `report/generate.py`,
  `report/template.html`, `report/style.css`, `README.md`, and this file modified/added,
  pending Ahsan's review.
- Next: Ahsan reviews the diff and the two generated reports (`results/repro_1/report/
  report.html`, `results/repro_2/report/report.html`), decides whether to add
  `tests/test_run_all.py`, and authorizes commit/push when ready.

## Report implementation checkpoint - Codex

- Updated: 2026-09-09T21:59:00+04:00, Codex; branch ahsan/report, observed HEAD c507033.
- User authorized developing Ahsan's report component, thorough testing, and showing the final system before committing/pushing to main. Publication follows user review; no commit/push performed.
- Complete and verified, uncommitted: report/generate.py, report/template.html, report/audit.html, report/style.css, report/README.md, tests/test_report.py, root README.md, requirements.txt and HANDOFF.md. Other owners' source and frozen contract unchanged.
- Renderer consumes schema v2 without cross-component imports. Includes strict consumed-field/count/evidence validation, comparison withholding, inconclusive/mixed-new evidence, SILVER qualifications, full coverage and denominators, deterministic safe HTML, PDF, preserved source JSON and SHA-256 export metadata. Output must be a new directory; HTML-only avoids the native renderer.
- Report integration fixed a real dependency incompatibility: installed pydyf 0.12.1 lacked Stream.transform required by WeasyPrint 62.3. Pinned/installed pydyf==0.10.0; no other installed package consumes it. `.\.venv\Scripts\python.exe -m pip check`: no broken requirements. No GTK changes, no WeasyPrint replacement.
- Final report tests: `.\.venv\Scripts\python.exe -m pytest tests/test_report.py -q --tb=short`: 76 passed in 4.85s (real PDF, full printed details, long-ID page bounds included). Final full suite with HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1: `.\.venv\Scripts\python.exe -m pytest -q`: 413 passed, one existing Starlette/AnyIO warning, 22.02s. `git diff --check`: passed. No source changes after those checks; only this checkpoint update.
- Real saved-data acceptance: `.\.venv\Scripts\python.exe -u results/report_acceptance.py`: passed. Actual analysis CLI over results/full_20260909_135157 equals accepted schema-v2 JSON, then actual report CLI via stdin produces results/checkmate-final/{report.html,report.pdf,analysis.json,export_meta.json}. 46 PDF pages; 42 finding records and remediation plus 478 unique supporting/flip/review/diagnostic IDs verified in extracted PDF text. PDFium line-ending hyphens normalized only for extraction comparison; output unchanged. All six benchmark artifact hashes unchanged. Report remains 14 resolved / 14 remaining; no new endpoint benchmark run.
- Final visual QA: `.\.venv\Scripts\python.exe -u results/report_visual_check.py results/checkmate-final results/report_visual_final`: passed. Desktop 1440px/mobile 390px, including all 93 details expanded: no overflow or broken anchors; 42 finding cards. PDF all-page character bounds pass, no blank pages. Inspected overview, outcome, finding and appendix pages; widened diagnostic-ID columns and moved detailed confidence evidence after findings. Final screenshots/contact sheet/check JSON in results/report_visual_final.
- Verified the documented PowerShell UTF-8 analysis-to-report pipeline with --html-only into results/report-powershell-check; parsed JSON equals final source. Root README now contains endpoint/runner/analysis/report commands and explicit Python 3.11 environment creation.
- Local QA files remain ignored: results/report_acceptance.py + .json, results/report_visual_check.py, results/report_tools (temporary pypdfium2 4.30.0), report_preview*, checkmate-report (earlier draft), report_visual_v*, report-powershell-check. Retain until review; final deliverable is results/checkmate-final and final preview is results/report_visual_final/desktop.png. Generated files must not enter Git.
- Processes: all validation sessions completed. Stalled owned Chrome PID 22936 was stopped; revised software-rendered Edge checks exit normally and stop their browser. No endpoint servers launched for this task.
- Next: Ahsan reviews HTML/PDF before the requested later commit/push to main. Implementation and testing are complete; no publication performed. On continuation inspect this branch/diff and preserve all generated evidence.

## Previous analysis implementation checkpoint - Codex

- Updated: 2026-09-09T20:50:11+04:00, Codex; main at 81aa53e.
- Ahsan explicitly authorized implementing the review recommendations on Khalid's behalf and committing/pushing directly to main. This is the task-specific exception to analysis ownership and the feature-branch/PR rule. No teammate messages requested.
- Implemented: strict artifact validation, symmetric comparison evidence, diagnostic exclusion, connection-failure findings, safe leak detection, unrounded severity, and documented report output with explicit rate counts. Scope: analysis/, its tests, HANDOFF.md; contract and other components remain untouched.
- Policy choice under delegated project-lead authorization: connection_failure gets 70/High, no size adjustment; separate from service unavailability. Existing severity weights remain unchanged.
- Verified so far: `.\.venv\Scripts\python.exe -m pytest tests/test_analysis.py tests/test_analysis_remediation.py tests/test_baseline.py -q --tb=short`: 233 passed in 1.86s. New regression file covers 75 cases; existing tests updated for corrected behavior. Saved full benchmark validates and remains 14 resolved / 14 remaining.
- Data-driven correction to proposed validation: shipped repeated_punctuation entries use diagnostic oracle + REVIEW tier. These are preserved and excluded by oracle, with tier differences exposed in diagnostic observations; recognized mixed combinations are not rejected. Unknown values still fail. No manifest or attack edits.
- Added analysis/README.md documenting schema_version 2, report integration, rate objects, case-level evidence, and policy changes. CLI supports both flat and v1/v2 directory layouts and verifies both retained manifests.
- Final validation by Codex: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, then `.\.venv\Scripts\python.exe -m pytest -q`: 337 passed, one existing Starlette/AnyIO warning, 17.32s. `git diff --check`: passed. No source changes since those tests.
- `.\.venv\Scripts\python.exe results/analysis_review_4b37ab6/verify_remediation.py`: passed. Strict validation, repeat analysis and real CLI produce identical schema-v2 JSON; retained original artifact hashes unchanged. Actual V2 TestClient reflection probe returns 422 and zero findings. Output: results/analysis_remediation/report_input.json and verification.json (ignored).
- Saved full benchmark remains 1,928 rows/version; 14 resolved, 14 remaining, zero unavailable/new; flips 218/1370 vs 112/1373; 36/42 eligible clean baselines each. No fresh endpoint benchmark or report rendering was run. PR's separate full2 dataset remains absent here.
- Final diff review confirms only analysis code/docs, analysis tests, and HANDOFF.md changed; no contract/baseline/endpoint/runner/attacks/report changes. Fetch confirmed origin/main equals local starting HEAD 4b37ab6. All reviewed issues are addressed with documented semantics; report work can proceed against schema v2.
- Committed and pushed implementation as 81aa53e (`fix(analysis): validate artifacts and require comparable finding evidence`). Push confirmed 4b37ab6..81aa53e main -> main; subsequent HEAD/origin/main both 81aa53e and working tree clean. This documentation checkpoint records publication and is being committed/pushed under the same authorization.
- Next: Ahsan can begin report implementation using analysis/README.md (schema v2) and results/analysis_remediation/report_input.json. No remaining blocker from the reviewed analysis issues. No running processes or pending test sessions. Earlier review evidence is historical; retained under ignored results/analysis_review_4b37ab6.

## Historical review checkpoint - Codex

- Updated: 2026-09-09T20:11:55+04:00, Codex; branch main, observed HEAD 4b37ab6 (merged PR #6).
- User requested independent review/testing against contracts and architecture. Review complete; no implementation fixes, commits, pushes, or teammate messages authorized or performed.
- Verdict: architecture/imports/dataclasses align; correctness fixes needed before final report use. Confirmed four disclosed issues plus persistent-group false resolution, unsupported newly-appearing claims, unchecked actual manifest hash/vocabulary, missing connection-failure findings, and reflected-input false leaks.
- Full details, code locations, reproductions and recommendations: results/analysis_review_4b37ab6/REVIEW.md (ignored). Harness probe.py; observations probe_output.json; full saved-data output analysis_output.json; actual V2 response reflected_path.json. altered_manifest.json is an intentional COPY for a negative probe; original artifacts unchanged. Keep these as local review evidence.
- Validation by Codex: Python 3.11.9; HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 then `.\.venv\Scripts\python.exe -m pytest -q`: 262 passed, one existing Starlette/AnyIO warning in 20.73s. `.\.venv\Scripts\python.exe -m pytest tests/test_analysis.py tests/test_baseline.py -q`: 158 passed in 3.20s.
- `.\.venv\Scripts\python.exe results/analysis_review_4b37ab6/probe.py`: exit 0, reproduces incorrect behaviors (observation harness, not desired-behavior passing regression tests). Actual V2 TestClient returned 422 with reflected user path that analysis falsely calls a leak.
- Independently checked saved results/full_20260909_135157/{v1,v2}: 1928 unique ordered rows each matching metadata completion/version, actual manifest hashes match and manifests byte-identical. Analysis repeated deterministically: 14 resolved/14 remaining/0 unavailable/0 new; 36/42 baselines eligible each; flips 218/1370 vs 112/1373; 5xx 90 vs 0; timeouts 1 each. No fresh live benchmark. PR's results/khalid_validation/full2 is absent here; its 15/14 claim refers to different artifacts.
- report/generate.py remains a stub: no full HTML/PDF report validation possible. Contract/baseline/other component source unchanged by merge and review. Tracked review change is HANDOFF.md only.
- Next: Ahsan assigns scoped fixes to Khalid or explicitly authorizes remediation. No running processes or pending test sessions. `git diff --check`: passed; final status contains HANDOFF.md only.

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
