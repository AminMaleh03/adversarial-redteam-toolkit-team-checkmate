# Handover — Lamei (Task 4: attack coverage, sentiment data, suite isolation, OCES)

> **STATUS: COMPLETE — OCES FROZEN. Ready for Ahsan's review of the PR into
> `stage3/integration`.** All of Task 4 (Phases 0–6) is authored, frozen, tested and pushed.
> No merge has happened; Ahsan reviews and accepts. No model inference was run for Task 4.

## Identity
- Branch: `stage3/lamei`. Handover is the head commit of this branch at review time (the
  commit that adds this finalized file); the two freeze commits below are its parents.
- Foundation: `257e15f3432aa29a3942d52b2cf3befb12ba3354` (tag `stage3-foundation-v1`).
- Canonical `endpoint/v2.py` git blob: `b71787e3bf39e4062f883c9e34fae78d5b7c6263`
  (cross-platform content id). LF sha256 `b71193bef639410c828ec78e9aacc172e5da6a1c3b9fd8e5f7041ee6afc78baf`;
  foundation-recorded CRLF sha256 `cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e`
  (the CRLF value is a Windows-checkout artifact; the git blob is the identity). `endpoint/v2.py`
  is unchanged by Task 4 (verified before and after freeze).
- Emotion model/tokenizer: `j-hartmann/emotion-english-distilroberta-base` @
  `0e1cd914e3d46199ed785853e12b57304e04178b`; labels (anger, disgust, fear, joy, neutral,
  sadness, surprise); limit 512.
- Sentiment model/tokenizer: `distilbert/distilbert-base-uncased-finetuned-sst-2-english` @
  `714eb0fa89d2f80546fda750413ed43d93601a13`; labels `("NEGATIVE","POSITIVE")` uppercase;
  limit 512.
- SST-2 dataset: `stanfordnlp/sst2` @ `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb`, `validation`
  split; file `data/validation-00000-of-00001.parquet` sha256
  `fb00fe008f6828f86ba2beda8415a4cf5da0c884f21c5f238c87131b5aa19529` (872 rows, 428 neg / 444 pos).

