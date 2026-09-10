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
