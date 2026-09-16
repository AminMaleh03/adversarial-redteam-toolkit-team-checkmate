# TASK 1 — AHSAN PRODUCT INTEGRATION PARTIALLY COMPLETE; DEPENDENCIES BLOCK FINAL ACCEPTANCE

2026-09-15, Codex, Asia/Dubai. Assigned branch `stage3/ahsan`; observed HEAD
`d5c5a7bbf789bd858da021c9ccc114e349fb8448`, a normal merge of tested
`stage3/integration` (`40ceef06cfecd10fb34ab53c5e41de35cd694ae8`) into the assigned
foundation branch. User authorized completing Task 1, committing and pushing only this
branch, then opening a PR to `stage3/integration`; no merge is authorized. Work is in the
isolated clone `results/task1-stage3-ahsan` so the main checkout's intentional uncommitted
HANDOFF.md and local `.claude` settings remain untouched.

Implementation commit `3c606fb6e5ece562ed739bccabc12a17a3e495db` is published on
`stage3/ahsan`. Draft PR #11 targets `stage3/integration`:
https://github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate/pull/11. It is not
merged. This factual handoff checkpoint follows the implementation commit.

PR workflow run 35002778576 completed `failure` on the documented missing-policy path:
setup and gate invocation succeeded, the evidence artifact was published, identity/enforcement
failed because no candidate verdict was available, and deploy was skipped. URL:
https://github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate/actions/runs/35002778576.

Implemented in Ahsan-owned files: registry-selected orchestration with collision-safe run
IDs/indexes, exact plan reuse for pairs, sequential lifecycle and process-tree memory
measurement; schema-v2/v3 report validation and a target-aware v3 template; structured,
target-specific remediation rendering; trusted `/api/targets`, identity-bearing Demo/status
contracts, stale-response rejection and emotion/sentiment model switching; genuine paired
emotion and single-target sentiment interactive paths; a GitHub gate/release workflow whose
deploy job depends on gate success; and Docker caching for both registry-pinned models.

Real acceptance by this agent: emotion demo run `0e947d4a63484cd8` completed 162/1928
selected rows on each target and rendered v3 HTML/JSON; sentiment demo run
`066e4f2f00324a68` completed 162/1931 selected rows and rendered a v3 single-target
HTML/JSON report with `comparison: null`. All internal endpoint ports were reaped. Corrected
Windows process-tree measurement observed 294,629,376 bytes for a loaded sentiment service;
the measurement is the launcher plus descendants and is not a concurrency claim.

Validation: Ahsan-owned focused tests `254 passed`; full non-browser suite `1033 passed,
28 skipped`; opt-in Playwright suite `27 passed`; workflow YAML parsed; `git diff --check`
clean apart from local autocrlf notices. The browser run found and verified a compatibility
repair for legacy status payloads that omit the new optional run/evaluation identities.

Final Task 1 acceptance is blocked by two missing other-owner deliverables, both reproduced:
`attacks.library.build_suite(..., suite="oces")` raises because no public frozen-data runtime
loader exists, and `analysis/policies/ci_core_v1.json` is absent. The real gate therefore
returns `execution_error`, exit 2, at `results/task1_gate_missing_policy/gate_result.json`.
Without those dependencies, same-policy fail/pass proof, OCES inference, final container/live
deployment, and the five-page competition PDF cannot honestly be completed. No deployment or
final robustness claim was made. See `docs/stage3/handoffs/ahsan.md` for detailed evidence.

# STAGE 3 FOUNDATION — COMPLETE AND PUBLISHED

2026-09-15, Claude Opus 5, Asia/Dubai. Worktree `C:/Users/ahsan/OneDrive/Desktop/stage3-foundation`,
branch `stage3/foundation`. Tested tree = tag `stage3-foundation-v1`. Base
`a17fc5b3d06f1a069ebfa0b85a95f14fe01d344e` (`ahsan/v5-redlab`, tag `v6.0.0`) — the validated
release, not `main` (`c507033`, four releases behind).

Task: Task 5 only, from the supplied reviewed task pack. Status: **FOUNDATION_READY**. Full
report in `docs/stage3/FOUNDATION_READINESS.md`. Tasks 1-4 are NOT started.

The earlier NOT_READY verdict was raised because the reviewed plan and Task 1-4 descriptions
had not been supplied. They were then supplied, are checked in verbatim under `docs/stage3/`
(the five task sections were verified byte-identical to the standalone files), and the
blocker is resolved.

**Delivered.** `CONTRACTS.md` 3.0.0 · `contract.py` gains four appended `RunResult` fields
(`target_id`, `suite_id`, `request_body_bytes`, `request_body_sha256`) plus model-free
`ModelSpec`/`TaskSpec`/`TargetSpec`/`EvaluationSpec`/`Registry`/`CheckResult`/`GateOutcome`;
`BaselineCase`/`AttackCase`/`Finding` structurally unchanged · `endpoint/targets.py` +
`targets.json` with the five agreed evaluations and real pins · `attacks.metadata.scoped_registry`
(snapshot->clear->yield->restore; no existing caller changed) · `artifacts/benchmark_v6/`
byte-exact with `PROVENANCE.md` · frozen `ci_core_v1` (162 cases) and the approved clean
reference · `tests/fixtures/stage3/` (53 files, deterministic builder) · ownership, decisions
and model identity docs · narrow `AGENTS.md`/`CLAUDE.md` updates preserving all unrelated rules.

