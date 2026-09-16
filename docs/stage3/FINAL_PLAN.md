# Final reviewed implementation plan — Team Checkmate

Purpose: close the four jury feedback gaps and prepare four independent implementation branches after a common foundation task.

Execution order: TASK 5 FIRST. Tasks 1–4 start from its published foundation commit. Parallel development does not mean every end-to-end test can run before dependencies are integrated.

This document supersedes the conflicting recommendations in the supplied Claude Code proposal. It is a reviewed design, not evidence that the code is implemented or tested. Repository facts below come from the supplied inspection transcript; Task 5 must recheck the current checkout.

## 1. Scope and accepted decisions

| Area | Required result |
| --- | --- |
| Evaluation | Explain coverage of the existing suite, then execute a compact additional evaluation with frozen cases and rules. |
| Remediation | Each reported finding has actual evidence, significance, an appropriate fix, and a usable verification procedure. |
| Second task | One English sentiment classifier, one unhardened endpoint, through the shared pipeline and a usable application/report journey. |
| CI | A candidate-release gate with real pass, real regression failure, and execution-error evidence. |
| Completion | Working navigation, correct report downloads, deployed verification, repeat-run evidence, and updated submission PDF. |

Keep the original emotion V1/V2 experiment, severity rules, baseline data, attack payloads, and core scoring semantics. Introduce a second-model configuration and analysis v3 with legacy v2 reading. Do not add uploads, public arbitrary URLs, general external-model onboarding, multilingual evaluation, vision/generation, training, runtime LLM remediation, a second sentiment twin, or a visual redesign.

