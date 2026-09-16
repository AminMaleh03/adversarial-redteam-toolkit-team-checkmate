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

**Pushed, CI failed, root-caused, fixed, re-pushed, CI passed.** `12ab918` pushed cleanly
(`7c46303..12ab918` — origin had not advanced). GitHub Actions run `35068155196` completed
`failure`: "Enforce gate outcome" rejected the run (`results/gate-exit-code.txt` non-zero).
No CI logs/artifacts were downloadable without repo-admin auth (`gh` unavailable,
`actions/jobs/.../logs` and the artifact zip both returned 401/403), so this was
root-caused by re-reading the actual production code paths the CI gate exercises (the real
run against `emotion_v2` under `analysis/policies/ci_core_v1.json`, `--html-only`, which
still renders `template_v3.html`) rather than log inspection. Found two real bugs:
1. The new model/tokenizer-revision template code assumed
   `identity.declared.model_id`/`model_revision` (the shape in
   `tests/fixtures/stage3/expected_analysis_v3.json`, which is NOT what
   `analysis.analyze.build_identity_block` actually returns) instead of the real
   `identity.model.{model_id,revision,tokenizer_id,tokenizer_revision}`. Local tests passed
   only because they were run against the same mismatched fixture; a real analysis document
   crashed the renderer under Jinja `StrictUndefined`.