**Pins.** emotion `0e1cd914e3d46199ed785853e12b57304e04178b`; sentiment
`distilbert/distilbert-base-uncased-finetuned-sst-2-english` @
`714eb0fa89d2f80546fda750413ed43d93601a13`, labels NEGATIVE/POSITIVE, limit 512; dataset
`stanfordnlp/sst2` @ `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb`, validation, 872 rows. No
model weights were downloaded or loaded at any point.

**Validation by Claude (not historical).** `.venv` Python 3.11.9. `python -m pytest -q` =
681 passed, 27 skipped (580 pre-existing + 101 new foundation tests); the same from a clean
`--no-local` clone; `git diff --check` clean; fixture builder self-validates and rebuilds
byte-identically; registry import subprocess confirms no torch/transformers/endpoint.model.
27 skips are pre-existing (Playwright, WeasyPrint). The historical "607 passed" was not used
as evidence. No deployment, no new inference, no OCES authored or run.

**Two real bugs found and fixed, both pre-existing or latent.** (1) `test_web.py::test_verified_full_served_bytes_match_recorded_evidence_hashes`
failed on any fresh Windows clone of `v6.0.0` (CRLF-mangled `verified_full_report`);
confirmed on an unmodified clone of `a17fc5b`. (2) Four new foundation tests failed on a
fresh clone because fixture/CI-input hashes are taken from on-disk bytes. Both fixed by a
`.gitattributes` scoped to `artifacts/**` (binary) and the hash-bearing LF paths (`-text`).
Published bytes unchanged; project-wide text rules unchanged.

**Preserved.** The uncommitted `HANDOFF.md` edit (Codex reference audit) is untouched in the
main checkout on `ahsan/v5-redlab`. No reset, stash, discard or force-push; no existing
branch overwritten.

**Published.** `stage3/foundation`, `stage3/integration`, and `stage3/ahsan`,
`stage3/rayyan`, `stage3/khalid`, `stage3/lamei` — all six tips at the same foundation SHA
on `origin`. Member checkout commands are in `docs/stage3/FOUNDATION_READINESS.md` section 9.

**Next.** Ahsan distributes Tasks 1-4. Remaining runtime checks belonging to those tasks are
listed in the readiness report section 4; nothing in this foundation is evidence that any
feature works.

**Temporary files.** Clean-clone checkouts under the session scratchpad only; nothing left
running.

# SYSTEM V6 — DEPLOYMENT RELEASE (DEPLOYED; ONE USER ACTION LEFT)

2026-09-10, Claude (took over from Codex at its usage limit), Asia/Dubai.
Branch `ahsan/v5-redlab`. Starting HEAD `901cc22` (V5.5, human-approved visuals).
Final V6 HEAD: `4c68d47`, pushed to `origin` and deployed to the existing HF Space.
Ahsan's V6 brief authorized the report-history fix, release hygiene/docs, new V6
commits, the release-branch push, an exact-snapshot upload to the existing Space while
Protected, local/container/cloud/mobile acceptance, then Public visibility and an
annotated `v6.0.0` tag. No merge, no V5.5 amendment, no redesign, no core change.

## V6 commits

- `dc60422` report navigation fix and release docs.
- `a93479e` byte-exact deployment snapshots for the verified evidence.
- `d03657a` report internal navigation history-safe during parse.
- `4c68d47` report internal navigation history-safe for unparsed sections.

## The UX fix as shipped

Internal report navigation (sidebar, mobile drawer, rubric and finding anchors, skip
link) is handled by a delegated listener in the report's `<head>`: it takes over the
click, scrolls the target into view and calls `history.replaceState`, so the Technical
Report occupies one logical page and the global Back control leaves it. The end-of-body
script keeps scrollspy, drawer and active state through `window.rlOnInternalNav`.
Two placements were required and both were found by real testing, not review:
1. the listener must be in `<head>` — this document is ~500KB, so on the hosted Space
   the sidebar is interactive long before the end-of-body script parses;
2. it must take over clicks whose target section is not parsed yet — otherwise the
   click fell through to native navigation, pushed an entry and scrolled nowhere.
Report entry links from Home, Lab and the demo report now open in the same tab, which
the brief's Results -> Report -> Back requirement needs. Source JSON keeps its new tab.
Modified clicks, deep links, `aria-current`, scrollspy, the drawer and Evidence/Audit
ordering are unchanged. V5.5 visual design untouched; behaviour only.

## Evidence-integrity defect found during deployment

The first upload built and started cleanly, but the anonymous smoke check caught the
served `/verified-full/analysis.json` hashing to `8a950cad...` instead of the published
`12d47b35...`. Cause: this checkout has `core.autocrlf=true` and the repo has no
`.gitattributes`, so `git archive` rewrote text blobs to CRLF — identical content,
different bytes, invalid published hash. `report.pdf` (binary) was unaffected. The
release operator now uses `git -c core.autocrlf=false -c core.eol=lf archive` and
asserts every `export_meta.json` entry before uploading;
`tests/test_web.py::test_verified_full_served_bytes_match_recorded_evidence_hashes`
now fails locally instead of shipping. Any future deployment tooling must preserve
committed bytes exactly.

## Validation (all run in this checkout)

