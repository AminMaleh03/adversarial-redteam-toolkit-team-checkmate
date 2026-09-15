# Handover — Lamei (Task 4: attack coverage, sentiment data, suite isolation, OCES)

> **STATUS: PRE-FREEZE DRAFT (living document).** Phases 0–4 (candidate authoring) are done
> and pushed. The OCES set is **authored but NOT frozen**: it still needs (a) Lamei's human
> review + GPT semantic sign-off of the 82 candidates and (b) Ahsan's confirmation of the
> canonical V2 defense identity. Fields that depend on the freeze are marked **TODO (freeze)**.
> This handover will be finalised at the freeze commit (Phase 5) and the PR (Phase 6).

## Branch / commit
- Branch: `stage3/lamei`
- Head SHA at this draft: `28942a58ad6f13cb57e56806d2446775ae915c43`
- Cut from foundation `257e15f3432aa29a3942d52b2cf3befb12ba3354` (tag `stage3-foundation-v1`).
- PR target: `stage3/integration`, reviewer **Ahsan** (do NOT self-merge). **TODO (Phase 6).**

## Ownership boundary
Own `attacks/**`, `baseline/**`, `tests/test_attacks*`, `tests/test_baseline`,
`tests/test_sentiment_baseline.py`, `tests/test_oces.py`, and this file. No endpoint, runner,
analysis, report/UI or `contract.py` changes were made. `contract.py` is unchanged.

## Commits (this task)
| SHA | What |
| --- | --- |
| `d57ee45` | Phase 1: coverage map, metadata coverage fields, resolver, isolation tests |
| `36ff45e` | Phase 1 fixes: source-manifest identity, overlay provenance, tests |
| `e81020c` | Phase 2+3: suite/task isolation + deterministic SST-2 sentiment baseline |
| `344119c` | Phase 2/3 review hardening: suite identity, honest wording, narrowed skips |
| `6abef0e` | Phase 4: OCES candidate authoring (pre-review, pre-freeze) |
| `28942a5` | Phase 4: OCES pre-freeze corrections from GPT audit |

## Frozen identities
- **Emotion model/tokenizer:** `j-hartmann/emotion-english-distilroberta-base` @
  `0e1cd914e3d46199ed785853e12b57304e04178b`; labels (anger, disgust, fear, joy, neutral,
  sadness, surprise); limit 512.
- **Sentiment model/tokenizer:** `distilbert/distilbert-base-uncased-finetuned-sst-2-english`
  @ `714eb0fa89d2f80546fda750413ed43d93601a13`; labels `("NEGATIVE","POSITIVE")` (uppercase);
  limit 512.
- **Dataset:** `stanfordnlp/sst2` @ `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb`, `validation`
  split (872 rows, 428 neg / 444 pos), file
  `data/validation-00000-of-00001.parquet` sha256
  `fb00fe008f6828f86ba2beda8415a4cf5da0c884f21c5f238c87131b5aa19529`.
- **V2 defense freeze point (for OCES freeze):** `endpoint/v2.py` git blob
  `b71787e3bf39e4062f883c9e34fae78d5b7c6263` (matches foundation). **Canonical id pending
  Ahsan — gates the OCES freeze.**

## 1. Core preservation (emotion)
- Emotion baseline bytes/ids unchanged. Core payload suite fingerprint
  `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430` **reproduces** from the
  live baseline (verified via `verify_phase0.py`, both build-order and send-order), matching
  the foundation's recorded `planned_suite_sha256`. New coverage metadata changes only a new
  manifest, never the payload fingerprint or historical files.
- Emotion core generated count: **1886** (unchanged).

## 2. Coverage layer (Phase 1)
- `attacks/coverage_map.json` v**1.0.0**, sha256
  `93f706e64d5b46da89f91cbf7a33bb8bcf32e27149a4dbbffe0d62f489a8a90c`. Classifies all core
  subfamilies **from construction + control design, never from observed results**.
- Distribution (subfamily): in_scope 34 / not_targeted 19 / out_of_scope 6 / mixed 5.
  By case: not_targeted 1220 (64.7%) / in_scope 655 / out_of_scope 6 / mixed 5 = 1886.
  Report BOTH denominators; never "65% of families".
