# Task 4 — Lamei: attack coverage, frozen additional evaluation and sentiment data

Owner: Lamei. Use Claude Code or Codex for implementation and mechanical validation; document semantic review honestly.

Start after: Task 5 publishes the common foundation, verified defense identity and pinned target/tokenizer information.

## Objective

Supply outcome-independent coverage metadata, a small defensible additional evaluation, reproducible task data and isolated suite generation. Preserve the original emotion payload suite.

## Read first

CONTRACTS.md; docs/stage3/FINAL_PLAN.md; FOUNDATION_READINESS.md; attack/baseline instructions; this task. The reviewed plan uses only paraphrase and neutral-distractor variants. Do not implement the draft's negation family, new directional oracles or 0.15 confidence-drop rule.

## Ownership

Own attacks/** and baseline/** for this stage, including component documentation, content/provenance files and generators. Own tests/test_attacks*, tests/test_baseline and Lamei-specific fixtures.

Do not modify endpoint defenses, runner serialization, analysis, report/UI or common contracts. You own docs/stage3/handoffs/lamei.md as a specific exception to Ahsan's general documentation ownership.

## Required implementation

1. Preserve the original core suite.
   - Keep existing emotion baseline content/IDs and AttackCase payloads unchanged.
   - Record the actual verified core payload fingerprint and compare against Task 5's source, not a blindly copied short hash.
   - New metadata may change a NEW manifest hash; that does not authorize rewriting historical evidence or changing the payload fingerprint.
   - Keep raw-body/header behavior intact. Do not fix a malformed request while adding metadata.
   - Keep suite="core" and default task behavior backward compatible.

2. Create a complete coverage declaration.
   - Inspect each existing subfamily, the actual case construction and the frozen controls.
   - Version attacks/coverage_map.json with source manifest hash, defense identity, authoring date, rationale and cross-cutting-control notes.
   - Use the agreed in_scope/out_of_scope/not_targeted/mixed definitions and per-case exceptions when subfamily membership is insufficient.
   - Treat current sanitizer expectations as evidence of intended behavior, not a complete causal classification.
   - Strict type/schema tests may exercise a declared control even if both wrappers already reject the input. State shared behavior rather than removing them merely because V1 also rejects them.
   - Do not classify using observed wins/losses or force the draft's numeric split.
   - Require every new planned case to resolve to a valid declaration; unknown/missing mappings must be surfaced as errors.
   - Emit coverage data for fresh runs; provide a separate attack_id-keyed overlay for historical analysis. Never write new coverage metadata into archived raw files.
   - Explain that the error handler is cross-cutting. Fixed-point and length tests only establish input-gate behavior.

3. Extend metadata and isolate suite state.
   - Use the frozen names/types for suite, coverage references, exposure, provenance, declared families and validity information.
   - Do not calculate authoritative wire-body byte evidence in the attack library; Rayyan records the exact serialized body at send time.
   - Use the foundation's public scoped_registry implementation. Confirm it clears during the context and restores both registry dictionaries exactly on exit.
   - Preserve build_suite(..., suite="core", task_id="emotion_7") and related signatures. Use injected target token_counter/max_tokens rather than importing endpoint weights at runtime.
   - Build and write the manifest from the same isolated suite before leaving the context.
   - Test nested/failed contexts and emotion -> sentiment -> emotion generation with no contamination.
   - No runtime imports from analysis or endpoint. Cross-component property tests may import the frozen sanitizer/tokenizer; mark model requirements honestly.

4. Create reproducible sentiment core baselines.
   - Produce 42 SST-2 validation examples, 21 NEGATIVE and 21 POSITIVE, using a fixed seed and deterministic order.
   - Use the pinned dataset revision and exact dataset row IDs from Task 5/source metadata.
   - Validate labels and duplicate/text rules before any inference. Selection must not depend on model correctness/confidence or attack success.
   - Commit baseline/sentiment_baseline.json, baseline/sentiment_provenance.json and baseline/build_sentiment_baseline.py. Keep extra provenance out of BaselineCase records; use the separate source mapping. Keep BaselineCase's existing schema usable.
   - Record legitimate exclusions and a deterministic replacement rule. Do not silently handpick better-performing samples.
   - Existing task-dependent attack builders may generate a different number of sentiment attacks. Record the actual generated count; no 1,928-case requirement.

5. Author the compact additional evaluation.
   - Plan 21 emotion seeds, three per emotion label, and 20 sentiment seeds, ten per label. Use baseline/oces/emotion_seeds.json and baseline/oces/sentiment_seeds.json. Write frozen variants to attacks/data/oces/emotion_cases.json and sentiment_cases.json, and use a separate provenance.json in that directory.
   - For each seed create one paraphrase and one neutral-distractor variant: 42 emotion and 40 sentiment planned attacks plus their clean requests.
   - Use the existing label-invariant oracle. Do not deliberately invert meaning.
   - Document source text, expected task label, transformation, rationale, author/reviewer, review method and tier for every variant.
   - Human authorship alone is not GOLD. Record actual human review if performed; otherwise describe AI/mechanical review truthfully and use the existing tier definitions.
   - Any ambiguous meaning, sentiment, emotion or discourse change stays REVIEW and visible. Do not force it into a scored tier just to meet a quota.
   - Check valid JSON/string form, target-tokenizer length including special tokens without truncation, and unchanged frozen clean_text result for each original/variant used.
   - These checks do not prove semantic validity and do not disable the exception handler. Use the agreed limited wording.
   - Do not query model predictions while selecting/reviewing these cases.

6. Freeze before evaluation.
   - Record defense commit and exact endpoint/v2.py hash before authoring.
   - Commit seeds, variants/generator, case IDs, tiers, expectations, tokenizer identities and content hashes before the first model evaluation.
   - After the commit exists, add a separate provenance record referencing that freeze commit/time; do not try to embed a commit's own hash in its contents.
   - Hand the freeze identity to Ahsan, Rayyan and Khalid. If they run later, record that execution identity.
   - No tuning/removal based on results and no defense changes to improve this set. Necessary later revisions become a new visible version.
   - Call it “additional evaluation authored after defense freeze; authors knew the defenses,” not a blind or design-independent holdout.

## Verification and acceptance

- [ ] Original emotion core payload fingerprint matches the verified source; original baseline bytes remain intact.
- [ ] Coverage mappings cover every actual planned case, with reasons and no outcome-based classifications.
- [ ] Historical files stay byte-identical; later overlays have separate hashes/provenance.
- [ ] Core and additional manifests are isolated across tasks and exceptions.
- [ ] Sentiment builder deterministically reproduces committed balanced data and source IDs.
- [ ] Counts are generated from data, not copied from the emotion benchmark.
- [ ] Additional-set content/tier decisions are recorded and committed before first inference.
- [ ] Real pinned-tokenizer and sanitizer conditions have been checked for both tasks before final acceptance; skipped model tests are not equivalent to success.
- [ ] Unknown subfamily, duplicate ID, orphan baseline, missing metadata and invalid selection tests fail clearly.
- [ ] Handover includes all unscored/ambiguous cases rather than silently dropping them.

## Handover

Write docs/stage3/handoffs/lamei.md with branch SHA, baseline/dataset/tokenizer identities, generated counts per task/suite, original payload fingerprint comparison, coverage map version/hash and derived counts, case-content freeze commit/time, review/tier summary and test results/skips. State whether any model inference occurred before freeze; if it did, disclose exposure rather than claiming independence.

Ahsan accepts the exact handover commit. Any late data change requires a new version and coordinated revalidation, not a silent amendment.