- Full suite **607 passed, 1 pre-existing deprecation warning, 55.53s**
  (`.\.venv\Scripts\python.exe -m pytest -q` with `REDLAB_BROWSER_TESTS=1`).
  Baseline was 599 at V5.5; V6 adds 8 report-history/evidence-integrity tests.
- Real local acceptance PASS (`results/v6-local-acceptance/summary.json`): Demo ->
  Results -> Report -> sections -> Back returns to Results, second Back to Home,
  forward/reload, Custom reload and Test Another, CUSTOM -> DEMO -> CUSTOM, active-Demo
  rejoin keeps the same run_name, no stale completed execution view.
- Docker `red-lab-v6:latest` built with cached apt/pip/model layers
  (`results/v6-docker-build.log`); container acceptance PASS, six routes 200, real
  CUSTOM -> DEMO -> CUSTOM (`results/v6-docker-acceptance.json`).
- Hygiene (`results/v6-hygiene.json`): nothing tracked from `results/`, no temporary
  scripts, logs, caches, screenshots or credential-shaped values. Absolute paths appear
  only in the intentional redaction fixtures in `tests/test_analysis*.py`; retained.
- No orphan endpoint processes or 8000/8001 listeners after local and container runs.
- Integrity unchanged throughout, locally and as served by the Space:
  `analysis.json` `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`,
  `report.pdf` `0853108d4939bab1ff2069a1e3dc42b8ad68b14096d12cfd1bfa81fbb56718ca`.
  Only the verified `report.html` was re-rendered from the template; no benchmark rerun.

## Deployment

GitHub `origin` https://github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate.git
— branch `ahsan/v5-redlab` pushed at `4c68d47`. No merge into `main`.
HF Space `ahsan-141117/team-checkmate-adversarial-redteam-toolkit`, authenticated as
`ahsan-141117`. Method: `git archive` of the exact commit (autocrlf disabled) plus
`huggingface_hub.upload_folder`, then a remote tree blob-hash check of all 77 files
against the commit; the Space's only extra file is its platform `.gitattributes`.
Operator `results/v6_hf_release.py` (ignored). Raw HF git protocol-v2 fetch is still
avoided. Space revision `732faf7` = GitHub `4c68d47`, stage RUNNING, Docker Space
architecture and 7860-only exposure unchanged; V1/V2 stay internal subprocesses.

Cloud validation against https://ahsan-141117-team-checkmate-adversarial-redteam-toolkit.hf.space
while the Space was still Protected:
- Smoke PASS: `/healthz`, `/`, `/lab`, verified `report.html`/`analysis.json`/`report.pdf`
  and all five static assets 200; static and report bytes match local; evidence SHA-256
  matches the published values; JSON still inline, not an attachment.
- Startup logs clean, no secrets (`results/v6-hf-run.log`, `results/v6-hf-build.log`).
- Real cloud acceptance PASS (`results/v6-cloud-acceptance/summary.json`, 64 screenshots):
  live Demo, custom Lab, CUSTOM -> DEMO -> CUSTOM with no wait, active-Demo rejoin,
  Report -> `#remediation`/`#provenance`/`#v2-findings` with `history.length` constant,
  Back returns to Demo Results, unknown lab job 404, zero page errors.
- Mobile/responsive PASS at 1920/1440/1366/1024/768/390: no horizontal overflow on Home,
  Lab, Lab metrics, Demo execution/Results, Evidence and the Technical Report; mobile
  nav drawer and report drawer usable; report Back from mobile returns Home.
- Result framing correct: cloud Demo reports "V1 162/1928 (8.40%)" and states the numbers
  describe that demo run only; the Technical Report keeps 1928/1928.

## Remaining user action

Space visibility is still **Protected** (`private=true`). The automated switch was
blocked by this session's permission policy, not by Hugging Face — authentication and
the API call are ready. Either re-run with approval:
`.\.venv\Scripts\python.exe results/v6_hf_release.py public` (it re-checks cloud
acceptance, stage and smoke before flipping, then confirms through the unauthenticated
Hub API), or set the Space to Public in its Hub settings. The unauthenticated
post-public check and the `v6.0.0` tag push are the only steps after that.

## Approved V5.5 snapshot (historical)

Updated: 2026-09-10T18:07:45+04:00, Codex, Asia/Dubai.
Branch: `ahsan/v5-redlab`. Observed pre-tuning HEAD: `b2b5f18`.
State: implemented, verified and amended locally. Observed code-amendment HEAD
`0f82bc7`; this final factual checkpoint is folded into the same V5.5 amendment.
Use `git rev-parse HEAD` for the final hash. V5.4 parent remains `0ea2581`.
No push or merge. Human visual approval is still required.

## Current objective and authorization

Ahsan's latest attached "SYSTEM V5.5 - FINAL VISUAL TUNING PASS" brief on
10 September 2026 explicitly approves the structure delivered in b2b5f18: Home,
Demo execution, Lab, Technical Report/sidebar, far-left Back and state/history.
It authorizes only palette/atmosphere/particles, Lab metric icons, optional Evidence
anchor, corresponding tests, verified HTML-only regeneration, local/Docker acceptance,
and amendment of the unpushed V5.5 commit. This includes web/report/tests/artifact scope.
No V5.6, push, merge, full benchmark, authoritative PDF regeneration or core changes.

