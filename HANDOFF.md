# SYSTEM V6 — DEPLOYMENT RELEASE (IN PROGRESS)

2026-09-10, Claude (took over from Codex after its usage limit), Asia/Dubai.
Branch `ahsan/v5-redlab`, starting HEAD `901cc22`. Ahsan's V6 brief approves the V5.5
visuals and authorizes the report-history fix, release hygiene/docs, a new V6 commit,
a release-branch GitHub push, an exact-snapshot upload to the existing HF Space while
Protected, real local/container/cloud/mobile acceptance, then Public visibility and an
annotated `v6.0.0` tag. No merge, no V5.5 amendment, no redesign, no core/benchmark change.

## V6 work completed and verified locally

- **Report history fix.** `report/template.html`: every internal `a[href^="#"]` now
  scrolls the target into view and calls `history.replaceState`, so sidebar/rubric/finding
  navigation updates the deep-link hash without pushing page-history entries. Modified
  clicks (ctrl/meta/shift/alt/middle) keep native behaviour. Scrollspy, `aria-current`,
  the mobile drawer and Evidence/Audit ordering are unchanged; the generic Back control
  was not touched.
- **Report entry links now open in the same tab** (`web/templates/index.html`,
  `web/templates/lab.html`, `report/demo_template.html`). Required by the brief's
  Results -> Report -> Back requirement: a new tab has no previous page to return to.
  Source JSON keeps its new-tab behaviour. No visual/layout change.
- Verified report HTML re-rendered from the template (`artifacts/verified_full_report/
  report.html`, `export_meta.json`). `analysis.json` and `report.pdf` untouched.
- README deployment section updated to Red Lab V6 / `red-lab-v6:latest`.
- Tests: 5 new desktop/mobile/direct-entry report-history cases in
  `tests/test_ui_browser.py`; `tests/test_web.py` entry-link expectation updated.

Validation (all by this checkout, evidence in ignored `results/`):
- Full suite **604 passed, 1 pre-existing deprecation warning, 84.71s** —
  `results/v6-final-tests.txt`.
- Real local acceptance PASS — `results/v6-local-acceptance/summary.json`.
  Demo -> Results -> Report -> `#remediation`/`#provenance`/`#v2-findings` ->
  Back returns to Demo Results with `history.length` constant; second Back reaches Home;
  mobile drawer flow returns to Home; Custom reload/Test Another; CUSTOM -> DEMO -> CUSTOM;
  active-Demo rejoin keeps the same run_name; no stale completed execution view.
- Docker `red-lab-v6:latest` built with cached apt/pip/model layers
  (`results/v6-docker-build.log`); container acceptance PASS with six 200 routes and
  real CUSTOM -> DEMO -> CUSTOM (`results/v6-docker-acceptance.json`).
- Hygiene: no tracked `results/`, temporary scripts, logs, caches or credential-shaped
  values (`results/v6-hygiene.json`). Absolute paths appear only in intentional
  redaction fixtures in `tests/test_analysis*.py` and are retained.
- No orphan endpoint processes or 8000/8001 listeners after local and container runs.
- Integrity, before and after all V6 work:
  `analysis.json` `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da`,
  `report.pdf` `0853108d4939bab1ff2069a1e3dc42b8ad68b14096d12cfd1bfa81fbb56718ca`.
  No benchmark rerun; contract/endpoint/attacks/analysis frozen paths unchanged.

## Remotes and deployment state

`origin` https://github.com/AminMaleh03/adversarial-redteam-toolkit-team-checkmate.git ;
`space` https://huggingface.co/spaces/ahsan-141117/team-checkmate-adversarial-redteam-toolkit.
HF authentication verified as `ahsan-141117`. Space pre-deployment: sha `b11bf79`,
`private=True` (Protected), stage RUNNING — that is V4. Deployment method: `git archive`
of the exact release commit plus authenticated `huggingface_hub.upload_folder`, then a
remote tree hash check (raw HF git protocol-v2 fetch is known to fail here).
Operator: ignored `results/v6_hf_release.py`.

## Cloud deployment defect found and fixed (2026-09-10, Claude)

First V6 upload (`dc60422` -> Space `f8841e2`) built and started cleanly, but the
anonymous smoke check caught the served `/verified-full/analysis.json` hashing to
`8a950cad...` instead of the published `12d47b35...`. Root cause: this checkout has
`core.autocrlf=true` and the repo has no `.gitattributes`, so `git archive` rewrote
text blobs to CRLF. The content was identical; the bytes, and therefore the published
evidence hash, were not. `report.pdf` (binary) was unaffected.

Fix: the release operator now runs `git -c core.autocrlf=false -c core.eol=lf archive`
and asserts every file in `export_meta.json` still hashes to its recorded value before
uploading. Repo-level regression guard added in `tests/test_web.py`:
`test_verified_full_served_bytes_match_recorded_evidence_hashes` asserts the bytes the
app actually serves hash to `export_meta.json`. Suite now **605 passed** in 56.72s.

Next: push the V6 commit to `origin`, upload the same snapshot to the Space while it
stays Protected, then cloud smoke/functional/mobile acceptance, Public visibility and
the annotated `v6.0.0` tag.


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
