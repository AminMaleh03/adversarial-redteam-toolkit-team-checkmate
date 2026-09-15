# Rayyan Task 2 checkpoint

Updated 2026-09-15T16:39:09+04:00, Codex, Asia/Dubai. Active assigned branch **stage3/rayyan**.
Observed HEAD **8c5b42c631a917642b5f4b4a5ee68227ce7fa58c**.
User reiterated stage3/rayyan only; stage3/rayyan-windows was agent-created locally,
is superseded, and will not be pushed. Khalid's branch remains preserved.

## Objective and authorization

Finish Rayyan Task 2 only. Attached starting/delivery instructions authorize commit,
push only stage3/rayyan, PR base stage3/integration, Ahsan reviewer, no self-merge.
Our changes: Rayyan code/tests/docs plus this required shared checkpoint. No Khalid
analysis edits. The incoming branch already edited Ahsan-owned foundation tests;
we did not edit that file and disclose it in the handover/PR.

## Completed and verified

- Earlier fixes fc8560c (runner/endpoint), f60697c (gate), 69db5b6 (documentation).
- 9d75993: exact coverage-map snapshot/hash, reusable paired planning, tokenizer
  context validation. 8c5b42c: gate CLI errors write error artifacts.
- `.\.venv\Scripts\python.exe -m pytest -q tests/test_endpoint.py tests/test_runner.py tests/test_gate.py --tb=short`:
  **230 passed**, no skips, 20.88s.
- `.\.venv\Scripts\python.exe -m pytest -q --tb=short -rs`:
  **841 passed, 30 skipped, 1 failed**, 26.66s. Full log:
  results/task2-rayyan-completion-tests-final.txt. Existing Ahsan foundation test
  line278 asserts fresh import state in shared pytest interpreter; owner must put
  registry isolation assertion in a subprocess. 27 browser and 3 native PDF skips.
- Full real pinned sentiment core: **1931/1931**, zero missing; all received body
  lengths/hashes match sender. 85 recorded 5xx, no timeouts/health/transport failures.
  Runtime43.467s, cached readiness3.457s, service peak working set1138769920B.
- Results/task2-full-sentiment-core/ records source SHAs, raw/meta/map/manifest,
  receiver observations and measurements. Export combines Rayyan8c5b42c and
  Lamei attacks/baseline f619e51, not a single integrated commit. Source in .source
  prevents duplicate pytest discovery; no project files removed.
- Real pinned tokenizer planning proves paired one-build reuse and cross-task
  manifest isolation. Correct sentiment.oces readiness rejects unsupported suite;
  planning_summary.json lists all20seeds+40variants not_executed with exact reason.
  Initial invalid evaluation ID probe retained separately; no OCES predictions.
- Actual final gate missing-policy error writes results/task2-rayyan-final-gate/
  gate_result.json and returns2 to PowerShell. Fixture gates verify0/1/2 only.
- Endpoint V2 and both model pins unchanged. No service/test processes left running.

## Remaining / next step

Review docs diffs, commit documentation, push stage3/rayyan only, open PR into
stage3/integration and request reviewer ahsan-141117 (foundation commit author).
Remote Rayyan remains d55f1e2; integration/Ahsan remain257e15f. Latest Lamei089e54d
only changes handover/tests from validated production snapshot f619e51.
Production/test commits are complete for currently available Rayyan interfaces.
Ahsan orchestration and Khalid frozen policy JSON remain missing; Lamei published
OCES freeze but public build_suite still rejects OCES. Do not implement their
pending components. Ahsan must test exact handover PR head before acceptance.
See [Rayyan handover](docs/stage3/handoffs/rayyan.md) for exact commands, hashes,
cache files, all blockers, real-versus-fixture evidence, and regression demo branch.

## Short history

Foundation257e15f; Khalid handover34b18b5; Rayyan fetched merge d55f1e2 repaired
on this device. Earlier real sentiment smoke26/26 and emotionV2 CI selection162/162
remain in results/task2-windows-sentiment-3 and results/task2-windows-ci. Older
historical Mac claims are labeled separately in Rayyan's handover.
