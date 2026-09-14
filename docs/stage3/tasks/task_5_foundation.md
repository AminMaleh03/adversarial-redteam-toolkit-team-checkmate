# Task 5 — Claude Code: prepare the shared foundation so all four members can start

Executor: Claude Code in Ahsan's actual repository, under Ahsan's ownership.

RUN THIS TASK FIRST. The supplied complete task pack is the input. Execute Task 5 only; do not begin Tasks 1–4 automatically.

## Objective and authorization

Prepare and publish a tested common foundation: corrected contracts, shared types/interfaces, genuine model/data identity, preserved benchmark evidence, coherent fixtures, clear ownership, and one base commit for four parallel branches.

This task authorizes the necessary reversible foundation edits, tests, new commits and publication of new foundation/implementation branches to the existing project remote. It does not authorize deploying the application, executing new additional-evaluation predictions, overwriting existing branches, merging unfinished features, or implementing the four feature work packages.

Do not stop after another generic proposal. Implement this foundation and return concrete verification evidence. If a genuinely missing source, access restriction or irreconcilable repository fact blocks readiness, finish unaffected preparation and report the exact blocker without claiming everyone is ready.

## Inputs and decisions already settled

Use the “Final reviewed implementation plan” and Tasks 1–4 supplied in this pack. They supersede the conflicting draft proposal. Store them in the repository so every member's coding agent can read the same instructions.

The mandatory corrections are:
- Four implementing members only: Ahsan, Rayyan, Khalid, Lamei. No work/handover dependency on Amin.
- Preserve original emotion V1/V2 core semantics and historical evidence.
- One pinned English SST-2 sentiment model, one V1-equivalent endpoint.
- Additional evaluation has paraphrase and distractor families only. No negation, directional label-flip oracle or 0.15 score-drop threshold.
- Input-gate fixed-point/length checks do not prove all defenses are irrelevant or that semantics are preserved. Do not claim design independence.
- Coverage classification is derived from controls/construction, including shared validation; no fixed 643/1,217/26 acceptance numbers.
- CI uses core plus a frozen case selection. No separate suite_id=ci_core, no 200-eligible-case requirement, no arbitrary +0.05 flip threshold or 80% positive-control requirement.
- New single-target analysis uses comparison:null everywhere.
- Sender-recorded request body bytes/hash are authoritative.
- New identities must not silently fall back to emotion. Legacy handling is explicit.
- UI/report/deployment functionality and the separate five-page submission are required completion work later, not completed by this task.

## Step 1 — Establish the correct base safely

1. Inspect applicable AGENTS.md/CLAUDE.md, git status, local/remote branches, current commit and release history.
2. The supplied transcript showed ahsan/v5-redlab at a17fc5b... with an edited HANDOFF.md. Treat that as a clue, not a current fact.
3. Identify the actual validated release branch/commit. Do not start from main merely because it is named main.
4. Preserve all existing uncommitted/user changes and existing branches. Use a clean separate worktree from the verified base if necessary. Do not reset, discard, auto-stash or include unrelated changes in the foundation commit.
5. Record the source commit, evidence source, initial relevant tests/environment and the handling of any pre-existing changes.
6. Create stage3/foundation or a new noncolliding name. Do not overwrite an existing unrelated branch.

## Step 2 — Save the reviewed requirements and ownership

Create:
- docs/stage3/FINAL_PLAN.md — the reviewed plan from this pack.
- docs/stage3/tasks/task_1_ahsan.md through task_5_foundation.md — the exact task descriptions.
- docs/stage3/OWNERSHIP.md — production/test/shared-file owners and the handover-file exceptions.
- docs/stage3/DECISIONS.md — concrete resolutions, sources and corrections to the old proposal.