2. `_applicable_limitations` gated the V2-hardening note on evaluation `kind == "paired"`,
   which wrongly stripped it from the CI gate's own `ci.emotion` evaluation — `"kind":
   "single"` in `endpoint/targets.json` (it tests `emotion_v2` alone against an approved
   clean-output reference, no live V1), but still genuinely about a hardened target.
Fixed both (see commit `a45de6d3a86ce578d49abaaaddbeb313512394a1` below) and added
regression tests tying the template's identity assumption directly to
`build_identity_block`'s real return shape, and a `_applicable_limitations` test using
`emotion_v2`/`"single"` kind matching the real `ci.emotion` shape exactly, so this class of
mismatch cannot recur silently. Re-ran the full focused suite (**370 passed**), fetched
(origin unchanged at `31723ee`), committed as `a45de6d3a86ce578d49abaaaddbeb313512394a1`
(`fix(v6.2): use the real identity.model shape and gate on hardened targets`), pushed
(`31723ee..a45de6d`). GitHub Actions run `35069400992` completed **success**; "Deploy tested
release to Hugging Face Space" `skipped`. PR #11 confirmed open, draft, unmerged. Hugging
Face `space` remote was never touched at any point in this session.

**Final v6.2 SHA: `a45de6d3a86ce578d49abaaaddbeb313512394a1`.**

Lesson for future sessions: `tests/fixtures/stage3/expected_analysis_v3.json`'s per-target
`identity` block does not match `analysis.analyze.build_identity_block`'s real output shape
(it has `declared.model_id`/`model_revision`; the real function puts model info in a
sibling `identity.model` key with `revision` not `model_revision`). Do not add new
template/report code that reads `summary.identity.*` based on this fixture alone --
cross-check against `analysis/analyze.py`'s actual construction first. This is a
pre-existing fixture/reality drift, not something this session's scope authorized fixing in
the fixture itself.

# RED LAB v6.3 — multi-target master technical report

2026-09-16T12:40:00+04:00, Claude Sonnet 5, Asia/Dubai. Same worktree
`C:\Users\ahsan\OneDrive\Desktop\stage3-ahsan`, branch `stage3/ahsan`. Observed pre-work
HEAD `78188adbdcb4449429116af3161a032516d38aa8`, matching the user-stated required starting
HEAD exactly. Base `stage3/integration` confirmed at
`40ceef06cfecd10fb34ab53c5e41de35cd694ae8`. PR #11 remains open, draft, unmerged. The main
integration checkout's uncommitted `HANDOFF.md` was not touched. User authorized this scope
in the V6.3 milestone brief (2026-09-16); the message arrived truncated mid-section-F and
was completed in a follow-up message before any code was written.

## Real evidence gathered (no fixtures used as proof of a real evaluation)

Located and reused as-is, unmodified: `artifacts/verified_full_report/` and
`artifacts/benchmark_v6/` (historical emotion.core, 1928/1928 both endpoints, V1 1370
eligible/218 flips/29 findings, V2 1373 eligible/112 flips/14 findings — confirmed by
reading `artifacts/verified_full_report/analysis.json` directly, not restated from memory).

No committed, hashable evidence existed for sentiment.core, emotion.oces or sentiment.oces
(the only prior sentiment.core run, Rayyan's `results/task2-full-sentiment-core/`, is
real but lives under gitignored `results/` and was not present in this worktree; OCES
runtime loading was blocked as of the Task 1 handoff). All required models were already
cached at their pinned revisions (`huggingface_hub.scan_cache_dir` confirmed
`emotion-english-distilroberta-base@0e1cd914e3d4` and
`distilbert-base-uncased-finetuned-sst-2-english@714eb0fa89d2`), so per the brief's
"rerun only if real evidence does not already exist" instruction, this session ran each
missing evaluation for real, once, against live local endpoints, at this commit:

| Evaluation | Command | Real result |
| --- | --- | --- |
| `sentiment.core` | `python -m run_all --mode full --evaluation sentiment.core --html-only --no-open --run-name v63_real_sentiment_core` | 1931/1931 completed; 1604 eligible, 99 flips (6.17%); 18 findings; 85 unhandled 5xx, 1 timeout |
| `emotion.oces` | `... --evaluation emotion.oces ...` | 63/63 both endpoints (21 seeds + 42 attacks); 18 eligible, 0 flips, 0 findings on both `emotion_v1`/`emotion_v2` |
| `sentiment.oces` | `... --evaluation sentiment.oces ...` | 60/60 (20 seeds + 40 attacks); 28 eligible, 2 flips, 2 findings |
| `ci.emotion` (local reproduction) | `python -m runner.gate --policy analysis/policies/ci_core_v1.json --out results/gate --results-root results/gate-runs --run-name v63-local-78188ad --html-only` | outcome `pass`, exit 0, 162/162 selected, 13/13 checks pass |

Every run's `run_identity.app_commit` recorded `78188adbdcb4449429116af3161a032516d38aa8`
independently (not asserted by hand). OCES tier/composition figures (0 GOLD, 50 SILVER, 32
REVIEW of 82; 42 emotion + 40 sentiment variants) were read directly from
`attacks/data/oces/oces_review_sheet.csv`'s `proposed_tier`/`task` columns, not restated
from the brief. The `ci.emotion` local run is an honest reproduction, not a downloaded copy
of the cited GitHub Actions run — this session has no `gh`/API access, so run `35069693601`
(user-stated V6.2 final success) is cited by number only in the report, never hashed as if
its artifact bytes were present.

Each real run was copied byte-for-byte (never hand-edited) into a new committed evidence
bundle with its own generated `PROVENANCE.md` and hash sidecar: `artifacts/sentiment_core_v1/`,
`artifacts/emotion_oces_v1/`, `artifacts/sentiment_oces_v1/`, `artifacts/ci_gate_evidence_v1/`.
Selected hashes (full lists in each bundle's `PROVENANCE.md`/`provenance.json`):
sentiment.core `analysis.json` `7847d2c4bbd6cca7…`; emotion.oces `analysis.json`
`cb6d9c3531d60b05…`; ci.emotion `gate_result.json` `e20f158da1d5b914…`;
`analysis/policies/ci_core_v1.json` (frozen, untouched) `e4cb0a86a3590037…`.

## Master evidence manifest and generator

`report/master_evidence/manifest.json` (new, Ahsan-owned) lists 18 real sources by repo
path + SHA-256, plus one explicit external citation (the GitHub Actions run, marked
`external_citation_unverifiable`, no path/hash) and three explicit not-applicable notes
(no sentiment V2 comparison, emotion.core revision not independently attested by the
historical run itself, zero OCES GOLD cases). `report/master_report.py` (new) re-hashes
every listed file at generation time and raises `EvidenceIntegrityError` — refusing to
write any output — on a missing or modified file; verified with both a missing-file and a
modified-bytes case in `tests/test_master_report.py`, and manually by appending a byte to
`artifacts/sentiment_core_v1/analysis/analysis.json` and confirming generation failed
closed (exit 1), then restoring the original bytes and regenerating cleanly. All
quantitative claims in the rendered report are read from these JSON/CSV files in
`report/master_report.build_context`, never hardcoded in the Jinja template.

## Report route and content

`report/master_template.html` (new) reuses the existing detailed report's sidebar
structure verbatim (fixed/collapsible `<aside>`, grouped `toc-nav`, scrollspy/active-state
JS, `report/style.css` classes) rather than a redesign. `run_all.TECHNICAL_REPORT_DIR` =
`artifacts/technical_report/` (same pre-generated/committed pattern as
`VERIFIED_FULL_REPORT_DIR`, never regenerated by the running app); `web/app.py` mounts it
at `/technical-report/` with `html=True`. The three "Technical Report" nav links in
`web/templates/index.html`/`lab.html` now read a new `technical_report_href`/
`technical_report_available` context pair instead of `verified_full_href`; `/verified-full/`
itself is untouched (confirmed byte-identical: `analysis.json` still hashes to
`12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`, `report.pdf` to
`0853108d4939bab1ff2069a1e3dc42b8ad68b14096d12cfd1bfa81fbb56718ca`, and its `report.html`
still reads "Red Lab v5.0"). No master PDF button is present or linked anywhere in the new
template (V6.4 scope). `report/generate.py`'s `PRODUCT_VERSION_LABEL` is now
`"Red Lab v6.2"` → `"Red Lab v6.3"`; `report/master_report.py` reuses that same constant
rather than a second copy.

Sections implemented per the brief: A Executive Overview, B System Architecture
(paired emotion V1/V2 vs. single-target sentiment vs. schema-v3-is-a-data-format
distinctions), C Evaluation Matrix (all five real target IDs/suites/models/purposes read
from `endpoint/targets.json`), D Emotion Core Results (historical figures + resolved/
persisting-finding narrative, links to `/verified-full/`, never rewritten), E Sentiment
Core Results (real 1931/1604/99/18 counts, explicit `comparison: null`, never reusing
1928), F OCES (plain-language explainer before the acronym, explicit "not an external or
blind holdout" disclosure, real 0/50/32 tier counts and 42/40 variant counts), G
Evidence-Specific Findings and Remediation (four named-key real finding examples across
endpoint-layer/model-sensitivity/sentiment-single-target buckets, each with
observed/why-it-matters/action/verify; diagnostic bucket is a narrative note, per contract,
since diagnostic cases are never scored findings), H CI Release Gate (plain-language
exit-code table, real local 13/13-check pass, explicit developer/maintainer audience and
"working reference implementation, not universal certification" framing), I Reproducibility
and Provenance (real app commit, both model identities, policy identity, OCES generator
version `1.2.1` read from the run's own `oces_freeze_content_hashes.json`, evidence-vs-
report-generation distinction), J Limitations (all eight required disclosures).

## Focused validation (this session's own results; no historical claim restated as current)

- `tests/test_master_report.py` (new, 14 tests): manifest hash verification against real
  committed evidence, fail-closed on missing/modified evidence, all five evaluation
  identities present, emotion paired with real 1370/218/1373/112 figures, sentiment single
  with no V2 claim and real 1931/1604 figures, OCES honesty disclosure and 0/50/32/42/40
  counts, CI exit-code table, no PDF button, `Red Lab v6.3` branding, sidebar anchors all
  resolve, quantitative claims traced to `build_context` (not template text).
- `tests/test_web.py` (3 new: technical-report route serves, no PDF button, verified-full
  bytes+branding unmodified; 1 rewritten: nav link now asserts `/technical-report/`; 2
  version-string bumps): **59 passed**.
- `tests/test_report.py` (4 version-string bumps to v6.3): unaffected otherwise.
- Combined `tests/test_master_report.py tests/test_web.py tests/test_report.py
  tests/test_lab.py tests/test_run_all.py tests/test_gate.py
  tests/test_analysis_identity.py`: **387 passed**, 1 pre-existing Starlette deprecation
  warning.
- `git diff --check`: clean (only pre-existing LF/CRLF autocrlf notices on the two touched
  test files).
- Local smoke test: started `uvicorn web.app:app` on a scratch port; `/` 200 with
  `<a href="/technical-report/">Technical Report</a>`; `/lab` 200; `/technical-report/` 200
  with `Red Lab v6.3`/`MASTER TECHNICAL REPORT`; `/technical-report/master_report.py` 404
  (no source exposed); `/verified-full/analysis.json` served bytes hash to
  `12d47b35c700c6…` over HTTP, matching the recorded historical value; server process
  stopped and confirmed unreachable afterward.
- Did not run: the full pytest suite, Playwright, Docker, CI-policy regeneration, PDF
  generation, or deployment (all out of scope per the brief).

Code was validated, then the explicit file list below is staged and committed as
`feat(v6.3): add multi-target master technical report`. Immediate next action is
fetch/verify/push (below).

## Explicitly deferred to v6.4+ (per the brief — do not start)

Master technical-report PDF and its pagination/print-layout refinement; freezing the final
master report bundle; broad website UI redesign; mobile/responsive redesign; Docker
rebuild; deployment; final Red Lab v7.0 branding.

Next: fetch origin and confirm `origin/stage3/ahsan` is still `78188ad` (unchanged since the
last v6.2 push) before pushing this commit, push normally (no force), observe the one
automatically triggered gate run, confirm its deploy job is skipped, and leave PR #11 draft
and unmerged. Do not touch Hugging Face.

**v6.3 closed out.** Committed as `80bee02de661a9400f27fbeac90b67b8d853a3f2`
(`feat(v6.3): add multi-target master technical report`). `origin/stage3/ahsan` had not
advanced (still `78188ad`) at push time; pushed cleanly (`78188ad..80bee02`). GitHub
Actions run `35075844725` ("Stage 3 release gate", PR #11) completed **success** (checked
via the public, unauthenticated GitHub REST API — no `gh`/token available in this session);
its "Deploy tested release to Hugging Face Space" job was `skipped`. PR #11 confirmed open,
draft, unmerged via the same API. Hugging Face `space` remote was never touched at any
point in this session.

# RED LAB v6.4 — master report review, PDF, and a reproducible bundle

2026-09-16T14:10:00+04:00, Claude Sonnet 5, Asia/Dubai. Same worktree
`C:\Users\ahsan\OneDrive\Desktop\stage3-ahsan`, branch `stage3/ahsan`. Observed pre-work
HEAD `91c4d7fdd23ad6e14cdd5dead6f65464059a1895`, matching the user-stated required starting
HEAD exactly. The main integration checkout's uncommitted `HANDOFF.md` was not touched.
User authorized this scope in the V6.4 milestone brief (2026-09-16). Checked the later
docs-only workflow run (`35076099520`, on the v6.3 handoff-closeout commit) once via the
GitHub REST API: `completed`/`success` — no failure to root-cause.

## Real browser review (this session installed a local Chromium/Playwright browser)

No browser binary existed in this environment before this session (matches the
pre-existing "27 skipped, Playwright not available" note in earlier handoffs).
`python -m playwright install chromium` downloaded both the headless-shell and full
Chromium builds locally (nothing committed; browser binaries are not repository
artifacts). Used it to load the live `/technical-report/` page and the rendered
`report.pdf` and drive/inspect both directly, not just read the template source.

**Real defect found and fixed: sidebar navigation silently failed on the last section.**
Clicking any sidebar link except the final one (`#historical`) worked; clicking
`#historical` moved the page but left `#limitations` marked active. Root cause, found by
instrumenting the live page: `master_template.html`'s `window.rlOnInternalNav` assigned
the clicked link to a **local** `var clicked` instead of the outer `clickedLink` closure
variable the scrollspy's `updateActive()` actually reads, so "clicked" state was never
truly sticky — it only *looked* correct for other sections because the intersection-based
autodetection happened to agree with the click there too. Fixed by assigning to
`clickedLink` directly (one line); added a regression test
(`tests/test_master_report.py::test_sidebar_click_sets_active_state_for_every_link`) that
greps the template source for the exact bug pattern, plus re-verified all 11 sidebar links
live with the real browser after the fix.

