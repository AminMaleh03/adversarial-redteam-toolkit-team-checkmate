# Task 2 — Rayyan: sentiment endpoint, target-aware runner and gate CLI

Owner: Rayyan. Use Claude Code or Codex for implementation and checks.

Start after: Task 5's published foundation commit. Work against its shared types and fixtures immediately. Do not wait for analysis implementation to write runner/gate unit tests.

## Objective

Run the existing evaluation machinery correctly against the new sentiment classifier and the original emotion endpoints, preserve exact request behavior, and expose a reliable command-line gate that turns actual results into exit 0, 1 or 2.

## Read first

CONTRACTS.md; docs/stage3/FINAL_PLAN.md; FOUNDATION_READINESS.md; endpoint/runner instructions; this task. Use the pinned model and interface decisions from Task 5. Do not reinstate negation oracles, a third suite named ci_core, or arbitrary public target input.

## Ownership

Own endpoint/**, runner/** and their component READMEs. Own tests/test_endpoint.py, tests/test_runner.py, tests/test_gate.py and Rayyan-specific fixtures.

Do not edit run_all.py, web, report, analysis, attacks, baseline, root README, Dockerfile or common contract.py. Send concrete requests to the owning member. Model and tokenizer metadata fixed in Task 5 may be completed/validated here, but do not silently change the selected revision or label mapping.

## Required implementation

1. Validate the selected model configuration.
   - Use distilbert/distilbert-base-uncased-finetuned-sst-2-english at the real pinned revision in the foundation registry.
   - Confirm label names/case, id mapping, tokenizer identity and usable model input limit.
   - Distinguish the training sequence length mentioned in a model card from the actual inference capacity. Determine boundaries from pinned configuration/tokenizer behavior.
   - Keep registry lookup model-free. Token counting must not accidentally import the old emotion module and load its weights for a sentiment run.
   - Validate unknown IDs, unpinned revisions, invalid target/evaluation references, duplicate ports and task/model label mismatches.

2. Implement the single sentiment endpoint.
   - Add endpoint/loader.py and endpoint/sentiment_v1.py using the frozen response contract.
   - Preserve /predict and /health compatibility: text input and complete label/confidence/all_scores output.
   - V1-equivalent wrapper only. Do not add a sentiment V2 or tune defenses based on new evaluation results.
   - Explicitly preserve no-silent-truncation behavior and full label scores. Never remap NEGATIVE/POSITIVE into emotion labels.
   - Keep existing emotion endpoints and pinned revision behavior unchanged.
   - Bind test services to configured loopback ports. Allow only the trusted registry targets.
   - Supply Ahsan with required Docker cache files and measured startup/resource information rather than editing his Dockerfile.

3. Extend runner/run.py.
   - Keep old --version calls working through the explicit emotion default. New --target-id derives version, and conflicting flags are errors.
   - Support --suite core|oces and --case-set using the common selection format.
   - Respect exact baseline_ids, attack_ids and order in frozen case sets. Reject unknown, duplicate, empty, incomplete or conflicting selections. Every derived selected case has its selected baseline.
   - Record selected/skipped/limit_excluded/completed/missing partitions consistently; a bounded CI selection still refers to the full core suite identity.
   - Parameterize tokenizer and token limits by the target. Use one isolated library build for each task/suite; reuse identical planned cases for the paired emotion experiment.
   - Preserve raw_body/raw_headers exactly for raw attacks. Do not reserialize them as JSON or “repair” malformed bytes.
   - For ordinary cases preserve the existing HTTP client's serialized request body. Capture request_body_bytes and request_body_sha256 from that exact prepared body and send that same request.
   - Include body evidence on baseline and attack rows even if transport subsequently fails. Do not substitute character count or response length. If serialization fails before bytes exist, record the reason and treat it as an execution failure.
   - Emit explicit target_id and suite_id on new rows, complete run_meta target/task/model/label/parent-run data, copied configuration/map snapshots and actual hashes.
   - Stage outputs and publish safely; never overwrite a previous successful run because readiness failed.
   - Preserve request ordering, no prediction retries, post-request health handling and partial evidence semantics.
   - Keep existing function signatures usable; document new public ones exactly.

4. Implement runner/gate.py.
   - Use the shared GateOutcome/CheckResult contract; do not define a competing version inside the runner.
   - Expose the frozen --policy, --out and applicable CLI options and document a real runnable invocation.
   - Invoke run_all.run_experiment for the internal CI evaluation, then pass analysis, run_metas and actual RunResult sequences to Khalid's pure evaluate_policy.
   - Do not import gate from run_all or create a circular import. Delay optional imports as needed so --help and offline tests do not load models.
   - Convert a valid failed policy to exit 1; missing/unusable evidence or configuration/readiness failures to exit 2; only an actual complete policy pass to exit 0.
   - Emit gate_result.json and readable reasons on error paths whenever the destination can be written. Use null for unavailable measured values; do not fabricate reference/candidate evidence.
   - Preserve trustworthy candidate-caused partial failures and distinguish them from unusable artifacts.
   - Do not recalibrate policy values, alter selection or skip hard cases during gate execution.
   - Ensure exit codes reach the shell/workflow; never swallow them after report generation.
   - Supply actual analysis/report/raw paths. If an optional PDF fails in CI, html_only remains supported; missing essential gate evidence still fails.

5. Support Ahsan's controlled regression demonstration.
   - Prepare a small temporary change removing V2's length rejection only, on an isolated branch.
   - Explain that the existing exception handler may turn the resulting exception into a generic HTTP 500; do not promise a stack trace or process crash.
   - Help execute failing and corrected runs under the same frozen policy, then ensure the released code retains the defense.
   - Do not run OCES before its case/rule freeze, and do not change the evaluated defenses to improve OCES results.

## Dependencies and parallel work

Task 5 supplies registry types, model metadata, public registry isolation and fixture examples. Lamei supplies real core/OCES suite integration and sentiment baselines; Khalid supplies policy and v3 analysis; Ahsan supplies orchestration.

Use unit-test doubles for those interfaces until they land. Implement endpoint/runner and gate code in separate commits so endpoint/runner can merge before the gate dependencies. Never add a fake policy implementation to production to make the CLI look complete.

## Verification and acceptance

- [ ] Relevant old endpoint/runner tests pass without loosening raw-request or truncation assertions.
- [ ] A real pinned sentiment endpoint returns both labels/scores correctly and correct health responses.
- [ ] Two target/suite builds do not contaminate one another's manifests.
- [ ] Actual wire-body length/hash matches captured HTTP bytes for ASCII, Unicode and raw malformed examples.
- [ ] Duplicate/mixed target IDs, bad config, missing selections and wrong tokenizer context are rejected.
- [ ] Full real sentiment core execution completes its generated planned count; do not force 1,928.
- [ ] After data freeze, sentiment additional evaluation executes every planned case or records the precise nonexecution reason.
- [ ] Pass/fail/error gate fixtures return 0/1/2; real integrated gate evidence follows once dependencies land.
- [ ] No test double, skipped tokenizer proof or absent dependency is presented as real end-to-end validation.

## Handover

Write docs/stage3/handoffs/rayyan.md with branch/head SHA, owned files changed, pinned model/tokenizer revision, public commands, test output/skips, actual run directories/counts, request-byte examples, sample gate outputs and measured startup/runtime/resource data. List remaining integration checks explicitly. Ask Ahsan to test the exact handover commit before acceptance.