Update AGENTS.md and CLAUDE.md narrowly to point to the final contract and tasks, assign baseline/** to Lamei and run_all.py/web/** to Ahsan, and approve the required component edges. Preserve all unrelated repository instructions.

Document runner.gate -> run_all and analysis.policy, runner.run -> model-free target registry and attack library, and analysis reading manifests/overlays from artifacts without importing attacks. Avoid a reverse run_all -> runner.gate import. State one owner per shared file and the contract-amendment procedure.

## Step 3 — Finish and commit the actual shared contracts

Create CONTRACTS.md version 3.0.0 with complete definitions, not only examples or a link back to the chat. Ground names and wrappers in actual source.

Include every handoff:
- Baseline/attack/suite metadata -> runner.
- Registry/model/task/evaluation config -> orchestration/endpoint/runner.
- Results/run metadata/identity and request-byte evidence -> analysis.
- Analysis v3/remediation/coverage/additional outcomes -> report and UI.
- Analysis plus recorded requests -> pure policy -> GateOutcome -> CLI/workflow.
- Run identity -> status polling, artifact links and downloads.

For every field define meaning, type, enum, required/default/null behavior, units, producer/consumer, source/hash semantics and error handling. Define exact function signatures and CLI flags from the final plan. Resolve all inconsistent names, empty/omitted/null examples and undefined types.

Implement only the common foundation needed now:
1. Append target_id, suite_id, request_body_bytes and request_body_sha256 to RunResult with the backward-compatible defaults in the final plan. Preserve all existing fields/order. Keep BaselineCase, AttackCase and Finding structurally unchanged.
2. Add model-free shared structural types for registry specs and GateOutcome/CheckResult to contract.py or a single documented shared contract module if the actual repository requires it. Record one import path; no competing definitions.
3. Create the pure static endpoint/targets.py registry loader and endpoint/targets.json definitions with real references. This one-time foundation ownership transfers to Rayyan afterwards.
4. Add attacks.metadata.scoped_registry with snapshot -> clear -> yield -> exact restoration in finally. It must pass nested-context/exception tests and must not change existing callers until their owners wire it.
5. Freeze the future AttackMetadata/schema additions in documentation and shared structural definitions. Do not inject invented coverage classes into live historical data.
6. Add lightweight schema/fixture validation using existing dependencies or the standard library. Do not add a broad schema framework solely for this task.
7. Do not add production fake-policy/analysis/endpoint implementations that return canned success. Use test-only doubles and exact documented protocols for features not implemented yet.

Define the registry evaluations:
- emotion.core: paired emotion_v1/emotion_v2.
- emotion.oces: paired same emotion targets, suite oces.
- sentiment.core: single sentiment_v1.
- sentiment.oces: single sentiment_v1.
- ci.emotion: single candidate emotion_v2, suite core, case_set_id ci_core_v1, internal CI mode.

Set evaluation-level baseline_file overrides for the two OCES seed files named in the final plan; core uses the task baseline_file. Record the actual selected seed file hash in each run, not the unrelated core baseline hash.

Core demo and interactive modes apply to both tasks; additional full executions can be CLI-only with real report access later. Preserve any current supported execution path. Public API defaults keep existing emotion requests working.

## Step 4 — Resolve model and data identity before branching

Resolve distilbert/distilbert-base-uncased-finetuned-sst-2-english from its authoritative source/cache and record the real 40-hex model revision, canonical repo ID, tokenizer identity/revision, label mapping and usable limit. Verify the existing emotion pin against source.

Validate registry relationships and path syntax without importing endpoint apps. Files assigned to later tasks may not exist yet; check their existence at selected-evaluation execution, not while loading the static registry for the existing emotion path.

Record the exact SST-2 dataset revision/config/split and expected source schema for Task 4. Do not select sentiment examples using model outputs or claim the validation split is unseen to the model developers.

Registry inspection/import and offline fixture tests must not load model weights. Cache only the metadata/tokenizer assets actually needed for readiness if necessary; new-model inference is Task 2's real validation. State what is verified now versus still a runtime acceptance requirement.

No placeholder revision, “main,” invented SHA or unresolved label mapping in active config. If source access prevents a real pin, report NOT_READY with that exact blocker rather than a fake valid registry.

## Step 5 — Preserve the original evidence and freeze CI inputs

1. Locate the raw run corresponding to the published benchmark. The supplied proposal points to results/repro_1; verify hashes and numerical reproduction against artifacts/verified_full_report/analysis.json.
2. Copy the necessary original manifest, results JSONL, run_meta and original baseline/provenance into artifacts/benchmark_v6. Preserve source bytes exactly.
3. Write a separate provenance/index file: source paths, original hashes, actual source revision where known, known limitations, legacy target mapping and verified figures. If a source revision is unknown, state unknown.
4. Do not add new fields to original manifests/run_meta or replace the previously published report. Add future classification and enrichment as separate overlays.
5. Account for line-ending conversion when committing evidence; use narrowly scoped attributes if needed, without changing project-wide text rules.
6. Verify the original core planned payload fingerprint from source. Snapshot severity/oracle behavior through meaningful baseline checks; do not write tests that merely copy a dict and call that complete verification.
7. Freeze the exact initial CI case selection from the actual source suite: every original clean baseline, all standalone attacks except malformed.oversized_10mb, and derived attacks for the first two sorted baseline IDs. Include all necessary clean references, ordered IDs, source/payload fingerprint, explicit exclusions and rationale.
8. Capture approved clean-reference top-label outputs from the verified original emotion_v2 baseline rows, with source hash and model identity. This is a regression reference, not ground-truth certification.
9. Put final CI input contracts and real case/reference artifacts in their agreed analysis/case_sets and policy-reference locations. Khalid owns subsequent implementation; do not auto-approve future changes to references.
10. New manifest/coverage hashes that can only exist after feature implementation are resolved by Khalid from real artifacts before the first gate demonstration. Define that procedure exactly; a draft/unfinalized policy must error, never pass.
11. Do not author or run OCES here. Record the evaluated defense commit and file hash so Lamei can author after that freeze.

If the original raw source cannot be recovered, do not substitute a fresh run and claim historical identity. Report the precise evidence blocker. Complete everything else that does not require it.

## Step 6 — Supply valid fixtures for immediate parallel work

Create tests/fixtures/stage3 and shared offline test helpers. Include:
- A small genuine legacy v2 analysis fixture and clearly labeled synthetic legacy row/layout fixtures.
- Coherent paired emotion.core results and single sentiment.core results, including uppercase sentiment labels.
- Both halves of paired emotion.oces and a single sentiment.oces example using the TWO agreed families.
- A run.json that indexes every included evaluation and correct target directory.
- Matching manifests/run_meta/coverage declarations, case selection, registry snapshots and valid hashes.
- Complete expected v3 outputs preserving nested finding objects and comparison:null for single.
- Finding-specific remediation examples, including missing request-byte evidence and a model-level fix.
- CI pass, policy-failure, execution-error, all-rejecting and wrong-clean-output examples.
- Negative fixtures for mixed identity, wrong model revision, wrong label space, duplicate/orphan cases, altered hash, missing/truncated file, zero denominator, incomplete execution and ambiguous legacy input.
- Status/API examples with run_id/evaluation identity to exercise stale-result handling.

Synthetic examples must say synthetic and must not masquerade as measured findings or model pins. No ellipses, placeholder hashes, nonexistent case IDs or invented production figures in passing fixtures. Calculate real hashes from the fixture bytes; validate count partitions, references, rates and declared families.

Keep the fixture pack small and offline. New absent feature implementations are replaced only by test-local doubles. Provide per-owner examples so members can write tests immediately without editing common fixtures.

## Step 7 — Verify the foundation

Run:
- Existing applicable contract/attack/runner/analysis/report regression checks to confirm the additive foundation does not break current behavior.
- New offline fixture/schema checks and nested/exception registry isolation checks.
- Legacy row construction and original evidence byte/hash checks.
- Registry import/validation tests without loading weights.
- A clean-checkout/import/test check from the prospective foundation tree to ensure fixtures/assets are tracked rather than available only as local files.
- git diff --check and explicit review of the changed-file scope.

Document exact commands, tested revision/tree, outputs, environment, and meaningful skips. Do not treat the historical “607 tests passed” as proof this foundation passes now. No new OCES inference or deployment is part of this stage.

## Step 8 — Publish the shared starting point

1. Commit only the reviewed foundation files and identified evidence. Record a clear commit message.
2. Publish the new foundation branch to the existing project remote.
3. Establish stage3/integration at that foundation without rewriting main or a prior release branch.
4. Create/publish four fresh implementation branches from the SAME foundation commit:
   - stage3/ahsan
   - stage3/rayyan
   - stage3/khalid
   - stage3/lamei
5. If any name already contains unrelated work, preserve it and use a new noncolliding suffix; record the exact actual mapping.
6. Confirm remote branch tips match the chosen foundation SHA and provide each member's fetch/checkout commands.
7. Do not force-push, overwrite user work, merge unfinished features, switch another active worktree's branch or create a dependency on Amin.
8. A commit cannot contain its own SHA. Reference the tested foundation by a tag/remote branch and report its full SHA after committing. Any later tracked readiness receipt must clearly distinguish its documentation commit from the tested foundation.

## Required final output

Return a plain-English summary plus a readiness report containing:
- FOUNDATION_READY or NOT_READY with concrete blockers.
- Verified source release/base and published foundation SHA.
- Integration branch and all four implementation branch names/remote tips.
- Contracts version, shared symbols, ownership and approved import edges.
- Real model/tokenizer/dataset pins and which runtime checks remain.
- Original evidence paths/hashes and the frozen CI selection/reference.
- Fixture/test commands and actual outcomes/skips.
- Complete changed-file list and preservation of pre-existing work.
- Member-specific checkout/start instructions and independent checks.
- Remaining feature/integration obligations; no claim that fixtures prove final functionality.

Store the report in docs/stage3/FOUNDATION_READINESS.md with a commit-reference strategy that avoids self-reference, and return the final verified SHA in chat.

Stop after Task 5. Ahsan will distribute Tasks 1–4 and their coding agents will implement them on the published branches. No additional high-level planning loop is needed for already settled decisions.