**Real defect found and fixed: a double-escaped HTML entity rendered as literal text.**
The provenance evidence table's fallback for a source with no evaluation id was
`{{ src.evaluation_id or '&mdash;' }}` — Jinja's autoescaping HTML-escapes the fallback
*string value* itself, so the page showed the literal text `&mdash;` instead of an em
dash. Fixed by using the real Unicode character instead of an HTML entity string.

**Content gap found and fixed: OCES's 0/0 scored rate was omitted, not misrepresented.**
All three OCES target summaries (`emotion_v1`, `emotion_v2`, `sentiment_v1`) have
`violation_rate: {numerator: 0, denominator: 0, rate: null}` — no case in the current seed
set produced a `meets_expectation`/`violates_expectation` outcome (the rest are
pre-registered `excluded`/`unevaluable`). The V6.3 report never rendered this metric at
all, so there was no *wrong* percentage shown, but the brief specifically asked for the
denominator and an explanation to be visible. Added `oces_scored_note` to each OCES target
context (`report/master_report.py`), rendered under each target's counts, reading e.g.
*"0 of 0 cases produced a scored expectation outcome — no violation rate is available to
report (20 excluded, 22 unevaluable, 0 not executed, per the pre-registered oracle
rules)."* Regression test added; asserts `"0% failure"`/`"100% success"`/`"0.00%"` never
appear near the OCES section.

