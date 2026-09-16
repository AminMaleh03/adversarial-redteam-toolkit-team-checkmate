# Task 3 — Khalid: analysis v3, coverage, remediation and CI policy

Owner: Khalid. Implementation and verification may be performed with Claude Code or Codex.

Start after: Task 5 publishes the shared foundation. Its fixtures and preserved raw benchmark let you begin without waiting for live new endpoints.

## Objective

Produce correct, traceable analysis across paired emotion and single sentiment evaluations, explain each finding with real evidence, and implement the agreed bounded pass/fail policy without changing the original experiment's scoring.

## Read first

CONTRACTS.md; docs/stage3/FINAL_PLAN.md; FOUNDATION_READINESS.md; original analysis instructions; this task. The final plan removes the draft's negation/score-drop oracles and its C7/C8/C9 thresholds. Do not implement those discarded rules.

## Ownership

Own analysis/**, including coverage.py, oces.py, remediation.py, remediation_rules.json, policy.py, policies/** and case_sets/**. Own tests/test_analysis*, tests/test_policy and analysis-specific fixtures.

Do not edit runner/gate, endpoint, attacks/baseline, report/UI, common contract.py or shared fixtures without Ahsan's coordinated amendment. Your own docs/stage3/handoffs/khalid.md is an explicit ownership exception.

## Required implementation

1. Handle identity and label space safely.
   - Extend validation and every caller, including drift.compute_drift's internal validate_rows call, to accept the task's declared labels. A top-level validation fix alone is insufficient.
   - Validate all_scores shape and finite values for new target responses according to the shared contract. Preserve usable/missing prediction semantics and historical evidence.
   - Enforce one target/suite/version per results file; duplicate cases and mixed identity are errors.
   - For pairing, verify the full common-run/model/tokenizer/baseline/suite/selection/settings identity. Withhold comparison with reasons if legitimate incomplete runs cannot be paired; reject corrupt metadata.
   - Recognize legacy flat/nested layouts and v2 documents explicitly. Unknown new data must not fall back to emotion labels or target_id=version.
   - Load maps/provenance from run artifacts, never by importing attacks.
   - Write schema v3 evaluation blocks with summaries keyed by target_id and comparison:null for single-target sentiment.
   - Preserve the existing nested findings[].finding representation, core metrics, confidence threshold, weights and severity tiers.

2. Reproduce and enrich the original benchmark.
   - Use the byte-preserved historical run from artifacts/benchmark_v6 and its manifest/provenance.
   - Reproduce original numeric findings, flips and denominators before adding presentation or enrichment.
   - Join Lamei's later coverage overlay without rewriting or falsifying original manifest metadata.
   - If reanalysis differs, investigate the exact source run and semantics. Do not edit expected totals to conceal a wrong source artifact.
   - Keep old-run evidence and fresh evaluation results distinguishable.

3. Implement coverage reporting.
   - Join every planned attack to a versioned class/rationale and applicable controls; reject unknown mappings for new evaluation data.
   - Derive counts from actual manifests and selection. Do not force the proposal's 643/1,217/26 split.
   - Produce per-class planned/selected/completed and eligibility buckets, unique failure numerators and explicit denominators.
   - Show shared framework behavior and cross-cutting error-handler limitations. A case being within a control's intended coverage does not prove that control caused the observed improvement.
   - Compute any matched paired failure/flip delta over the intersection of eligible case IDs. Keep separate per-target denominators visible.
   - Preserve zero denominator as N/A/null according to the frozen representation and units; do not emit a zero-success claim.
   - Do not sum overlapping per-control totals as a disjoint partition.

4. Implement the additional-evaluation analysis.
   - Support oces.paraphrase and oces.distractor only, using existing invariant label-comparison behavior.
   - Respect frozen tiers and low-confidence/missing-prediction rules. REVIEW/DIAGNOSTIC are not automatically scored.
   - Every planned case has a per-target outcome, including excluded, unevaluable and not_executed with a reason.
   - Keep operational failures visible; absence of a prediction cannot be counted as successful invariance.
   - Provide per-family and per-target counts, direct evidence links, seed/variant/freeze hashes and the accurate author-exposure statement.
   - Treat prediction flips as consistency failures; distinguish correctly classified clean baselines before claiming induced misclassification.
   - Keep OCES findings/rates separate from the original core and from other models.
   - Do not add new severity weights or a 0.15 score-drop requirement.

5. Implement finding-specific remediation.
   - Generate observed -> significance -> fix -> verification from actual rows, metadata and known repository code.
   - Add structured remediation_detail next to the existing finding object. For new findings, also provide a concise evidence-specific Finding.remediation string for legacy consumers.
   - Create reusable rules with explicit IDs/version/hash. Cover the real observed failure-mode/family combinations; avoid one arbitrary hardcoded rule per sequential finding number.
   - Record actual status distributions, body evidence supplied by the runner, relevant confidences, case IDs and health observations where available.
   - Never claim a generic 500 proves a model-inference cause or process death. Never claim a token limit prevents oversized HTTP bodies from being parsed.
   - Mark supported inferences/suspected causes and missing evidence explicitly. Historical body evidence remains unavailable unless reconstructed exactly and labeled as such.
   - Verification instructions must name the affected or patched target, emitted case-set file, necessary baselines, runnable command and exact condition to inspect.
   - Do not reroute sentiment fixes to emotion_v2, claim a collector command runs the gate, or reference nonexistent verification files.
   - Model-level weaknesses may need a specific evaluation/remediation procedure rather than an invented endpoint control. Explain that limitation.
   - Use a clearly identified fallback only when needed; it must still contain evidence-specific observations and a useful next verification step.

6. Implement the pure CI policy.
   - Use the shared evaluate_policy(policy, analysis, run_metas, results_by_target) interface and shared GateOutcome/CheckResult types.
   - No model calls, files, HTTP or subprocesses inside the policy function.
   - Evaluate the frozen core selection against emotion_v2, with the approved clean-reference snapshot and real candidate identity.
   - Enforce selection/integrity/completion, coherent successful clean responses, approved clean-label agreement, zero selected 5xx/timeouts/transport/health failures, no detected leak signatures and documented rejection behavior.
   - Inspect every selected request for gate operational checks, including requests excluded from semantic scoring; do not change historical report scoring to achieve this.
   - Report ground-truth baseline accuracy separately from agreement with the approved reference.
   - Attack flip rates, slow responses and finding groups remain informational in this first policy.
   - Invalid policy/evidence/readiness/integrity -> execution_error. Trustworthy recorded candidate defects -> policy_failure. Zero executed checks or a draft policy cannot pass.
   - Populate actual suite/selection/policy fingerprints only after verifying the real artifacts. Freeze before the controlled regression demonstration. Never calibrate against the candidate to manufacture a pass.

## Independent work

Use the foundation's small paired/single/legacy fixtures, error cases and retained raw benchmark. The fixtures are synthetic contract evidence. They are not a replacement for real integrated runs.

Provide analysis/report fixtures and policy outputs early to Ahsan and Rayyan through the documented shared interface. Do not privately change JSON names or null conventions.

## Acceptance checks

- [ ] Historical raw reanalysis preserves verified core numbers and severity behavior.
- [ ] A real uppercase sentiment label space works through validation AND drift.
- [ ] Mismatched run/model/suite identities cannot generate a paired improvement.
- [ ] Single-target output has comparison:null and no fabricated comparison metrics.
- [ ] Coverage counts reconcile with actual selected/planned IDs; zero denominators and overlapping controls are handled correctly.
- [ ] Every planned additional case is visible with the correct status and evidence.
- [ ] Every new reported finding has usable structured remediation and a valid verification route.
- [ ] Policy tests cover pass, all-rejecting candidate, constant/wrong clean output, 5xx, leaks, timeouts, partial candidate failure, missing/truncated evidence, bad identity and invalid/empty policy.
- [ ] Real policy/analysis artifacts validate with Ahsan's actual renderer after integration.
- [ ] No unfinished policy calibration, skipped dependency proof or fixture run is called a real gate demonstration.

## Handover

Write docs/stage3/handoffs/khalid.md with branch SHA, public interfaces, test results, original-number reconciliation, example v3 paired/single outputs, coverage totals, rule coverage/fallbacks, exact policy/reference/selection hashes and commands. Include all remaining real integration checks for Ahsan's acceptance.