## Completed final tuning

- Shared palette: warm white #fff9f4, white surfaces, charcoal #17181c/#292a2f,
  crimson #c6253d/#971e32, warm red #d53a3e, burnt orange #e5622e and rare citrus
  #f0a33a. Muted text #6d655f and borders #e7dcd3. Rust/green remain endpoint semantics.
- Home: decorative field spans the actual viewport (excluding scrollbar), while content
  measure and hierarchy stay unchanged. Removed corner framing and duplicate bounded
  background rules. Integrated crimson/orange washes and fine static texture.
- Particles: 1.8x average previous drift velocity; independent depth, size and opacity;
  short warm connections, independent nodes and a soft central reading zone. Desktop
  44/68 nodes, mobile 16; reduced motion keeps a static field. No pointer interaction.
  Existing visibility/hidden-view lifecycle remains intact.
- CTA dimensions and hierarchy preserved; Technical Report now has white fill and
  crimson border/text. Static internal surfaces, current-stage emphasis, input focus
  and restrained shadows updated by modifying existing authoritative selectors.
- All seven Lab metrics retain their exact values/labels. Inline decorative SVGs sit
  right of the number/label; fixed local geometry, aria-hidden, not focusable. No library.
  Only renderSummary presentation changed in lab.js; state/storage/polling untouched.
- Demo Results: Evidence anchor after Method fits the existing desktop header and mobile
  menu. Existing 03 / SOURCE heading, evidence explanation, SHA-256 and schema preserved.
- Technical Report: shared palette only. Its generated content and scripts are byte-for-
  byte unchanged after excluding the style block. No sidebar/rubric/chart redesign.
- Removed superseded Home field/corner rules, metric declarations shared incorrectly
  with score lists, and duplicate progress transition. No new override layer/!important.

Changed this pass: web/static/{app.css,particles.js,lab.js}, report/{style.css,
demo_template.html}, tests/test_ui_browser.py, verified report.html/export_meta.json,
and this handoff. Web templates, app.js/chrome.js, report template/charts unchanged.

## Validation by this Codex pass

Project Python 3.11 .venv, optional Playwright/installed Edge. Full suite:
```
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:REDLAB_BROWSER_TESTS='1'
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```
**599 passed, 1 existing Starlette/AnyIO deprecation warning in 93.39s**.
Log: `results/v55-tuning-final-tests.txt`. Existing 595 retained; two additional
responsive widths and two focused browser tests (metric SVG/text/layout, Evidence
entry/provenance/header fit). Initial browser-only run had one new fixture failure:
full-report sample lacked a Demo-only field; fixed only the test fixture, then passed.

Real local command: `.\.venv\Scripts\python.exe results/v55_tuning_acceptance.py`.
PASS: Demo complete/results/Back/Forward/reload; Custom results/reload/Test Another;
CUSTOM -> DEMO -> CUSTOM; repeated active Demo nav/reload retains the same run_name,
no duplicate run. No stale views or browser errors. Local process/listener probe found
no endpoint.v1/endpoint.v2 processes and no listeners on 8000/8001 after completion.
Demo runs: hf_demo_20260910_140226_008f86 and hf_demo_20260910_140308_30eac5.
Screenshots/no-overflow checks: 1920, 1440, 1366, 1024, 768, 390 for Home, Lab metrics,
Demo Results/Evidence, Technical Report/charts; mobile report drawer included.
Evidence: `results/v55-tuning-acceptance/summary.json`, screenshots in same directory;
`results/v55-tuning-real-acceptance.log`. Preview fixture images are separate in
`results/v55-tuning-preview/`; they are not measurement evidence.

Docker: one successful build AFTER local tests; apt/pip/pinned-model layers CACHED.
Command: `.\.venv\Scripts\python.exe results/v55_tuning_docker_build.py`.
Image: `team-checkmate-v5-redlab:latest`, config/id
`0cbbd3e8b6ed2b4f14c554d91e4dbb845c9de7b763e5834da398caad7d1af53a`.
Reviewed tracked-source staging context excludes local .claude settings; no Dockerfile
or dependency changes. Log: `results/v55-tuning-docker-build.log`.
`.\.venv\Scripts\python.exe results/v55_tuning_docker_acceptance.py`: PASS.
Six routes 200: /, /healthz, /lab, verified report.html, analysis.json, report.pdf.
JSON remains inline. Real CUSTOM -> DEMO -> CUSTOM passed (8.56/24.51/8.59s).
Privacy 404, JSON/PDF hashes, no endpoint processes/listeners and no .claude in image
all verified. Temporary redlab-v55-tuning-acceptance container removed.
Evidence: `results/v55-tuning-docker-acceptance.json` and container log.

## Integrity and Git

Before AND after, including Docker-served evidence:
- analysis.json: `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`
- report.pdf: `0853108d4939bab1ff2069a1e3dc42b8ad68b14096d12cfd1bfa81fbb56718ca`