**Citation refreshed, not just re-worded.** The CI-gate section cited GitHub Actions run
`35069693601` (the v6.2-era run). This session directly confirmed via the GitHub REST API
that run `35075844725` (the actual gate run for this V6.3→V6.4 line of commits) completed
`success` with its deploy job `skipped` — a more current and more directly-verified
citation for "latest successful gate evidence." Updated the citation in both
`report/master_report.py` and the manifest's `external_citations` entry; still marked
`external_citation_unverifiable` (no artifact bytes downloaded) and still clearly
distinguished from the local `ci.emotion` reproduction bundle.

**Pre-existing rendering quirk observed, not fixed:** in both the new PDF and the frozen,
byte-unchanged `artifacts/verified_full_report/report.pdf`, Chromium's PDF viewer shows
the masthead logo failing to decode (WeasyPrint logs `Failed to load image` for the
embedded PNG, which carries C2PA/JUMBF content-credentials metadata) and its alt text
overlapping the adjacent brand text. Confirmed side-by-side against the historical PDF
before treating this as a defect — it is identical in both, pre-dates this milestone, and
is out of scope (would require changing `Team Checkmate Logo.png`, a shared brand asset,
not a report-generation change). Documented here rather than silently ignored.

All other review checklist items passed as-is: all ten A–J-plus-historical sections have
substantive content (63–1405 words each, `oces`/`remediation` heaviest); the five
evaluation identities, emotion-paired/sentiment-single framing, and historical-vs-current
attribution were already correct from V6.3; every `<a href>` on the page resolves (checked
programmatically); findings' "How to verify the fix" commands reference real result paths
recorded in the committed evidence bundles.