Sentiment selection: distilbert/distilbert-base-uncased-finetuned-sst-2-english. Task 5 resolves and records a real full revision, tokenizer configuration and label mapping; no placeholder may be used in active configuration. Its documented task and language support justify this bounded choice. Use stanfordnlp/sst2 validation examples, with dataset revision/provenance. Validation is an existing benchmark, not proof the model developer never inspected it. Sources: [model card](https://huggingface.co/distilbert/distilbert-base-uncased-finetuned-sst-2-english), [dataset](https://huggingface.co/datasets/stanfordnlp/sst2).

Use a single V1-equivalent sentiment wrapper because it demonstrates reuse with minimal new serving behavior. Do not justify this choice by assuming a hardened target would produce too few findings.

## 2. Review corrections that are binding

1. Remove OCES negation and both new directional oracles. A required 0.15 score drop has no supplied empirical justification, and negation does not always imply a polarity flip. The additional set uses paraphrase and neutral-distractor variants only, under the existing label-invariance oracle.
2. Do not call the additional set design-independent. Its authors know the controls. Say “additional evaluation authored after the evaluated defenses were frozen; authors were aware of the defenses; not a blind holdout.”
3. Valid JSON, suitable type, bounded tokens and unchanged clean_text establish that the specific input gates accept/leave the text unchanged. They do not prove the exception handler is irrelevant or prove semantic preservation.
4. Recompute coverage classifications from actual controls and case construction. The proposed 643/1,217/26 split is a hypothesis, not an acceptance target. Strict typing covers type tests even if V1's framework already rejects them. Distinguish control applicability from an incremental V2 advantage.
5. Sentiment has its own generated case count. Never require it to have exactly 1,928 cases. Preserve the original emotion core count/fingerprint when the current checkout and source evidence confirm them.
6. Use comparison: null consistently for a single-target analysis block. Do not alternate between omitted and required-null fields. Render a short explanation, with no empty comparison table or improvement percentage.
7. Actual request-body bytes and hashes belong to the sender. Add them to RunResult; do not label an estimated manifest text length as the wire-body size. A response failure may still have a known attempted request body.
8. Preserve original raw benchmark files and their hashes. Enrichment uses separate overlays/provenance; never edit a historical manifest or run_meta to make new fields appear historical.
9. Simplify CI. Remove the proposed minimum of 200 eligible flips for a roughly 170-request run, the unvalidated +0.05 flip tolerance, the 80% V1 positive-control threshold, and the blanket finding-group regression check that would catch intentionally informational slow findings. Attack flip rates remain visible but are not a blocking threshold in this first policy.
10. A generic HTTP 500 does not establish an internal model crash, process death or a leak. Preserve the historical metric key unhandled_5xx if required for compatibility, but explain it as observed server-error responses. The inspected V2 handler itself returns 500.
11. Capture current branch/dirty state before foundation work. The transcript showed ahsan/v5-redlab and an edited HANDOFF.md, not a clean main. Never discard that work or branch from stale main by assumption.
12. Do not replace AGENTS.md wholesale with a pointer. Preserve all unrelated rules; update only conflicting ownership, interface references and explicitly approved integration edges.
13. The old “607 passed” is historical evidence, not the new pass criterion. Preserve and pass the applicable existing tests; identify genuine changes and skipped environment-dependent tests explicitly.
14. Functional navigation is part of integration. Full technical reports are not subject to the five-page competition submission limit; the separate submission document is.
15. Sequential endpoint startup does not prove peak memory equals one model. Parent processes and tokenizer helpers may retain weights. Measure the actual process tree/container.

## 3. Ownership after Task 5

| Owner / task | Exclusive production ownership |
| --- | --- |
| Ahsan / 1 | run_all.py; web/**; report/**; .github/**; Dockerfile; requirements.txt if needed; top-level README/HANDOFF/AGENTS/CLAUDE/CONTRACTS; shared contract.py; docs/stage3; final artifacts and submission |
| Rayyan / 2 | endpoint/**; runner/**; endpoint/runner component docs |
| Khalid / 3 | analysis/**; analysis/policies/**; analysis/case_sets/**; analysis component docs |
| Lamei / 4 | attacks/**; baseline/**; attack/baseline component docs |
| Claude Code under Ahsan / 5 | One-time common foundation edits listed in Task 5, then ownership transfers to the table above |

Each member may edit their own docs/stage3/handoffs/<name>.md; this is an explicit exception to Ahsan's general documentation ownership. Tests have explicit matching owners. Ahsan owns test_report, test_web, test_lab, test_run_all, test_ui_browser, foundation tests and common fixtures. Rayyan owns test_endpoint, test_runner and test_gate. Khalid owns test_analysis*, test_policy and analysis fixtures. Lamei owns test_attacks* and test_baseline. Shared conftest/dependency changes go through Ahsan.

No member edits another member's production files to make their branch pass. Request a documented contract change; Ahsan lands a foundation amendment and everyone incorporates the same amendment. No dependency on Amin.

## 4. Final interface decisions

Task 5 translates this section into complete checked-in contract documentation, model-free shared types, valid fixtures and exact signatures. All repository paths are relative to the repository root.

### 4.1 Identity and file compatibility

Append these fields to RunResult, preserving every existing field and positional order:

| Field | Type / default | New-run meaning |
| --- | --- | --- |
| target_id | str = "" | emotion_v1, emotion_v2, or sentiment_v1 |
| suite_id | str = "" | core or oces |
| request_body_bytes | int or None = None | Length of the exact serialized attempted HTTP request body |
| request_body_sha256 | str or None = None | SHA-256 of those same body bytes |

Blank identities/null byte evidence are supported for historical rows only. New observed requests require explicit identity and available serialized-body evidence; an exception before serialization must explain unavailable evidence. Do not add fields to BaselineCase, AttackCase or Finding unless a verified blocker is documented first.

CI is a selection of core: suite_id=core, case_set_id=ci_core_v1. Do not create a second conflicting suite called ci_core. Version remains v1/v2; sentiment_v1 uses version=v1, and its target_id distinguishes it from emotion_v1.

An enclosing run.json has a unique run_id, run_name, created_at_utc, app_commit, dirty flag, mode, registry snapshot/hash, and evaluations. Each evaluation names its kind, task, suite, case-set, declared families and target directories. Every target run_meta repeats the enclosing run_id as evaluation_run_id and identifies target, task, model/tokenizer revisions, label space, baseline hash, suite/selection hashes, and code provenance. Preserve the runner's existing per-invocation run_id as distinct if already used.

Define exact unique keys as enclosing run_id + evaluation_id + target_id + existing case key. A results file may contain one target/suite/version only. Comparison also requires matching parent run, task, model AND tokenizer revisions, baseline identity, ordered planned/selected case fingerprints, coverage-map version/hash, relevant analysis settings, and valid manifests. Matching target names or a common task alone is insufficient. Withhold comparisons with explicit reasons when prerequisites fail; corrupt input is an error.

Legacy loading is explicit: only recognized legacy schema/layout is routed through an emotion legacy adapter, with source hashes and inferred provenance. Never infer a new row's model from version alone or silently fall back to emotion after a malformed new run. Preserve historical v2 analysis bytes; upcast in memory only.

### 4.2 Shared call boundaries

Freeze these proposed interfaces during Task 5, preserving existing positional arguments where required:

- endpoint.targets.load_registry(path=...) -> Registry, with TargetConfigError on invalid configuration. Static registry inspection must not load model weights. Validate configured references and path syntax at load time; existence of a future endpoint module or baseline file is checked when that evaluation is executed, so an unimplemented sentiment feature does not break the existing emotion path.
- Registry exposes target(target_id), model_for(target_id), evaluation(evaluation_id), and task_for(target_id). Define the returned types completely in the common contract module; no ambiguous global singleton state.
- attacks.metadata.scoped_registry() is a context manager that snapshots current registry state, clears it for the isolated build, and restores the exact previous state in finally. Snapshot-and-restore without clearing is insufficient. Nested use and exceptions must work; concurrent mutation uses the existing global job lock.
- attacks.library.build_suite(baselines, *, token_counter=None, max_tokens=None, suite="core", task_id="emotion_7") -> list[AttackCase]. Keep legacy defaults. Manifest generation and execution must consume the same isolated build.
- baseline.load.load_baseline(path=existing_default) keeps its old call usable; task configuration chooses the data file. OCES supplies a separately frozen seed file via evaluations.<id>.baseline_file: baseline/oces/emotion_seeds.json or baseline/oces/sentiment_seeds.json; core defaults to tasks.<task_id>.baseline_file. Resolve this override before suite generation and record the actual baseline hash.
- runner CLI retains legacy --version; adds --target-id, --suite core|oces and --case-set. Case sets freeze baseline_ids, attack_ids, order, selection_version and exclusions. Unknown/missing/duplicate selected IDs are errors; limits/skips cannot silently override a frozen CI selection.
- analysis.analyze.run_analysis_from_dir(run_dir) -> analysis v3 dictionary, with explicit legacy adapters. Pure row-analysis helpers carry task label-space context through validation and drift; fix all call sites, including compute_drift's internal validation.
- run_all.run_experiment(mode, run_name=None, results_root=None, progress_callback=None, *, evaluation_ids=None, html_only=False) -> existing return fields plus run_id/evaluations. None keeps the original emotion behavior. It supports full/demo and an internal ci mode used by the gate; browser opening remains CLI-only.
- runner.gate invokes run_all and analysis.policy. run_all never imports/invokes runner.gate: avoid a circular orchestration dependency.
- analysis.policy.evaluate_policy(*, policy, analysis, run_metas, results_by_target) -> GateOutcome. Pure computation, no file/process/network I/O. results_by_target contains parsed RunResult lists so operational checks can inspect every selected request, even those excluded from semantic scoring.
- GateOutcome includes schema_version, outcome, exit_code, policy identity/hash, candidate identity, approved reference identity/hash, suite/selection identity, checks, summary, artifact paths, and exclusions. outcome is pass|policy_failure|execution_error with exit_code 0|1|2 respectively. CheckResult uses pass|fail|error|not_applicable, named evidence references, observed/threshold values and a reason.

Task 5 must document exact public flags for gate and report CLIs, serialized examples, compatibility defaults, paths and error behavior. Function implementations owned by Tasks 1–4 may be absent initially; test doubles are confined to tests. No fake-success production stubs.

### 4.3 Analysis v3 and metrics

Keep the existing VersionSummary shape and nested findings[].finding object. Add remediation_detail as a sibling to finding, plus declared/inferred identity provenance.

Envelope: schema_version=3, contracts_version="3.0.0", run_identity, evaluations[], limitations.
Each evaluation: evaluation_id, kind, task, suite, targets[], summaries keyed by target_id, comparison, coverage, oces. comparison is null for single; coverage/oces are null only where inapplicable or explicitly unavailable in a recognized legacy view.

Preserve the original core rate units and format_rate behavior. New numeric rates are ratios in [0,1] or null for no denominator; user-facing text renders N/A. Always store numerator and denominator alongside a new rate. Never convert N/A to zero or mix ratio units with percentage points.

Per-target original drift keeps its existing confidence >=0.60 and eligibility rules; it measures prediction consistency, not automatically accuracy. Report clean-label correctness separately. For a paired *delta*, use the intersection of eligible case IDs in both targets and show that common denominator. Retain individual eligible denominators in the separate target summaries; do not describe a difference between differently filtered populations as a matched improvement.

For each coverage class, partition selected attacks into eligible_pass, eligible_fail, review, diagnostic and unevaluable; not-selected and not-executed counts remain visible separately. One case contributes at most once to a failure numerator. Within-control counts may overlap and must not be summed as if disjoint.

### 4.4 Coverage and additional evaluation

Keep codes in_scope, out_of_scope, not_targeted, mixed, with precise definitions in CONTRACTS.md. Labels describe intended input-control coverage, not demonstrated effectiveness. controls_targeted may list length, strict-type/schema, normalization. State that C3 error handling is cross-cutting and evaluate its observable responses without claiming isolated causal proof. Use per-case exceptions when a subfamily is not uniform. Include an incremental_vs_v1 note where framework behavior is shared. New unknown cases fail validation rather than receiving an invented class.

Fresh metadata may contain coverage references and provenance. Historical metadata remains untouched: join a versioned coverage overlay by original attack_id and record its later creation time, source manifest hash and map hash. Existing sanitizer expectations inform the new analysis, but the new coverage classification itself must not be called historically predeclared.

OCES scope: two families, oces.paraphrase and oces.distractor, using the existing invariant/label_should_match_baseline rule. Plan 21 emotion seeds (three per label) and 20 sentiment seeds (ten per label), with one variant of each family per seed: 42/40 planned attacks, plus the corresponding clean requests. Final accepted content and exclusions are frozen before the first evaluation. Do not force an ambiguous rewrite into a scoring tier to achieve a quota.

Paraphrases need recorded meaning/label review. “Hand-authored” is not automatically GOLD. Distractors need a written low-risk justification and review for negation, sarcasm, discourse effects or changed labels. Ambiguous cases stay REVIEW, remain visible and do not enter automatic semantic rates. Do not select content based on classifier outputs.

Use attacks/data/oces/emotion_cases.json and sentiment_cases.json for frozen variants, with a separate attacks/data/oces/provenance.json. Freeze evaluated defense commit and file hash, seed/variant content hashes, generator version, case IDs, tier decisions, expected relation and scoring version. After a separate freeze commit exists, record that commit in subsequent provenance; do not write a commit's own hash into itself. Tests prove input-gate conditions; they do not prove semantics or independence. No OCES predictions before freeze. Subsequent reruns are disclosed; data revisions create a new evaluation version.

Each planned OCES attack has exactly one per-target status: meets_expectation, violates_expectation, excluded, unevaluable, or not_executed, with a reason where needed. Semantic rates exclude the last three; operational failures remain visible and are not semantic successes. Use the existing scoring/severity route where applicable and keep OCES findings separate from core findings. Do not claim prediction flips are new classification errors without correct-clean-label evidence.

### 4.5 Remediation

remediation_detail contains rule_id/version/hash, observed facts with case references, significance, diagnosis_confidence, fix and verification. Observations describe recorded behavior; explanations identify supported inference versus suspected cause.

A 500 alone cannot prove inference failed internally. Token limits do not establish HTTP-body-size protection before JSON parsing/tokenization. Distinguish request-body limits from token-count checks. No invented leak, byte count or missing field. Existing raw-body lengths can be derived only from exact proven payload bytes and labeled as reconstructed; otherwise mark unavailable.

The legacy Finding.remediation string should contain a concise finding-specific summary for new findings. Existing historical strings remain unchanged. Structured detail drives the new UI; legacy documents use their original text.

Verification commands must exist, target the actual patched target, include relevant baselines, and use emitted/committed case-set files. Running a request collector alone does not “pass a gate”; state which command reruns and which checks establish the expected outcome. Never switch a sentiment finding to emotion_v2 as its supposed fix.

### 4.6 Bounded first CI policy

Candidate: emotion_v2 at the candidate code revision and pinned model. Reference: a frozen, identified approved clean-output snapshot from the preserved original run; no second live V1 service is required in every gate.

Freeze a bounded core selection: all original clean baselines, all standalone attacks except malformed.oversized_10mb, and derived attacks for the first two baseline IDs in stable sorted order. Task 5 resolves exact ordered IDs/counts from the verified suite and checks every reference exists. Freeze the selection for functional coverage, not after inspecting favorable outcomes.

Blocking checks:
- Valid policy, candidate identity, model revision, expected suite/selection hashes, metadata integrity and nonempty expected selection.
- All selected requests accounted for and completed, with valid response records.
- Every selected valid baseline gets HTTP 200 and a coherent prediction in the declared label space, with finite scores/confidence and the correct score-vector shape.
- Clean top-label outputs match the approved reference on the frozen baseline IDs. Report agreement separately from ground-truth accuracy; the reference is not assumed perfectly correct.
- Zero observed HTTP 5xx, timeouts, transport failures or failed post-request health checks across selected cases.
- Zero detected leak signatures, explicitly describing the limits of the detector.
- Every case whose existing oracle requires clean rejection returns the contract-defined allowed rejection status class. Do not count missing responses as rejections.

Slow counts, attack flip rates and finding groups are reported, not blocking thresholds. The gate claims operational robustness and approved clean-output regression checks on this selection, not comprehensive model-level adversarial robustness.

Infrastructure/config/invalid evidence/no readiness -> execution_error (2). A well-recorded candidate failure, including an abort after observed loss of health, -> policy_failure (1), with unexecuted cases retained. Structural errors take precedence when results cannot be trusted. Both stop the release workflow. No mutable threshold recalibration during candidate evaluation.

The real fail/pass demonstration uses a temporary test-only revision removing the V2 length rejection; the remaining exception handler can still return 500, so the gate checks observed 5xx rather than assuming an unhandled stack trace. Restore the control and rerun the same policy/selection. Do not merge or deploy the intentionally regressed revision.

GitHub deployment must depend on gate success and publish the tested commit/artifact. Required merge checks are a separate repository setting. Missing release credentials means release is unavailable/failed, not successfully deployed. [GitHub job dependencies](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs).

## 5. Foundation and integration rules

Task 5 establishes contracts/types, model metadata, identity mapping, original evidence, valid fixtures and ownership. It does not implement complete feature logic or run the new additional evaluation. Named model/data revisions, shared signatures, schema shapes and branch base must be concrete before readiness is declared.

Contract fixture examples are synthetic and labeled, including happy/error/legacy cases. They must be structurally and arithmetically coherent; hashes are actual hashes of the fixture bytes. They are not benchmark evidence.

All four branches start from one published foundation SHA. Use stage3/integration as the common integration branch if main is not the current released base. No forced reset/rebase of existing work.

Merge order:
1. Foundation.
2. Lamei's metadata/registry/data and Rayyan's endpoint/runner portion, resolving their actual interface dependency.
3. Khalid's analysis/policy together with Ahsan's minimum v3 report/orchestration compatibility in one tested integration candidate. Do not leave a mainline where schema v3 is emitted into a v2-only report.
4. Rayyan's gate and Ahsan's workflow/UI/release integration.
5. Real end-to-end runs, final artifacts, deployment and submission.

All four can implement from fixtures while waiting for dependent real runs. Dependency waiting is not permission to mark end-to-end work complete.

## 6. Evidence and final acceptance

Retain the supplied benchmark's claimed original values only after Task 5 verifies their source: 1,928 cases per endpoint; 29/14 findings; 15 resolved/14 remaining; flips 218/1,370 and 112/1,373. Reanalysis of the same historical bytes must preserve numeric core semantics. Fresh runs may differ in timing-sensitive cases; show this rather than forcing equality.

Every branch hands over its commit SHA, changed files, exact commands, pass/fail/skip outputs, fixture-vs-real evidence labels, example artifacts and remaining integration obligations. Ahsan verifies the exact branch revision being accepted; rerun affected checks after later changes.

Final real evidence includes original emotion core, paired emotion additional set, sentiment core and additional set, both interactive paths, same-policy CI fail/pass/error, correct deployed downloads, an emotion -> sentiment -> emotion cycle and a repeat run. Use existing reproducibility evidence plus sufficient fresh repeats to demonstrate the changed system; investigate named variability rather than hiding it. Resource measurements cover build time, cached/startup behavior and actual peak memory.

The separate competition PDF uses final frozen analysis artifacts, is at most five pages and 20 MiB under the user-provided brief, and distinguishes old/new results. Do not compress the entire technical report to five pages. Preserve byte-exact deployment hashes and an identified rollback artifact.

## 7. Boundaries for later panel answers

Demonstrated scope is two English text-classification tasks, with a paired hardening experiment only for the original model. Additional cases are not a blind holdout. Coverage labels describe intended input-gate coverage, not guarantees. A prediction flip is not automatically a new wrong answer. A failed health check is observed unavailability, not proven process death. A gate pass is compliance with this named policy, not production certification. Model-card or suite limitations stay visible. No feature is claimed merely because a config file or mock exists.