- Historical overlay `attacks/overlays/coverage_overlay_benchmark_v6.json` (1,886 entries)
  carries its own provenance/hashes; the archived V6 manifest is byte-unchanged.
- Resolver fails loud on any unmapped subfamily (CONTRACTS 6.5).

## 3. Suite / task isolation (Phase 2)
- `attacks.library.build_suite(baselines, *, token_counter=None, max_tokens=None,
  suite="core", task_id="emotion_7")` — kw-only, legacy defaults; unknown suite/task_id →
  `ContractError`; `suite="oces"` refused (OCES is frozen data, not synthesised).
- `task_id` is **validated only**, not stored in per-attack metadata; executed-row task
  identity is recorded in run provenance by the runner (`RunResult.target_id` → task via the
  registry).
- Build + `write_manifest` must run inside one `metadata.scoped_registry()` (clears on entry,
  restores both `_MANIFEST` and `_FINGERPRINTS` on exit).
- Fixed a Phase-1 latent bug: coverage stamping mutated registered metadata, breaking
  `register()` idempotency on a second build in a shared registry (run_all's Demo/Full → Lab
  path). `register()` now compares the as-registered identity, excluding only the
  post-registration coverage_* fields; `suite_id` **is** part of identity.

## 4. Sentiment core baseline (Phase 3)
- `baseline/build_sentiment_baseline.py` → `baseline/sentiment_baseline.json` +
  `baseline/sentiment_provenance.json`. 42 rows, **21 NEGATIVE + 21 POSITIVE**, SEED=20260915
  (authored/frozen by Task 4, not foundation-prescribed), deterministic **model-free**
  selection (mechanical validity + de-dup, then one seeded permutation per label). Text kept
  **verbatim** (SST artefacts preserved); labels uppercase; id = `sst2-val-<idx>`.
  **0 exclusions.** Selection independent of any model output.
- Hashes: `sentiment_baseline.json`
  `33077982c79553d0ae700ed0658c5912186958750866d725792e7f9bf4c87bd2`;
  `sentiment_provenance.json`
  `a96ac92863f18c87a86eebf8d6f5169a038267452474940c933eb4b6d681805f`.
- Selected NEG idx: 18,35,59,110,111,121,136,162,211,319,361,432,489,590,601,672,730,743,748,761,805.
  Selected POS idx: 13,17,52,109,120,201,227,248,290,341,427,480,561,588,609,656,671,674,686,778,785.