## PDF generation

`report/master_report.py` now renders `report.pdf` from the exact same HTML string as
`index.html` (not a second, possibly-diverging render), via `report.generate.render_pdf`
(same WeasyPrint call the historical report already used — no new rendering path).
`master_template.html` gained a masthead "Download PDF → " link, shown only when
`include_pdf` is true (`html_only` generation, used by the fast test fixture, omits both
the file and the link, matching the live-demo reports' own PDF suppression). 19 pages at
A4 (confirmed via WeasyPrint's own `Document.pages`), reusing `report/style.css`'s
existing `@media print` rules almost entirely as-is (the sidebar/`.report-toc` is already
print-hidden, `.report-section` already breaks one-per-page, `.panel`/`.v3-finding`/
`.v3-mini-card` already avoid splitting) because the master template deliberately reuses
that same class vocabulary — no new print CSS was needed. Visually reviewed page-by-page
in a real PDF viewer (Chromium via Playwright): clean pagination, page-number footer,
readable tables (SHA-256/model-identity columns wrap via the existing generic
`overflow-wrap: anywhere` table-cell rule), finding cards with expanded evidence-case
lists, and the historical section clearly labeled "ARCHIVED EVIDENCE" on its own final
page. Live-demo/CLI reports (`template_v3.html`, `demo_template.html`) are untouched and
still have no PDF button — the new masthead link exists only in `master_template.html`.

## Freezing the bundle and its reproducibility limit

Promoted the evidence-manifest builder from an ephemeral scratch script (used ad hoc in
V6.3) into a committed, maintainable generator: `report/master_evidence/build_manifest.py`
regenerates `report/master_evidence/manifest.json` (still 18 real sources, all hashes
unchanged except the refreshed CI-run citation) from on-disk evidence every time it runs —
confirmed by a regression test that it reproduces the exact committed manifest.

`report/master_report.generate()` writes a **separate** final bundle manifest,
`artifacts/technical_report/master_evidence_manifest.json` (not self-referential: it
records `rendered_index_sha256`/`rendered_pdf_sha256` for the two files it just wrote, and
does not hash itself). Verified:

- The 18-source evidence manifest still passes `verify_manifest` in full (fail-closed
  behavior re-tested with a fresh missing-file and modified-bytes case, both real).
- `index.html` regenerated from identical evidence is **byte-identical** across separate
  runs (new test, `test_html_regeneration_is_byte_identical_across_runs`).
- `report.pdf` is **not** byte-reproducible. Verified directly, not assumed: rendering the
  identical HTML twice — including across separate Python processes with
  `PYTHONHASHSEED` fixed to `0` — produced two PDFs differing in length and every byte
  from offset 54472 onward, inside a compressed `FlateDecode` content stream. This
  build's PDFs carry no `/CreationDate`/`/ModDate` at all (checked directly), ruling out
  the usual timestamp-metadata explanation; the divergence is consistent with
  non-deterministic internal serialization (most likely font-subsetting order) inside
  WeasyPrint/pydyf, not this project's own code. `master_evidence_manifest.json` records
  this limit in a `pdf_reproducibility_limit` field rather than implying the hash is
  reproducible.
- `/technical-report/` serves both `index.html` and `report.pdf` from the committed
  `artifacts/technical_report/` directory (`web/app.py`'s existing `StaticFiles` mount,
  unchanged) — confirmed live: `GET /technical-report/report.pdf` returns
  `200 application/pdf` with real `%PDF-` bytes.

Final committed hashes:

- `artifacts/technical_report/index.html`:
  `e988d1fc986d01c359897c2ec2a0e585b9dbdcd718b58318eca6121de8fba2ff`
- `artifacts/technical_report/report.pdf`:
  `bf2a904c2cfecbcf9cc0d5e856240f7c946f02a87912dea9e791c8d89e052350` (this exact file's
  hash; a fresh regeneration will legitimately differ — see above)

Frozen/historical artifacts confirmed untouched by this session:
`artifacts/verified_full_report/`, `artifacts/benchmark_v6/`, `artifacts/ci_gate_evidence_v1/`,
`artifacts/emotion_oces_v1/`, `artifacts/sentiment_core_v1/`, `artifacts/sentiment_oces_v1/`,
`analysis/policies/`, OCES data under `attacks/data/oces/` and `baseline/oces/`.

## Branding

`report/generate.py`'s `PRODUCT_VERSION_LABEL` bumped `"Red Lab v6.3"` → `"Red Lab v6.4"`;
`report/master_report.py` and `report/master_evidence/build_manifest.py` both read/set
this same value rather than a second hardcoded copy. Archived `/verified-full/` confirmed
still reading `"Red Lab v5.0"` (unchanged).

## Focused validation (this session's own results)

- `tests/test_master_report.py`: **21 passed** (14 carried over from V6.3 plus 7 new:
  html-only has no PDF/link, full generation has a valid multi-page PDF whose hash matches
  the manifest snapshot, the build_manifest generator reproduces the committed manifest,
  HTML regeneration is byte-identical, the OCES 0/0 wording, the CI-citation distinction,
  and the sidebar-bug regression).
- `tests/test_web.py` + `tests/test_report.py` + `tests/test_master_report.py` combined:
  **237 passed** (2 rewritten for the new PDF-button behavior, 1 new live-demo-has-no-PDF
  regression check, remaining version-string literals bumped to v6.4).
- `tests/test_lab.py tests/test_run_all.py tests/test_gate.py tests/test_analysis_identity.py`:
  **158 passed**, unaffected, run as a broader sanity check per the brief.
- `git diff --check`: clean (only pre-existing LF/CRLF autocrlf notices).
- Local browser review: real Chromium (installed this session) driving the live
  `/technical-report/` page (all 11 sidebar links, collapse/expand, console error count
  zero) and the real `report.pdf` (19 pages, page-by-page visual pass, one pre-existing
  non-regression quirk documented above).
- Did not run: the full pytest suite, full model evaluations, OCES evaluations, Docker,
  or CI-policy regeneration (all out of scope per the brief).

Code was validated, then the explicit file list below is staged and committed as
`feat(v6.4): finalize master technical report HTML and PDF`. Immediate next action is
fetch/verify/push (below).

## Deferred to v6.5+ (per the brief — do not start)

Broader visual/UI redesign of the master report; the pre-existing logo-decode PDF-viewer
quirk (would require touching the shared `Team Checkmate Logo.png` asset, out of this
milestone's scope); mobile/responsive polish; Docker rebuild; deployment; final Red Lab
v7.0 branding.

Next: fetch origin and confirm `origin/stage3/ahsan` is still `91c4d7f` (unchanged since
the v6.3 docs-closeout push) before pushing this commit, push normally (no force), observe
the one automatically triggered gate run, confirm its deploy job is skipped, and leave
PR #11 draft and unmerged. Do not touch Hugging Face.

**v6.4 closed out.** Committed as `920a6caa048406fd33652c8c0149ceec548ce722`
(`feat(v6.4): finalize master technical report HTML and PDF`). `origin/stage3/ahsan` had
not advanced (still `91c4d7f`) at push time; pushed cleanly (`91c4d7f..920a6ca`). GitHub
Actions run `35082203070` ("Stage 3 release gate", PR #11) completed **success** (checked
via the public, unauthenticated GitHub REST API); its "Deploy tested release to Hugging
Face Space" job was `skipped`. PR #11 confirmed open, draft, unmerged via the same API.
Hugging Face `space` remote was never touched at any point in this session.

# RED LAB v6.5 — homepage/lab/report content and layout corrections

2026-09-16 15:53 +0400. Branch `stage3/ahsan`, worktree `stage3-ahsan`, starting HEAD
confirmed at the v6.4 closeout commit `71bc7d8bd5fac3bd3c195e7e5c7f40baaf0b46d0` with a
clean tree before any edits. Six focused corrections requested as the last pass before
Ahsan's local functional acceptance; v7 (broader UI redesign) explicitly deferred.

**1. Homepage (`web/templates/index.html`, `web/static/app.{css,js}`).** Deck copy rewritten
to state both classifiers accurately (paired emotion V1/V2 vs. standalone sentiment, no
sentiment_v2 implied anywhere). The hero statement is now a 3-message rotator (`#hero-
statement` + `.hero-statement-line`, one `.is-active` at a time) stacked in one CSS grid
cell so swapping the active line never resizes the container -- no layout jump -- and
`prefers-reduced-motion: reduce` visitors get a static first line (verified: `setInterval`
never starts). The V1/V2 hardening badges (`#hero-control-paired`) now hide behind a
single-target badge (`#hero-control-single`) when sentiment is selected, driven by
`updateModelCopy()`. "View Technical Report" moved into the same three-column
`.hero-actions` row as the other two CTAs (was a separate button below); vertical rhythm
across the whole hero (padding, logo size, statement/deck font sizes, gaps) was tightened
so all three actions clear the fold at both 1366x768 and 1920x1080 with room to spare --
verified with a real Chromium browser (Playwright, headless, real viewport sizes, bounding-
box measurement, see below). A 1080px breakpoint steps the row down to 2+1 before the
existing 760px single-column mobile layout; mobile keeps the full copy/animation/logos/
three actions per the brief (no one-screen mobile requirement).

**2. Technical-report sidebar (`report/style.css`, `report/master_template.html`).** The
fixed 280px sidebar column used to stay a grid column all the way down to the 760px phone
breakpoint, crowding the report body at ordinary "narrower window" or higher-zoom desktop
widths. `--report-toc-width` is now `clamp(220px, 21vw, 280px)` (shrinks gracefully instead
of a hard cliff), and the sidebar's collapse-to-drawer behavior was extracted from the
760px media query into its own `@media (max-width: 1024px)` block (same drawer markup/CSS,
wider trigger). The inline scrollspy script's `isMobile()` and its resize listener were
updated from 760px to 1024px to match, so drawer inert/focus-trap/auto-close behavior never
desyncs from what's actually visible. Verified via real browser at 1440px (normal fixed
sidebar), 900px and 800px (drawer with working toggle), and confirmed the v6.4 scrollspy
fix still holds: clicking the first (`#overview`) and last (`#historical`) sidebar links
both correctly set `.is-active` on the clicked link.

**3. Live-demo results alignment (`report/template_v3.html`, `report/style.css`).** The
per-evaluation header (eyebrow "CORE · PAIRED", the `evaluation_id` heading, and the task/
target detail line) were three direct children of a plain `.section-heading` flex row with
no wrap -- fine for master_template's two-child layout, but here it just crammed a 29px
heading against two small caption lines with no wrap at narrow widths. Added a
`.v3-eval-heading` modifier class (`flex-wrap: wrap; align-items: baseline`) plus a
`.v3-eval-detail` class on the trailing line so the three pieces share one row when space
permits and wrap onto their own lines in order otherwise -- verified visually at 1366px
(one row) and 500px (label+identity, then detail line on its own row, no overlap). Applies
identically to emotion and sentiment since both render through the same template.

**4. Limitations sections removed (`report/master_template.html`, `report/template_v3.html`,
`report/master_report.py`).** Removed the "Limitations" heading, its TOC entry, and its
rendered `<ul>` from the current master technical report, and the equivalent section from
the schema-v3 live-demo report template (shared by emotion and sentiment runs). The
`master_report.py` `context["limitations"]` list (8 hand-written bullets) was deleted
entirely since nothing renders it any more. The frozen per-summary/per-report `limitations`
field in the analysis JSON contract itself was **not** touched -- schema validation in
`report/generate.py` still requires it; only the template's rendering of it changed. Checked
that every fact worth keeping already lives elsewhere and still renders: OCES provenance
("authored by this team after the evaluated defenses were already frozen") in section F,
the OCES 0/0 scored-outcome wording (`oces_scored_note`, unchanged from v6.4) in D/E/F,
sentiment's single-target identity in sections E/F, and the CI gate's one-candidate scope
note in section H. `/verified-full/` (schema v2, frozen V5 archive) was not touched --
confirmed via `test_technical_report_verified_full_bytes_unmodified` (byte-for-byte hash
check, still passing).

**5. Try Your Own Input page (`web/templates/lab.html`, `web/static/{app.css,lab.js}`).**
`.model-picker`'s own `margin: 0 auto` (needed to center it on Home's centered hero) was
centering it as a narrower island inside `/lab`'s left-aligned form, disconnected from the
textarea directly below it. Added `.lab-editor .model-picker { max-width: none; margin: 0
0 20px; }` so it now sits flush with the "Your sentence" label/textarea (verified: both
start at the same x-coordinate in a live render). The intro deck paragraph and the V1/V2
badge row were static regardless of selection, so selecting sentiment still visually
implied a V1/V2 hardening comparison; both now toggle via `updateModelJourney()` the same
way the existing caption/model-identity text already did -- sentiment gets its own
single-target copy and an `id="lab-hero-control-single"` badge instead of inheriting
emotion's paired-comparison wording and badges.

**6. Versioning.** `report/generate.py`'s single-source `PRODUCT_VERSION_LABEL` bumped
`"Red Lab v6.4"` → `"Red Lab v6.5"` (read by both `web/app.py` and `report/master_report.py`
via `MASTER_REPORT_VERSION_LABEL = PRODUCT_VERSION_LABEL`); `report/master_evidence/
build_manifest.py`'s `REPORT_IDENTITY.product_version_label` bumped the same way, then
`python -m report.master_evidence.build_manifest` regenerated `manifest.json` (diff is
exactly the one label line -- all 18 evidence source hashes unchanged, confirmed via
`git diff`). `python -m report.master_report` regenerated `artifacts/technical_report/
index.html` + `report.pdf` + `master_evidence_manifest.json` from that manifest. As with
v6.4, PDF byte-reproducibility is **not** claimed -- only the content/manifest hash of this
specific committed `report.pdf` is recorded, consistent with the already-documented,
already-verified WeasyPrint/pydyf non-determinism.

**Final bundle (this milestone):** `rendered_index_sha256`
`b54ac78d7a2c139153503345790a2101739262ae38656881f49524b2c7de7297`,
`rendered_pdf_sha256`
`f0b04ccc7626fd4f9aec3eb3ac1482eba672b89d1c1f4c58b09cb634ca320cc2`,
PDF page count **18** (down from v6.4's 19 -- the removed Limitations section was one full
page under the print CSS's per-section page break; confirmed no orphan blank page at the
old boundary or after the new final page via a real Chromium PDF-viewer render).

**Validation by this Claude session:** `tests/test_master_report.py` (23, incl. 2 new: no-
Limitations-but-facts-survive, sidebar-breakpoint-css-and-script-agree) +
`tests/test_report.py` (158, incl. 1 new alignment test + 1 rewritten no-Limitations test)
+ `tests/test_web.py` (65, incl. 5 new: three-actions-one-row, hero-statement-rotates,
hero-control-badges-switch, lab-model-picker-left-aligned, lab-intro-copy-and-badges-
switch) = **245 passed**. `git diff --check`: clean (only pre-existing LF/CRLF autocrlf
notices, no real whitespace errors). Real-browser verification (Playwright + the same
locally-installed Chromium from v6.4, not committed): homepage at 1366x768 (all three CTAs
fit, no scroll needed to reach them), 1920x1080 (fits with large margin), a narrow-desktop
900px window (orderly 2+1 stepdown, all three fit), and a 390px mobile viewport (stacks
correctly, third action scrolls into view as expected/allowed); hero rotation confirmed to
advance after 5.5s under normal motion and stay pinned on the first message under
`reduced_motion="reduce"`; sentiment selection confirmed to swap both the homepage and lab-
page badges/copy live; `/lab` model-picker confirmed pixel-aligned with the textarea;
`/technical-report/` sidebar confirmed to switch from fixed column to drawer between
1024px and 900px, and the drawer opens/closes correctly; the regenerated `report.pdf`
opened in Chromium's real PDF viewer, 18 pages, no clipped/overlapping content, no orphan
blank page. Did not run the full pytest suite, model evaluations, OCES evaluations, Docker,
or CI-policy regeneration (out of scope per the brief; only the listed focused suites ran).

**Not done in this milestone (explicit scope boundary):** commit is local only on
`stage3/ahsan` -- not pushed, so no CI gate run to observe this time (the brief's final ask
was the commit SHA and a locally-reviewable diff, not a push/CI cycle; push on request).
v7 (broader visual/UI redesign) not started. Hugging Face untouched. `/verified-full/` V5
archive untouched (byte-verified). PR #11 unaffected (still draft, unmerged).
