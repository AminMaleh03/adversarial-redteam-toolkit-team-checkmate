# Task 1 — Ahsan: product integration, reports, CI workflow, deployment and final acceptance

Owner: Ahsan. Implementation and testing may be executed by Claude Code or Codex under Ahsan's direction.

Start after: Task 5 publishes FOUNDATION_READY and the common foundation SHA. Start independent UI/report work immediately using the shared fixtures. Real integration acceptance waits for the actual dependency implementations.

## Objective

Make the four improvements work as one understandable product, verify every branch before acceptance, deliver a real release gate, and publish evidence-backed reports and the final submission. Do not implement another member's production component to work around an interface mismatch.

## Read first and scope

Read CONTRACTS.md, docs/stage3/FINAL_PLAN.md, docs/stage3/FOUNDATION_READINESS.md, the ownership map, and this task. The final plan's corrections supersede the earlier Claude proposal. Keep English-only scope, one sentiment endpoint, two additional-evaluation families, and the bounded CI policy. Do not add uploads, arbitrary endpoint entry, new model modalities or a visual redesign.

## Files you own

run_all.py; web/**; report/**; .github/**; Dockerfile; requirements.txt when a justified common change is needed; top-level project documentation; docs/stage3/**; contract.py and foundation fixture amendments; published artifacts and submission source/output.

Tests: test_run_all.py, test_web.py, test_lab.py, test_report.py, test_ui_browser.py and shared integration tests. Rayyan edits endpoint/runner, Khalid analysis/policy, and Lamei attacks/baselines. Provide requested README/dependency changes centrally so those owners do not collide with you.

## Required implementation

1. Preserve and extend orchestration.
   - Add registry-driven evaluation selection while preserving the old run_experiment positional arguments and original default emotion behavior.
   - Implement the agreed keyword-only evaluation_ids and html_only options and internal CI mode. Keep browser opening CLI-only.
   - Create a collision-safe run_id and directory. Write the run.json index, copied registry/selection snapshots and provenance consistently before presenting results.
   - Consume Rayyan's target-aware runner and Lamei's isolated suite builder. Do not build a different payload set for each half of the emotion pair or accidentally reuse another task's global registry.
   - Preserve partial candidate failures as evidence. Distinguish infrastructure startup/configuration failures. Stop/reap only processes started by this job and free the job lock in finally.
   - Process evaluations sequentially using existing lifecycle helpers. Measure memory; do not claim sequential service startup guarantees one loaded model.

2. Support analysis v3 and historical v2 reports.
   - Accept both schema versions, upcasting historical v2 only in memory.
   - Preserve the nested findings[].finding object, original metrics and historical artifact bytes.
   - Render target summaries independently, comparison only for a valid paired block, and a short single-target explanation when comparison is null.
   - Validate declared families, not a hardcoded six-category set for every suite.
   - Render coverage classes, intended-controls notes, explicit numerators/denominators, common-eligible paired deltas, additional-set outcomes and exposure/freeze information.
   - Render observed evidence -> significance -> fix -> verification for every new finding. Do not reduce it to the old deduplicated generic advice list.
   - Keep no-data, zero-denominator, excluded, unevaluable and not-executed states distinct. A missing new required block is an error, not an empty successful report.
   - Add model-aware HTML/PDF/JSON exports and evidence hashes. The detailed report can exceed five pages.

3. Integrate a simple model/evaluation journey.
   - Add GET /api/targets with only trusted configured choices.
   - Extend POST /api/run, GET /api/status and POST /api/lab/run using Task 5's exact request/response contracts. Preserve the existing empty/default request behavior for emotion.
   - Offer emotion and sentiment core demos and interactive text testing. Additional full evaluations may remain CLI-run, but their frozen real reports must be reachable from the public product.
   - Make unsupported combinations explicit. Preserve existing full execution support; do not remove an existing ability merely because the proposal assumed it was CLI-only.
   - Keep the single global job lock across Demo and Lab; return 409 while busy. Reject unknown targets/modes with the agreed 422 shape.
   - Use run_id plus evaluation identity to reject stale polling responses. Switching model clears prior results and links. Polling a previous run must not overwrite a newly selected view.
   - Preserve interactive input privacy and existing retention behavior; do not include arbitrary user text in committed fixtures or final benchmark evidence.
   - Show clear progress, failure/partial state, target labels and correct downloads. No invented progress percentages or implementation jargon in normal user flows.

4. Create the actual GitHub gate workflow.
   - Invoke Rayyan's gate CLI against the checked-out candidate revision, using Khalid's frozen policy.
   - Verify the selected commit and relevant model revision in outputs. Do not test only the old public Space.
   - Publish gate_result.json, logs, raw evidence, analysis.json and report.html even when a policy check fails, where available.
   - Cache downloads appropriately, but never reuse stale execution outputs as a fresh test. CI may use html_only; final deployment must still produce PDFs.
   - Make the release/deployment job depend on successful gate completion. Publish the tested commit/artifact with the existing hosting method. Configure PRs for checks only and release events for deployment; do not deploy an intentionally regressed PR.
   - Use existing secret/environment controls. If credentials or required settings are unavailable, report the exact missing setup; do not use a placeholder deploy job and call it release enforcement.
   - Required merge protection is distinct from release-job gating. Do not claim merge blocking without actually configured repository rules, and do not depend on Amin.

5. Prove the gate.
   - With Rayyan, use an isolated regression branch removing only V2's length rejection.
   - Freeze policy, selected cases and reference first. Run the real gate and record policy failure with actual case IDs/status evidence.
   - Restore the control and record pass under identical policy/selection hashes.
   - Also verify an unavailable target produces execution_error and exit 2.
   - Preserve both workflow URLs/commit identities. Never merge/deploy the regressed revision or use its outputs as final robustness evidence.

6. Integrate, deploy and update the submission.
   - Verify exact PR/branch SHAs and owned-file boundaries before merge. Sequence v3 analysis and minimum report compatibility together in a tested integration candidate.
   - Bake/cache both pinned models for the existing offline runtime where applicable; include the exact tokenizer assets. Use current dependency pins unless a demonstrated need exists.
   - Run actual container acceptance and then deployed acceptance: original emotion, sentiment, interactive modes, additional-report links, downloads, model switching and repeat run.
   - Measure actual build/startup/runtime/memory behavior and record the environment. Keep a verified previous release and the byte-preserving deployment procedure for rollback.
   - Reconcile HTML, JSON, detailed PDF and the separate competition PDF against final analysis artifacts.
   - Produce the competition PDF within the user-provided five-page/20 MiB limit. Preserve original-versus-new separation and every material limitation.
   - Update README, demo explanation and concise panel preparation notes using what actually ran. No future feature presented as shipped.

## Independent work and dependencies

You can implement validators/templates/UI behavior against the synthetic fixtures before any feature branch lands. Use test doubles only inside tests. Freeze changes to the common schema centrally; never reshape the contract privately in the renderer.

Real checks need Lamei's data/metadata, Rayyan's endpoints/runner/gate and Khalid's analysis/policy. After those arrive, replace fixture evidence with actual runs. A fixture-rendered page is not a completed product demonstration.

## Acceptance checklist

- [ ] Original full/demo/interactive behavior remains available and relevant existing tests pass.
- [ ] Valid v2 and v3 reports render; invalid new documents fail clearly; null single comparison never yields a fake improvement.
- [ ] Emotion -> sentiment -> emotion and a second run show correct, non-stale output and downloads.
- [ ] Additional evaluation and finding-specific advice appear with real evidence.
- [ ] Global locking, failure cleanup, unsupported input and partial-result states work.
- [ ] Real same-policy CI failure, correction/pass and execution-error examples exist.
- [ ] A real release step depends on that check, or the concrete remaining release blocker is explicitly reported.
- [ ] Container and live deployment pass the agreed user journey; byte hashes match downloaded evidence.
- [ ] Final submission figures/limits are checked; no known material integration issue is hidden.

## Handover and completion

Keep docs/stage3/handoffs/ahsan.md with accepted member SHAs, integration/release SHA, exact checks and results, skipped checks/reasons, workflow URLs, model/runtime measurements, artifact paths/hashes, deployment URL and rollback identity. Other members write their own handovers; you link them.

Task completion requires actual integrated evidence. If infrastructure blocks a final deployment, provide the concrete ready artifact and blocker; do not mark deployment complete.