Only verified HTML re-rendered using render_html; export metadata matches actual HTML
bytes. No benchmark rerun. `.\.venv\Scripts\python.exe results/v55_tuning_audit.py`
PASS: frozen paths unchanged; lab.js changes confined to metric presentation; generated
Technical Report non-style content/scripts unchanged. `git diff --check` passed.
Frozen: contract.py, endpoint/model/V1/V2, baseline, attacks, runner, analysis/thresholds,
run_all.py, web backend/privacy. No production dependency changes.
Read-only remote checks: origin main c507033; Space main b11bf79; neither has a V5.5
branch, and no remote-tracking ref contains b2b5f18. V5.4 parent 0ea2581 must remain.
Only the existing V5.5 commit may be amended; no pushes to either remote.

## Running processes and next action

Intentional preview remains healthy at http://127.0.0.1:7860/:
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/Scripts/python.exe -m uvicorn
web.app:app --host 127.0.0.1 --port 7860`; server PID 7060, launcher 37532,
original exec session 33913. Log: `results/v55-closure-server.log`.
All new test/build/acceptance sessions completed; temporary Docker container removed.
Task staging directory results/v55-docker-context has been removed.
Ignored results logs/screens/scripts stay for review and must not be committed.
Pre-existing .claude/settings.local.json preserved; globally ignored in normal Git.
Sandboxed Git cannot read that global ignore and may show .claude/ as untracked.

Next: Ahsan's manual visual review at http://127.0.0.1:7860/. Implementation and
validation are complete; Git status was clean after the code amendment. No push.

## Short history

V4 frozen tag v4.0.0 -> bba3a7b. V5.1 6b0bc9c branding; V5.2 5eb8735 execution;
V5.3 6716107 report navigation; V5.4 0ea2581 Custom Lab/registry isolation.
Original V5.5 3d1c990 was rejected visually; previous closure b2b5f18 fixed structure,
charts, history and Back. Latest human review approves that structure and asks only
for this final color/dynamics pass. Older parked suggestions are not new tasks.

# Stage 3 Task 1 PR #11 - targeted CI repair in progress

2026-09-15T23:43:23+04:00, Codex, Asia/Dubai. Branch `stage3/ahsan`, observed
pre-repair HEAD `c809ca4bd03f1b93e08239b511fbf7bb6ffb22bb`; live GitHub branch and PR #11
head matched it, and `stage3/integration` remained `40ceef06cfecd10fb34ab53c5e41de35cd694ae8`.
User authorized the narrowly targeted repair in the 15 September 2026 attached brief.

Implemented but not yet committed/pushed: resolve an explicitly supplied registry
`results_root` before deriving the run directory; create `results/` before the release-gate
tee/redirection; focused regressions cover portable target paths and the workflow's producer
exit-code chain. Validation by this Codex session: Python 3.11.9; targeted
`tests/test_run_all.py tests/test_gate.py` **52 passed in 0.87s** after correcting one new
test assertion (initial targeted run: 51 passed, 1 failed); workflow YAML parse PASS;
`git diff --check` PASS. The one authorized real command produced run
`ci-targeted-repair_0cc2162a825c470b`, gate outcome `pass`, exit 0, all 13 checks status
`pass`, and wrote `gate_result.json`, analysis evidence, `gate.log`, and
`gate-exit-code.txt` containing 0. No full suite, Docker, OCES, Playwright, deployment, or
report regeneration was run. No process was left running.

Next: review/stage the four explicit files, confirm the live GitHub head is still `c809ca4`,
commit `fix(ci): normalize gate output paths`, push normally, and observe only its PR run.
The main integration checkout's intentional `HANDOFF.md` remains byte-identical at SHA-256
`901bfd4e739f0e9b1ea2d8dad173df6663fa203e2e56716da8a99048e9337ae2`.

# RED LAB v6.1 — truthful target-aware runtime UI and interactive-result corrections

2026-09-16T10:33:50+04:00, Claude Sonnet 5, Asia/Dubai. Branch `stage3/ahsan`, worked in a
fresh git worktree at `C:\Users\ahsan\OneDrive\Desktop\stage3-ahsan` (the prior stale local
`stage3/ahsan` branch ref, at old commit `257e15f`, was reset to track
`origin/stage3/ahsan`). Observed pre-work HEAD `2aa883ebac6c9a92812757380d2dabfeccde4c42`,
matching the user-stated authoritative remote head; base `stage3/integration` confirmed at
`40ceef06cfecd10fb34ab53c5e41de35cd694ae8`. PR #11 remains open, draft, unmerged, targeting
`stage3/integration`. The main integration checkout's uncommitted `HANDOFF.md` was not
touched; it was independently verified to still hash to
`901bfd4e739f0e9b1ea2d8dad173df6663fa203e2e56716da8a99048e9337ae2`. User authorized this
scope in the v6.1 milestone brief (2026-09-16); no other exception requested.

Root cause found before fixing anything: `web/app.py`'s Live Demo route always calls
`run_all.run_experiment(..., evaluation_ids=[evaluation_id])`, so it always goes through
`_run_registry_experiment` (schema v3), which renders through `report/template_v3.html` --
`report/demo_template.html` (schema v2) is legacy/CLI-only and was already correct (no PDF
link). The real Phase 4 defect was in `template_v3.html`'s unconditional
`{% if include_pdf %}` Download PDF button, reachable by every demo run regardless of
evaluation.

Implemented (Ahsan-owned files only: `report/`, `run_all.py`, `web/`, `tests/`):

- **Phase 1** — `report/generate.py`'s `PRODUCT_VERSION_LABEL` bumped to `"Red Lab v6.1"`
  (the one place every live page and freshly generated report reads from). The archived
  `/verified-full/` artifact under `artifacts/verified_full_report/` is a static, pre-generated
  snapshot never re-rendered from this constant -- confirmed byte-identical (not in `git
  status`) and its own literal `"Red Lab v5.0"` text was left untouched.
- **Phase 2/3** — new `web/progress.py` defines a shared "descriptor" shape (cards, same-model
  note, footer note, real stage order/percent, display stage list with each row's `maps_to`
  real stage). `web/app.py` (`_demo_descriptor`) and `web/lab.py` (`_lab_descriptor`) each build
  a paired (emotion.core) and a single-target (sentiment.core) descriptor; `index.html`/
  `lab.html` embed both as JSON, and `chrome.js`'s new `rlRenderProgress`/generalized
  `rlUpdateLanes` build the endpoint cards and stage checklist DOM from whichever descriptor
  matches the real `evaluation_id` -- never pre-rendered V1/V2 markup hidden with CSS. Demo's
  single-target list uses one combined real "attacking_target" event (the registry orchestrator
  only emits one send-suite transition per target); the interactive Lab's single-target list is
  more granular because `run_custom_lab`'s sentiment branch already makes two real calls (clean
  reference, then variants) -- renamed its emitted stage ids to `starting_target`/
  `clean_reference`/`adversarial_variants` accordingly.
- **Phase 4** — `report/template_v3.html`'s Download PDF anchor now also requires `mode ==
  'full'`; `run_all.py`'s `_run_registry_experiment` and `run_analysis_and_report` both force
  `html_only` (skip PDF rendering entirely) whenever `mode == "demo"`, and pass the real mode
  through to `report.generate` instead of a hardcoded `"full"` (CI's `mode="ci"` is mapped to
  the `"full"` report style, since `report.generate` only knows `"full"`/`"demo"` presentation
  modes -- unchanged from before). No demo run of either evaluation produces a `report.pdf`
  file at all now, closing the class of bug regardless of exact prior reproduction path.
- **Phase 5** — `lab.html`'s interactive-result disclaimer changed from the emotion-specific
  "not part of the verified 1,928-case benchmark" to "not part of the frozen verified
  evaluation suite".
- **Phase 6** — `web/lab.py`'s `diagnose()` no longer collapses every non-flip outcome into
  `NO_MATERIAL_EFFECT`. New `_distribution_shifted()` (TV distance > 0, itself already rounded
  to 6dp -- no new threshold) splits the old bucket into `STABLE_LABEL_DISTRIBUTION_SHIFT`
  ("Label stable; distribution shift observed") and `NO_OBSERVED_CHANGE` ("No observed
  prediction change"). Paired mitigated/persists/regression codes, which already require an
  actual flip, are unchanged. The single-target sentiment path gained the same honest
  A/B/C framing (`LABEL_CHANGED` / `STABLE_LABEL_DISTRIBUTION_SHIFT` / `NO_OBSERVED_CHANGE`),
  replacing its previous flat `"OBSERVED"` diagnosis for every variant.
- **Phase 7** — `select_lab_variants` now returns a 4th element, `is_diagnostic`, read directly
  from `attacks.metadata.ORACLE_DIAGNOSTIC` on the matched case's own pre-registered metadata
  (never re-derived). Both `_build_result_payload` (paired) and `_build_single_result_payload`
  (single-target) give a diagnostic case its own `DIAGNOSTIC_OBSERVATION` verdict, keep its
  label change out of the scored `v1_flips`/`v2_flips`/`label_flips` counters, and add it to a
  new, separate `diagnostic_observations`/`diagnostic_label_changes` summary count instead.
  `attacks/` itself was not touched.
- **Phase 8** — `select_lab_variants` now skips a catalogue entry whose matched case's
  `attacked_text == original_text` (a genuine no-op for that input), logging the omission at
  debug level, rather than counting or sending an unchanged duplicate. This is the same rule
  for every evaluation (the function takes no evaluation_id), so emotion and sentiment can
  legitimately see different applicable-variant counts for different input text without any
  evaluation-specific branching.
- Small additive CSS (`app.css`) for the new diagnosis badge classes; no layout/visual redesign.

Deliberately NOT done (frozen/out of scope, confirmed unchanged): `contract.py`,
`CONTRACTS.md`, `analysis/` (incl. policies/case_sets), `attacks/`, `runner/`, `endpoint/`,
`baseline/`, `artifacts/verified_full_report/`, model revisions, OCES generator version,
Docker, Hugging Face deployment, `/verified-full/` report content, and no new master
technical report.

Validation by this Claude session (Python 3.11, `.venv` from the main checkout, invoked
against this worktree):
- `tests/test_lab.py`: 61 passed (18 new/rewritten: version-source, PDF-omission-adjacent,
  diagnosis relabeling incl. new `test_diagnosis_stable_label_distribution_shift`, diagnostic
  truncation exclusion for both emotion and sentiment, no-op variant filtering, Cyrillic+Greek
  co-applicability, single-target descriptor content, target-neutral disclaimer).
- `tests/test_web.py`: 56 passed (rewrote 2 stale-markup tests to read the new
  `demo-descriptors` JSON instead of removed static HTML; added centralized-version-source,
  sentiment-single-target-descriptor, and sentiment-stage-alias tests).
- `tests/test_report.py`: 122 passed (4 version-string literals updated to v6.1; added 3 new
  v3 demo/full PDF-exposure tests).
- `tests/test_run_all.py`: 30 passed (unaffected by the demo/PDF orchestration change).
- `tests/test_gate.py`: 41 passed (confirms the CI gate path, which forces its own
  `html_only`, is unaffected by the new demo-mode PDF suppression).
- Combined run of the five files above: **313 passed**, 1 pre-existing Starlette deprecation
  warning, no failures.
- `tests/test_ui_browser.py`: 27 skipped (Playwright/browser not available in this
  environment -- unchanged from before this work; not a regression).
- `git diff --check`: clean (only a pre-existing LF/CRLF autocrlf notice on `app.js`).
- Local smoke test: started `uvicorn web.app:app` on a scratch port; `/healthz` returned 200;
  `/` and `/lab` both rendered `"Red Lab v6.1"`; the embedded `demo-descriptors`/
  `lab-descriptors` JSON verified programmatically to hold `emotion.core: kind=paired` (two
  V1/V2 cards, `same_model_note="Two endpoint configurations"`) and
  `sentiment.core: kind=single` (one "Sentiment — Configured Target" card,
  `same_model_note=null`, no paired vocabulary anywhere in its JSON); confirmed directly via
  `report.render_html(..., mode="demo")` on the real `expected_analysis_v3.json` fixture that
  `"Download PDF"` is absent in `demo` mode and present in `full` mode; server process
  force-stopped afterward and confirmed unreachable.
- Did not run: the full 1076+ suite, full emotion/sentiment core, OCES, Docker, CI policy
  regeneration, or detailed technical-report generation (all out of scope per the brief).

Not yet done as of this checkpoint: the code above is validated and ready but **not yet
staged, committed, or pushed** -- that is the immediate next action. Once committed, this
entry should be treated as pre-commit; the actual final SHA will be visible in `git log` and
the PR (a commit cannot record its own hash). Expect origin/stage3/ahsan to still be at
`2aa883e` at push time; if it has advanced, stop and reconcile before pushing.

Explicitly deferred to v6.2+ (per the brief -- do not start): application commit provenance
fix; emotion common paired denominator; sentiment conditional report limitations; replacement
of `/verified-full/`; multi-target master technical report; new technical-report PDF; OCES
master-report sections; CI evidence report section; broad visual redesign; responsive/mobile
polish; Docker rebuild; deployment; final Red Lab v7.0 branding.

Next: stage the 15 files listed above explicitly (never `git add -A`/`.`), commit as
`feat(v6.1): make runtime UI target-aware`, fetch origin and confirm `origin/stage3/ahsan`
is still `2aa883e`, push normally (no force), observe the one triggered gate run, confirm
deployment is skipped, and leave PR #11 draft and unmerged. Do not touch Hugging Face.

**v6.1 closed out**: committed as `7c463038de1635d9c10ad7172c49cbfbbf3cb84f`; `origin/
stage3/ahsan` had not advanced (still `2aa883e`) at push time; pushed cleanly (`2aa883e..
7c46303`). GitHub Actions run `35064427517` ("Stage 3 release gate") completed `success`;
its "Deploy tested release to Hugging Face Space" job was `skipped`. PR #11 confirmed open,
draft, unmerged. Hugging Face `space` remote was never touched.

# RED LAB v6.2 — accurate target-aware report metadata, provenance and comparison wording

2026-09-16T11:20:00+04:00, Claude Sonnet 5, Asia/Dubai. Branch `stage3/ahsan`, same worktree
`C:\Users\ahsan\OneDrive\Desktop\stage3-ahsan`. Observed pre-work HEAD
`7c463038de1635d9c10ad7172c49cbfbbf3cb84f`, matching the user-stated required starting HEAD
exactly. Base `stage3/integration` confirmed at `40ceef06cfecd10fb34ab53c5e41de35cd694ae8`.
PR #11 remains open, draft, unmerged. The main integration checkout's uncommitted
`HANDOFF.md` was not touched; independently re-verified still hashing to
`901bfd4e739f0e9b1ea2d8dad173df6663fa203e2e56716da8a99048e9337ae2`. User authorized this
scope in the v6.2 milestone brief (2026-09-16).

Investigation before fixing anything: read `runner.run.code_provenance`,
`run_all._run_registry_experiment`'s `analysis_document` assembly, `analysis.analyze`'s
`build_comparison_summary`/`LIMITATION_NOTES`, and `report/template_v3.html` (the schema-v3
template that actually renders every Live Demo/CLI-registry report). Two of the three
described defects turned out to already be computed correctly in the live code path --
`code_provenance(ROOT)` is called once and threaded through consistently, and
`build_comparison_summary`'s `common_denominator` genuinely is the matched-case
intersection, confirmed against `tests/fixtures/stage3/expected_analysis_v3.json`. The one
concrete, reproducible defect found: `analysis.analyze.LIMITATION_NOTES` (frozen, Khalid's
`analysis/`) is emitted unconditionally onto every target's summary regardless of pairing,
and its second entry is written in V1/V2-hardening terms -- so a sentiment-only run's
top-level `limitations` list (built by `run_all.py`, Ahsan-owned) always carried that note
even though sentiment has no V2 at all.

Implemented (Ahsan-owned files only: `report/`, `run_all.py`, `tests/`; nothing under
`analysis/`, `attacks/`, `runner/`, `endpoint/`, `baseline/`, `contract.py`, `CONTRACTS.md`,
or `artifacts/verified_full_report/` was touched):

- **Branding**: `report/generate.py`'s `PRODUCT_VERSION_LABEL` bumped to `"Red Lab v6.2"`.
- **Application commit**: `_run_registry_experiment` already called `runner_mod.
  code_provenance(ROOT)` once and reused it; added a new, directly unit-tested
  `_app_commit_unavailable_reason(provenance)` helper that produces an explicit, honest
  reason string (never "unknown", a branch name, or a remote head) whenever the commit is
  genuinely missing, stored as `run_identity.app_commit_unavailable_reason`.
  `report/template_v3.html`'s "Application commit" line now shows the real commit when
  present, or "Not recorded — <reason>" when not, instead of a bare, unexplained fallback.
  `report/generate.py` was confirmed (and now has a regression test) to import no
  `subprocess` and never shell out to `git` -- provenance is threaded through existing run
  evidence only.
- **Common eligible denominator**: no code change to the computation itself (already correct
  and frozen under Khalid's `analysis/`); added rendering-layer regression tests pinning that
  the template shows the matched-intersection value (not either side's own denominator
  alone), that a withheld comparison shows its explicit reason rather than "Not recorded",
  and that single-target sentiment renders the (now more complete) "Not applicable" notice
  with no "Common eligible denominator" line at all.
- **Sentiment limitations leak**: new `run_all._applicable_limitations(analysis_blocks)`
  replaces the old bare flatten-and-dedupe of every target's `summary.limitations` --
  filters out the one paired-only (V2-hardening) note, matched by content not tuple index,
  whenever the run contains no paired evaluation at all. A run that includes any paired
  evaluation (e.g. emotion.core alongside sentiment.core) keeps the note untouched.
- **Report identity consistency**: each endpoint card in `template_v3.html` now shows its
  declared/inferred model id + revision and tokenizer id + revision (previously present in
  the analysis data but never rendered anywhere); the single-target notice now names the
  pinned target, states no hardening comparison is available or implied, and that
  remediation must rest on single-target evidence only.

Validation by this Claude session (Python 3.11, `.venv` from the main checkout, invoked
against this worktree):
- `tests/test_run_all.py`: 18 passed (8 new: synthetic-40-char-SHA `run.json` check via the
  existing `_plan_evaluation` early-stop technique, `_app_commit_unavailable_reason` unit
  tests incl. empty-string and present-commit cases, `_applicable_limitations` unit tests
  for sentiment-only exclusion / paired-run retention / ordering+dedup).
- `tests/test_report.py`: 153 passed (4 version-string literals updated to v6.2; 1 wording
  assertion updated for the expanded single-target notice; 9 new v6.2 tests: real
  40-char-commit rendering, explicit missing-provenance reason, no model-revision/branch-name
  substitution, no-subprocess-import regression, matched-intersection denominator not
  either side alone, withheld-comparison explicit reason, single-target not-applicable
  wording, no V2/hardening affirmative claims in a sentiment block, and no V2/hardening
  limitation note when the run has no paired evaluation).
- `tests/test_web.py`: 55 passed (2 version-string literals updated to v6.2).
- `tests/test_lab.py`: 61 passed (unaffected, run as part of the combined check).
- `tests/test_gate.py`: 41 passed (unaffected).
- Combined run of the five files above: **329 passed**, 1 pre-existing Starlette deprecation
  warning, no failures.
- `tests/test_analysis_identity.py`: 37 passed (sanity check that nothing under `analysis/`
  was disturbed; not modified, not expected to change, ran anyway per the brief's mention of
  "analysis/provenance or identity tests if directly affected").
- `git diff --check`: clean.
- Minimal report-generation smoke check (direct `report.render_html` calls on
  `tests/fixtures/stage3/expected_analysis_v3.json`, no models loaded): emotion paired
  fixture's real 40-char `app_commit` (`9386d75a...`) appears verbatim; `common_denominator`
  (`6`, an int) renders correctly; the sentiment block contains no V2/hardening-comparison
  claims; sentiment `comparison` is `null` and its notice reads "No hardening comparison is
  available or implied"; `"Red Lab v6.2"` appears in the rendered HTML.
- Did not run: the full pytest suite, full emotion.core/sentiment.core, OCES, Docker,
  Playwright, CI-policy regeneration, or deployment (all out of scope per the brief).

Code was validated, then committed as `12ab918815292d3d81c49167d724821823c3f63f` with
message `feat(v6.2): correct report provenance and comparison context`. Immediate next
action is fetch/verify/push (below).

Explicitly deferred to v6.3+ (per the brief -- do not start): replacement of
`/verified-full/`; the new multi-target master technical report; combined Core and OCES
narrative; CI-gate evidence section in the master report; new master-report PDF; broad UI
redesign; responsive/mobile polish; Docker rebuild; deployment; final Red Lab v7.0 branding.

Next: fetch origin and confirm `origin/stage3/ahsan` is still `7c46303` (unchanged since
v6.1's push) before pushing this commit, push normally (no force), observe the one
automatically triggered gate run, confirm its deploy job is skipped, and leave PR #11 draft
and unmerged. Do not touch Hugging Face.