## Ownership
Changed only `attacks/**`, `baseline/**`, `tests/test_attacks*`, `tests/test_baseline`
(no edits — Khalid's), `tests/test_sentiment_baseline.py`, `tests/test_oces.py`, and this
file. `contract.py`, `endpoint/**`, runner/analysis/report/UI: untouched.

## Commits (this task)
`d57ee45` Phase 1 coverage map · `36ff45e` Phase 1 fixes · `e81020c` Phase 2+3 · `344119c`
Phase 2/3 hardening · `6abef0e` Phase 4 candidates · `28942a5` Phase 4 audit fixes ·
`5e01825` **Freeze A (case-content)** · `f619e51` **Freeze B (provenance)** · this handover.

## Core preservation (emotion)
- Original emotion baseline bytes/ids unchanged; historical benchmark evidence
  (`artifacts/benchmark_v6/**`) byte-identical to foundation (verified: no diff).
- Original core payload suite fingerprint
  `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430` **reproduces** from the
  live baseline (build-order and send-order), matching the foundation's recorded
  `planned_suite_sha256`. New metadata changes only a new manifest, never the fingerprint.
- Emotion core generated count: **1886**. Sentiment core generated count: **1889**
  (its own deterministic count; content-driven; never copied from emotion).

## Coverage (Phase 1)
- `attacks/coverage_map.json` **v1.0.0**, sha256
  `93f706e64d5b46da89f91cbf7a33bb8bcf32e27149a4dbbffe0d62f489a8a90c`. Classified from
  construction + control design, **never** from observed V1/V2 results. 61 canonical
  subfamilies + 3 approximate-mode boundary variants = 64 map entries.
- Distribution — keep the two denominators distinct:
  - by case: **1,220 / 1,886 generated core cases = 64.7% not_targeted**
    (in_scope 655, out_of_scope 6, mixed 5).
  - by subfamily: **19 / 61 canonical subfamilies ≈ 31.1% not_targeted**
    (in_scope 34 incl. 3 approx, out_of_scope 6, mixed 5).
  - Do **not** phrase this as "65% of attack families are outside the controls."
- Historical overlay `attacks/overlays/coverage_overlay_benchmark_v6.json` (1,886 entries)
  carries its own provenance/hashes; the archived manifest is unmodified.

## Suite / task isolation (Phase 2)
- `build_suite(baselines, *, token_counter=None, max_tokens=None, suite="core",
  task_id="emotion_7")` — kw-only, legacy defaults; unknown suite/task_id → `ContractError`;
  `suite="oces"` refused (OCES is frozen data, not synthesised). `task_id` is validated only,
  not stored in per-attack metadata (executed-row task identity is recorded in run provenance
  by the runner). Build + `write_manifest` run in one `scoped_registry()` (clears on entry,
  restores both dicts on exit). Fixed a Phase-1 idempotency bug so a second build in a shared
  registry (run_all's Demo/Full → Lab) no longer trips the metadata guard.

## Sentiment core baseline (Phase 3)
- `baseline/build_sentiment_baseline.py` → `baseline/sentiment_baseline.json`
  (sha256 `33077982…c87bd2`) + `baseline/sentiment_provenance.json` (sha256 `a96ac928…81805f`).
- **42 SST-2 validation baselines, 21 NEGATIVE + 21 POSITIVE**, SEED=20260915 (authored by
  Task 4, not foundation-prescribed), deterministic **model-free** selection (mechanical
  validity + de-dup → one seeded permutation per label). Text verbatim (SST artefacts kept);
  labels uppercase; id = `sst2-val-<idx>`; **0 exclusions**; selection independent of any
  model output. Provenance keeps the per-row source mapping out of `BaselineCase`.

## OCES additional evaluation (Phase 4/5 — FROZEN)
- Seeds (deterministic, model-free): **21 emotion** (3 per each of 7 labels) + **20 sentiment**
  (10 per label) → `baseline/oces/{emotion_seeds,sentiment_seeds}.json`. Seed `text` is the
  OCES clean request = `clean_text(raw source)` (sanitation-invariant); raw source retained in
  provenance. Core baselines untouched.
- Variants: 1 paraphrase + 1 neutral distractor per seed → **42 emotion + 40 sentiment = 82**;
  **41 clean requests + 82 variants = 123 total additional requests**; **41 paraphrases /
  41 neutral distractors** → `attacks/data/oces/{emotion_cases,sentiment_cases}.json`.
  - Families `oces.paraphrase` / `oces.distractor` only; relation=invariant; oracle=
    `label_should_match_baseline`. No negation, directional oracle, or confidence-drop rule.
  - Distractor = `clean_request + " " + neutral_clause` (exact request prefix; only a neutral
    sentence added). Every clean request and variant: valid JSON string, `clean_text` no-op,
    under 512 tokens for **both** tokenizers (special tokens, no truncation; observed max ~57).
  - Coverage: all 82 `not_targeted`, zero targeted controls, construction rationale
    (CONTRACTS 6.5). Core coverage_map.json not touched.
- Tiers **SILVER 50 / REVIEW 32**; semantic risk low 50 / medium 22 / high 10.
- Review: author = **AI draft (Claude Code)**; reviewer = **Lamei (Task 4 owner)**; review
  method = **human semantic review by Lamei, assisted by ChatGPT**. **0 deleted / 0 rewrites**
  after final review; **no GOLD promotion** merely because human review happened; ambiguous /
  noisy examples intentionally retained as REVIEW. Review sheet
  `attacks/data/oces/oces_review_sheet.csv`: `Lamei_decision` = APPROVE (50) / KEEP_REVIEW (32).
- Exposure (CONTRACTS 6.6): "additional evaluation authored after the evaluated defenses were
  frozen; the authors were aware of the defenses; not a blind holdout and not design-independent."

## Freeze
- **Freeze A (case-content):** `5e01825f7e399ae2019671f0f964b6b83be52a71`
- **Freeze UTC:** `2026-09-15T11:34:47Z`
- **Provenance B:** `f619e513bdd10f5eb5c94830ce9efc3f11c28c4a`
  (`attacks/data/oces/freeze_provenance.json`, references Freeze A; alters no frozen content).
- Content-hash artifact `attacks/data/oces/freeze_content_hashes.json` (does not hash itself).
  Frozen artifact SHA-256s:
  - `baseline/oces/emotion_seeds.json` `d5cc6011848ad5800fdfbb2b006a2cc77e7f8de0bd0d6cef3e5d012565951af3`
  - `baseline/oces/sentiment_seeds.json` `a16e5c999c68fc20e685e793b7cfd3e6de38cf49cfc70ebf1e42a833390fd2c5`
  - `attacks/data/oces/emotion_cases.json` `f2e8e394f8cb90cf9dab6de225bb8033868f72ee273f7ea61516a5ff1af65863`
  - `attacks/data/oces/sentiment_cases.json` `053737c338ae0102807e7099963817de33c6d89c972d4e87d93226d504799e04`
  - `attacks/data/oces/provenance.json` `003bdaaaa87aea39f952fbcc0778f419e9be5562eca8b725ac0967c72ea08b85`
- Defense identity used for authoring/freeze: foundation `257e15f…`, `endpoint/v2.py` blob
  `b71787e3…` (verified unchanged).

## Inference disclosure
No prediction, model forward-pass, label query, confidence query, or outcome-based selection
occurred before the OCES freeze. Pinned tokenizers were used for length checks. `endpoint.v2`
was imported only for sanitizer-equivalence validation; **this may load model assets but no
inference was executed.** (`model_inference_before_freeze = false` in the freeze provenance.)

## Tests — real runs (not fixtures)
Run from repo root, project venv, `TOKENIZERS_PARALLELISM=false`.
- Targeted Task 4: `pytest tests/test_oces.py tests/test_attacks_isolation.py
  tests/test_sentiment_baseline.py tests/test_attacks_coverage.py tests/test_attacks.py
  tests/test_baseline.py -q` → **118 passed**.
- Full suite (with the two deselects below): **737 passed, 30 skipped, 2 deselected** (~34s).
- Determinism: sentiment baseline, coverage map, and OCES builders each reproduce byte-for-byte.
- All evidence here is from real generation/test runs, not fixture-rendered pages.

### Skip / deselection explanation (do not read as "30 unexplained skips")
- **30 skipped, none relevant to Task 4:** 27 in `tests/test_ui_browser.py` (browser
  acceptance, gated behind `REDLAB_BROWSER_TESTS=1`, off by default — Ahsan's UI) + 3 in
  `tests/test_report.py` (native PDF renderer unavailable on this machine — report area,
  external asset). My own asset-gated tests (real pinned-tokenizer sentiment count, OCES
  rebuild parity, frozen `clean_text` equivalence) **ran** (assets cached), not skipped.
- **2 deselected — pre-existing CRLF/LF environment failures on macOS, NOT a Task 4
  regression** (confirmed by running them on the pristine foundation): 
  `tests/test_stage3_foundation.py::TestPreservedEvidence::test_defense_freeze_point_still_matches_the_checked_in_file`
  and `tests/test_stage3_foundation.py::TestFixturePack::test_builder_is_deterministic`.
  They pass on the team's Windows/CI. The latter also rewrites `tests/fixtures/stage3/`;
  `git checkout -- tests/fixtures/stage3/` to clean.

### Acceptance / failure coverage (all fail loudly)
unknown subfamily; duplicate attack id; orphan baseline; missing/invalid coverage metadata;
invalid deterministic selection (insufficient pool); scoped-registry contamination / nested +
failed-scope restore; emotion→sentiment→emotion isolation; sentiment rebuild determinism; OCES
exact count/family/oracle; tokenizer bounds (special tokens, no truncation); frozen sanitizer
equivalence; freeze-hash integrity; freeze-provenance → Freeze A linkage.

## Remaining integration requirements
- **Freeze identity must be handed to Ahsan / Rayyan / Khalid** (Freeze A `5e01825…`,
  Provenance B `f619e51…`, defense blob `b71787e3…`).
- Any OCES **execution is post-freeze** and must record its own execution identity; no
  tuning, case removal, or defense change based on OCES results.
- Any late change to frozen data requires a **new visible version** and coordinated
  revalidation — never a silent amendment.
- **PR:** `stage3/lamei` → `stage3/integration`, reviewer **Ahsan** (no self-merge). Ahsan
  accepts the exact handover commit.
- Runtime acceptance (Rayyan/Task 2): sentiment weights load at the pinned revision and serve
  the pinned label space; no truncation on the sentiment path. Not run here (no weights loaded).