- **Generated sentiment core attack count: 1889** (real pinned sentiment tokenizer;
  distinct from emotion's 1886; content-driven, deterministic). Not copied from emotion.

## 5. OCES additional evaluation (Phase 4 — AUTHORED, NOT FROZEN)
- Seeds (deterministic, model-free, from the committed baselines):
  - emotion: **21** = 3 per each of 7 labels (sort by baseline_id within label, first 3) →
    `baseline/oces/emotion_seeds.json` (sha256 `d5cc6011…`).
  - sentiment: **20** = 10 per label (sort by ascending idx within label, first 10) →
    `baseline/oces/sentiment_seeds.json` (sha256 `a16e5c99…`).
  - The seed `text` is the **OCES clean request** = `clean_text(raw source)` (sanitation-
    invariant); the exact raw source is kept in provenance. Core baselines untouched.
- Variants: one paraphrase + one neutral distractor per seed → **42 emotion + 40 sentiment =
  82** → `attacks/data/oces/emotion_cases.json` (sha256 `f2e8e394…`),
  `sentiment_cases.json` (sha256 `053737c3…`), `provenance.json` (sha256 `d776f08d…`).
  - Families: `oces.paraphrase` / `oces.distractor` only; relation=invariant; oracle=
    `label_should_match_baseline`. **No negation, no directional oracle, no confidence-drop.**
  - Distractor = `clean_request + " " + neutral_clause` (exact request prefix; only a neutral
    sentence added — clean causal story).
  - Every clean request (41) and variant (82): valid JSON string, `clean_text` no-op, under
    512 tokens for **both** tokenizers (special tokens, no truncation).
  - Coverage: all 82 = `not_targeted`, zero targeted controls, construction rationale
    (CONTRACTS 6.5). Core `coverage_map.json` not touched.
  - Exposure recorded verbatim in substance: "authored after the evaluated defenses were
    frozen; the authors were aware of the defenses; not a blind holdout and not
    design-independent."
- **Review / tier status (honest):** all AI-drafted; `reviewer=null`,
  `review_method=ai_drafted_pending_human_review`, `author="AI draft (Claude Code); Task 4
  owner: Lamei"`. Proposed tiers **SILVER 50 / REVIEW 32** (no GOLD — nothing human-reviewed);
  semantic risk low 50 / medium 22 / high 10. Every high-risk (noisy/garbled/short/mixed)
  candidate is proposed REVIEW and kept visible; noisy dair-ai seeds retained, not swapped.
- Review sheet for humans: `attacks/data/oces/oces_review_sheet.csv` (`Lamei_decision` blank).

## 6. Model inference
**No model prediction (inference) has been run on any seed or variant, in any phase.** The
only model assets touched were the two tokenizers (length counting) and, in one test, the
frozen `clean_text` sanitizer (a pure string op). Recorded in the OCES provenance
(`no_model_inference: true`). If anyone runs predictions later, that execution identity must
be recorded and disclosed as exposure.

## Commands run and real output
Run from repo root with the project venv (`TOKENIZERS_PARALLELISM=false`):
- Regenerate sentiment baseline: `python -m baseline.build_sentiment_baseline` → 42 rows,
  21/21, 0 exclusions; hashes above (reproduces byte-for-byte).
- Regenerate OCES: `python -m baseline.oces.build_oces` → 21/20 seeds, 82 variants, 41 clean
  requests checked; tiers SILVER 50/REVIEW 32; coverage not_targeted 82 (reproduces).
- Core fingerprint check: `python verify_phase0.py` → MATCH (build- and send-order).
- Owned-scope tests: `python -m pytest tests/test_oces.py tests/test_attacks_isolation.py
  tests/test_sentiment_baseline.py tests/test_attacks_coverage.py tests/test_attacks.py
  tests/test_baseline.py -q` → **113 passed**.
- Full suite (with the two required deselects, below) → **732 passed, 30 skipped, 2 deselected**.

## Real run vs fixtures; skips
- All evidence here is from **real generation runs** (deterministic builders) and the test
  suite — not fixture-rendered pages. No endpoint/report demonstration is claimed by this
  handover.
- **30 skipped**: pre-existing browser/UI/model-weight-gated tests outside my scope. My own
  guarded tests (real-tokenizer sentiment count, OCES rebuild parity, `clean_text` mirror ==
  frozen sanitizer) **ran** (assets cached), not skipped.
- **2 deselected — pre-existing CRLF/LF environment failures, NOT my regression**, confirmed
  by running them on the pristine foundation:
  `tests/test_stage3_foundation.py::TestPreservedEvidence::test_defense_freeze_point_still_matches_the_checked_in_file`
  and `tests/test_stage3_foundation.py::TestFixturePack::test_builder_is_deterministic`
  (the latter also rewrites `tests/fixtures/stage3/`; `git checkout -- tests/fixtures/stage3/`
  to clean). They pass on the team's Windows/CI. Deselect locally on macOS.

## What still needs integration / could not be done here
- **OCES human review + freeze (Phase 5):** Lamei reviews `oces_review_sheet.csv` → GPT
  semantic sign-off → apply decisions (adjust tiers/text, fill `reviewer`) → freeze commit.
  **Blocked on:** Ahsan confirming the canonical V2 identity (`endpoint/v2.py` blob
  `b71787e3`). After the freeze commit exists, a separate provenance record references it
  (a commit cannot embed its own hash). **TODO (freeze):** freeze commit SHA + time,
  final tier/reviewer values, final OCES file hashes.
- **PR (Phase 6):** open `stage3/lamei` → `stage3/integration`, reviewer Ahsan, after freeze.
- **Runtime acceptance (Rayyan/Task 2):** sentiment weights load at the pinned revision and
  serve the pinned label space; no truncation on the sentiment path. Not run here (no weights
  loaded).
- **Governance for Ahsan:** (1) confirm canonical V2 identity = git blob `b71787e3`;
  (2) approve the four coverage-class definitions as clarification of CONTRACTS 6.5 (names
  unchanged).
