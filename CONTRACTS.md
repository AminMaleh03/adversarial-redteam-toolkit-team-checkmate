# CONTRACTS.md — version 3.0.0

The normative description of every interface four people build against. **Owner: Ahsan.**

`contract.py` is the single import path for every shared type named here. There is no
second definition of any of them anywhere in the repository — if you find one, that is the
bug. Function signatures below are frozen: implement them exactly, and if one is wrong,
request an amendment (procedure at the end) rather than changing it locally.

Reading order: [`docs/stage3/FINAL_PLAN.md`](docs/stage3/FINAL_PLAN.md) for the decisions,
this file for the shapes, [`docs/stage3/OWNERSHIP.md`](docs/stage3/OWNERSHIP.md) for who
edits what, `tests/fixtures/stage3/` for worked examples of everything below.

**Status of each item** is marked: **[frozen]** exists and is committed; **[contract]** is
specified here and implemented by a named task. A `[contract]` item has no production
implementation yet, and there is no stub returning canned success — test doubles live in
tests only.

---

## 0. What changed in 3.0.0

| Change | Compatibility |
| --- | --- |
| `RunResult` gains four appended fields | Additive with defaults. Every existing positional construction and every historical row still loads. |
| New shared structural types in `contract.py` | Purely additive. |
| `CONTRACTS_VERSION = "3.0.0"` | New. |
| `BaselineCase`, `AttackCase`, `Finding` | **Structurally unchanged.** |
| Analysis schema | v3 introduced; v2 still readable, and v2 bytes on disk are never rewritten. |

Nothing in 3.0.0 removes or reorders an existing field.

---

## 1. Identity: the vocabulary everything else uses

| Term | Values | Meaning |
| --- | --- | --- |
| `task_id` | `emotion_7`, `sentiment_2` | A classification task: one label space, one default baseline file. |
| `target_id` | `emotion_v1`, `emotion_v2`, `sentiment_v1` | One servable endpoint. **This, not `version`, identifies what produced a row.** |
| `version` | `v1`, `v2` | Legacy field, kept for compatibility. `sentiment_v1` is `version="v1"`. Never infer a model or a task from it. |
| `suite_id` | `core`, `oces` | Which case family set. **There is no `ci_core`.** CI is a frozen *selection* of `core`. |
| `evaluation_id` | `emotion.core`, `emotion.oces`, `sentiment.core`, `sentiment.oces`, `ci.emotion` | One unit of work. |
| `case_set_id` | `ci_core_v1` today | A frozen selection within a suite. |
| `run_id` | 12+ hex chars | The **enclosing** run. Repeated in each target's `run_meta` as `evaluation_run_id`. |

**Case keys** are unchanged: `baseline:<baseline_id>` and `attack:<attack_id>`.

**The unique key for a result row** is
`run_id + evaluation_id + target_id + <existing case key>`.

**A results file contains exactly one `(target_id, suite_id, version)`.** Mixing them is
an error, not something to partition after the fact.

### The rule that has no exceptions

> A new run must record its identity explicitly. Nothing may infer a model from `version`,
> default an unknown identity to emotion, or fall back to emotion after a malformed new
> run. Blank identity is supported **only** for recognised historical artifacts.

Legacy routing is explicit: a document is either recognised as a known legacy layout —
and then routed through the emotion legacy adapter with `v1→emotion_v1`, `v2→emotion_v2`
recorded as **inferred** provenance — or it is rejected as unrecognised. There is no third
path. See `tests/fixtures/stage3/negative/ambiguous_legacy.json`.

---

## 2. `contract.py` — the shared types **[frozen]**

### 2.1 Unchanged

`BaselineCase(baseline_id, text, label, source)` — structurally unchanged.

`AttackCase(attack_id, baseline_id, category, original_text, attacked_text, is_raw=False,
raw_body=None, raw_headers=None)` — structurally unchanged. `baseline_id=None` still means
a standalone payload with nothing to compare against. `is_raw=True` still means **send
these bytes verbatim**: do not re-serialise, do not repair invalid UTF-8, do not let the
HTTP client build its own headers.

`Finding(finding_id, title, category, severity_score, severity_tier, description,
remediation, evidence=[])` — structurally unchanged, including `remediation` before
`evidence`. Construct with keyword arguments.

### 2.2 `RunResult` — four appended fields

| Field | Type | Default | Producer | Consumer | Meaning and rules |
| --- | --- | --- | --- | --- | --- |
| `target_id` | `str` | `""` | runner | analysis, policy, report | Which target produced the row. `""` **only** for historical rows. A new run must set it. |
| `suite_id` | `str` | `""` | runner | analysis, policy, report | `core` or `oces`. `""` historical-only, meaning the original core suite. |
| `request_body_bytes` | `int \| None` | `None` | runner | analysis, remediation | Length in bytes of the **exact serialised body that was sent**. |
| `request_body_sha256` | `str \| None` | `None` | runner | analysis, remediation | SHA-256 hex of those same bytes. |

Rules for the request-byte evidence, which exists because the old reports guessed at it:

- It is **sender-recorded and authoritative**. Capture it from the prepared request body
  the HTTP client is about to put on the wire, then send that same request.
- It is **never** a character count, a response length, or a manifest text length.
- It is present on baseline rows and attack rows alike, and it survives transport failure:
  a request that got no response still has a known attempted body.
- If serialisation fails before any bytes exist, record `None` **and** record the reason;
  that is an execution failure, not a zero-byte body.
- `None` means unavailable. It never means zero. A historical row is always `None`, and no
  amount of later analysis can reconstruct it — see
  `artifacts/benchmark_v6/PROVENANCE.md`.

### 2.3 Registry types

All model-free. Importing them loads no weights and imports no endpoint module.

```python
ModelSpec(model_id, revision, tokenizer_id, tokenizer_revision, labels, max_sequence_length, notes="")
TaskSpec(task_id, model_ref, baseline_file, description="")
TargetSpec(target_id, task_id, version, module, app_attr="app", port=0, hardened=False, description="")
EvaluationSpec(evaluation_id, kind, task_id, suite_id, target_ids, declared_families,
               case_set_id=None, baseline_file=None, mode="standard", description="")
Registry(registry_version, models, tasks, targets, evaluations, source_path="", source_sha256="")
```

| Type | Field | Notes |
| --- | --- | --- |
| `ModelSpec` | `revision`, `tokenizer_revision` | **Exactly 40 lowercase hex.** `"main"`, a short SHA or a placeholder raises `ContractError` at construction. |
| | `labels` | `tuple[str, ...]` in model id order, **exact case**. Sentiment is `("NEGATIVE", "POSITIVE")`. |
| | `max_sequence_length` | Tokens including special tokens, read from the tokenizer — not a model card's training length. |
| `TargetSpec` | `module` | A dotted string, **never imported** by the registry. `app_path` yields `"module:app"` for uvicorn. |
| | `version` | `v1`/`v2` only. |
| | `port` | Required, unique across targets. `emotion_v1` 8000, `emotion_v2` 8001, `sentiment_v1` 8002. |
| `EvaluationSpec` | `kind` | `paired` requires exactly 2 `target_ids`; `single` exactly 1. |
| | `suite_id` | `core` or `oces`. `ci_core` raises. |
| | `baseline_file` | Evaluation-level **override**. OCES supplies its frozen seed file here. |
| | `mode` | `standard` or `ci`. |

`Registry` accessors — all raise `ContractError` on an unknown id rather than returning
`None`:

```python
registry.target(target_id)        -> TargetSpec
registry.task_for(target_id)      -> TaskSpec
registry.model_for(target_id)     -> ModelSpec
registry.evaluation(evaluation_id)-> EvaluationSpec
registry.baseline_file_for(evaluation_id) -> str
```

**`baseline_file_for` is the only correct way to find an evaluation's baseline.** The
evaluation override wins; otherwise the task default. Resolve it **before** generating the
suite, and record the hash of the file it returns. Recording the core baseline hash for an
OCES run is a defect: it claims the run used data it did not use.

### 2.4 Gate types

```python
CheckResult(check_id, status, reason, evidence_refs=[], observed=None, threshold=None, blocking=True)
GateOutcome(outcome, exit_code, policy_id, policy_version, policy_sha256, candidate,
            reference, suite_id, case_set_id, selection_sha256, checks,
            summary={}, artifacts={}, exclusions=[], schema_version=1)
```

`status` ∈ `pass | fail | error | not_applicable`. `reason` is required even when passing.
`observed=None` means not measured — never substitute zero. `blocking=False` marks an
informational check that is reported and never changes the outcome.

`outcome` ∈ `pass | policy_failure | execution_error`, with exit code **0 | 1 | 2**.
`contract.EXIT_CODE_BY_OUTCOME` is the only permitted mapping and `GateOutcome.__post_init__`
enforces it, along with:

- Zero checks is never a result. Zero executed checks is an `execution_error`.
- `pass` cannot coexist with a failing blocking check.
- All-`not_applicable` is not a pass; at least one blocking check must actually pass.
- `policy_failure` requires a failing blocking check.
- `execution_error` requires a check in status `error`.

These are structural invariants, not style. A gate that cannot say what it checked has not
passed.

### 2.5 Constants

`SUITE_CORE/SUITE_OCES`, `EVAL_KIND_PAIRED/SINGLE`, `EVAL_MODE_STANDARD/CI`,
`OCES_FAMILY_PARAPHRASE/DISTRACTOR`, `OCES_FAMILIES`, `CORE_FAMILIES`, the four
`COVERAGE_*` classes, `CHECK_*`, `OUTCOME_*`, `EXIT_CODE_BY_OUTCOME`, `CONTRACTS_VERSION`,
`ContractError`.

Import the constants; do not retype the strings. A typo should be an `ImportError`, not a
silent mismatch discovered three components downstream.

---

## 3. Registry file and loader **[frozen]**

`endpoint/targets.json` holds the data; `endpoint/targets.py` parses it. Created once by
the foundation; **ownership transfers to Rayyan**.

```python
endpoint.targets.load_registry(path=None) -> Registry            # raises TargetConfigError
endpoint.targets.missing_requirements(registry, evaluation_id, root=None) -> list[str]
endpoint.targets.require_runnable(registry, evaluation_id, root=None) -> None
```

`TargetConfigError` subclasses `ContractError` subclasses `ValueError`.

**Validated at load** — everything knowable from the file: every cross-reference resolves;
revisions are real pins; ports are unique and in range; `module` is a dotted path;
configured paths are syntactically valid repo-relative paths (no `..`, no backslashes, no
absolute paths); an evaluation's targets all belong to its task; `kind` matches the target
count.

**Not validated at load** — whether a module or baseline file *exists*. That is deliberate.
`endpoint/sentiment_v1.py` (Task 2) and `baseline/sentiment_baseline.json` (Task 4) do not
exist yet; if loading required them, the foundation would break the working emotion path
for everyone until both land. Call `require_runnable(registry, evaluation_id)` immediately
before executing an evaluation.

### The five evaluations

| `evaluation_id` | kind | task | suite | targets | baseline file used | mode |
| --- | --- | --- | --- | --- | --- | --- |
| `emotion.core` | paired | `emotion_7` | `core` | `emotion_v1`, `emotion_v2` | `baseline/baseline.json` | standard |
| `emotion.oces` | paired | `emotion_7` | `oces` | `emotion_v1`, `emotion_v2` | `baseline/oces/emotion_seeds.json` | standard |
| `sentiment.core` | single | `sentiment_2` | `core` | `sentiment_v1` | `baseline/sentiment_baseline.json` | standard |
| `sentiment.oces` | single | `sentiment_2` | `oces` | `sentiment_v1` | `baseline/oces/sentiment_seeds.json` | standard |
| `ci.emotion` | single | `emotion_7` | `core` (`case_set_id=ci_core_v1`) | `emotion_v2` | `baseline/baseline.json` | ci |

### The pins

| | repo id | revision | labels | limit |
| --- | --- | --- | --- | --- |
| emotion | `j-hartmann/emotion-english-distilroberta-base` | `0e1cd914e3d46199ed785853e12b57304e04178b` | anger, disgust, fear, joy, neutral, sadness, surprise | 512 |
| sentiment | `distilbert/distilbert-base-uncased-finetuned-sst-2-english` | `714eb0fa89d2f80546fda750413ed43d93601a13` | `NEGATIVE`, `POSITIVE` | 512 |

Dataset for Task 4: `stanfordnlp/sst2` @ `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb`,
`validation` split, 872 rows, columns `idx:int32`, `sentence:string`, `label:int64`
(0→NEGATIVE, 428 rows; 1→POSITIVE, 444 rows). Full detail and the two selection rules are
in [`docs/stage3/MODEL_IDENTITY.md`](docs/stage3/MODEL_IDENTITY.md).

---

## 4. Baseline, attacks and suite metadata → runner

### 4.1 Baseline **[frozen signature]**

```python
baseline.load.load_baseline(path=None) -> list[BaselineCase]
```

Unchanged and still callable with no arguments. Task configuration chooses the file via
`registry.baseline_file_for(evaluation_id)`; the loader itself gains nothing.

`runner.run.main` sorts baselines by `baseline_id` before building and fingerprinting.
"First two in sorted order" is therefore well defined regardless of file order. Keep it.

### 4.2 Attack library **[contract — Lamei]**

```python
attacks.library.build_suite(baselines, *, token_counter=None, max_tokens=None,
                            suite="core", task_id="emotion_7") -> list[AttackCase]
attacks.library.standalone_cases(*, token_counter=None, max_tokens=None) -> list[AttackCase]
attacks.library.build_derived(baseline) -> list[AttackCase]
attacks.library.write_manifest(path) -> None
```

`suite` and `task_id` are new keyword-only arguments with the legacy defaults, so every
existing call keeps its current behaviour. `token_counter`/`max_tokens` are injected by the
caller — the attack library never imports `endpoint.model`.

**The manifest and the execution must consume the same isolated build.** Build once, write
the manifest from that build, run that build.

### 4.3 Registry isolation **[frozen]**

```python
@contextmanager
attacks.metadata.scoped_registry()
```

Snapshot → **clear** → yield → restore exactly, in `finally`. Both `_MANIFEST` and
`_FINGERPRINTS`. Nesting works; an exception inside still restores. Concurrency is handled
by the existing global job lock, not by this scope.

The clearing step is the point. Without it a suite built inside the block inherits every
case already registered in the process, so writing the manifest for an emotion run also
stamps in sentiment cases built a moment earlier — and the analysis then scores results
against an oracle set describing different cases. Snapshot-and-restore alone only protects
what came before.

Existing callers are unchanged; their owners wire this in when they are ready.

### 4.4 Attack metadata additions **[contract — Lamei]**

Frozen names for the new `AttackMetadata` fields. Do not invent variants:

| Field | Type | Meaning |
| --- | --- | --- |
| `suite_id` | `str` | `core` or `oces`. |
| `coverage_class` | `str` | One of the four `COVERAGE_*` values. |
| `controls_targeted` | `list[str]` | From `length`, `strict_type_schema`, `normalization`. **Intended** coverage. |
| `coverage_rationale` | `str` | Why this class, from construction and controls — never from observed results. |
| `coverage_map_version` | `str` | Version of the map this came from. |
| `exposure` | `str` | For OCES: the author-exposure statement. |
| `declared_family` | `str` | `oces.paraphrase` or `oces.distractor` for OCES cases. |

The attack library does **not** compute wire-body bytes. That is the runner's, at send time.

**Historical metadata is never edited.** New coverage data for the preserved benchmark goes
in a separate overlay keyed by `attack_id`, recording its own later creation time, the
source manifest hash and the map hash. The new classification is *not* historically
predeclared and must not be described as such.

---

## 5. Runner → analysis

### 5.1 CLI **[contract — Rayyan]**

| Flag | Status | Notes |
| --- | --- | --- |
| `--target URL` | existing | required |
| `--version v1\|v2` | existing | still works; implies the emotion target explicitly |
| `--target-id ID` | **new** | derives `version`. Supplying both, in conflict, is an error |
| `--suite core\|oces` | **new** | default `core` |
| `--case-set PATH` | **new** | a frozen selection file |
| `--out DIR`, `--limit N`, `--skip ID`, `--predict-path`, `--health-path`, `--timeout`, `--health-timeout` | existing | unchanged |

`--limit` and `--skip` **cannot silently override a frozen CI selection**. Unknown, missing
or duplicate selected ids are errors.

### 5.2 Case-set file

```json
{"case_set_id": "...", "selection_version": 1, "suite_id": "core",
 "baseline_ids": [...], "attack_ids": [...], "order": [...], "exclusions": [...]}
```

Exact ids, exact order. Every derived selected case must have its baseline selected too. A
bounded CI selection still refers to the full `core` suite identity — the planned
fingerprint describes the whole suite, and coverage records what was selected from it.

### 5.3 `run.json` — the enclosing index **[contract — Ahsan]**

`run_id`, `run_name`, `created_at_utc`, `app_commit`, `dirty`, `mode`, `registry`
(snapshot + hash), and `evaluations[]`. Each evaluation entry names its `evaluation_id`,
`kind`, `task_id`, `suite_id`, `declared_families`, `case_set_id`, `baseline_file` and
`target_dirs`.

### 5.4 `run_meta.json` — per target **[contract — Rayyan]**

Everything the old file had, plus: `evaluation_run_id` (the enclosing `run_id`),
`evaluation_id`, `target_id`, `task_id`, `suite_id`, a `model` block (ids, revisions,
labels), a `baseline` block (`path` + `sha256` of the file **actually used**),
`fingerprints.selection_sha256` and `fingerprints.results_sha256`, `case_set_id`, and
`code_provenance` (`app_commit`, `dirty`).

The runner's existing per-invocation `run_id` stays distinct from `evaluation_run_id`.

Worked example: `tests/fixtures/stage3/runs/*/*/run_meta.json`.

### 5.5 When two runs may be compared

Matching target names, or a common task, are **not** sufficient. A comparison requires all
of: same parent run; same task; same **model and tokenizer** revisions; same baseline
identity; identical ordered planned and selected case fingerprints; same coverage-map
version and hash; same relevant analysis settings; and valid manifests on both sides.

If a prerequisite fails on legitimately incomplete runs, **withhold the comparison with an
explicit reason**. If the metadata is corrupt, that is an error.

---

## 6. Analysis v3 **[contract — Khalid]**

```python
analysis.analyze.run_analysis_from_dir(run_dir) -> dict   # schema_version 3
```

### 6.1 Envelope

```
{ "schema_version": 3, "contracts_version": "3.0.0",
  "run_identity": {...}, "evaluations": [...], "limitations": [...] }
```

Each evaluation block: `evaluation_id`, `kind`, `task_id`, `suite_id`, `targets[]`,
`summaries` keyed by `target_id`, `comparison`, `coverage`, `oces`.

**`comparison` is `null` for every single-target evaluation — always present, always
null.** Never omitted, never `{}`, never a fabricated improvement figure. The report
renders a short explanation, not an empty table. `coverage` and `oces` are `null` only
where genuinely inapplicable or explicitly unavailable in a recognised legacy view.

### 6.2 Per-target summary

Keeps the existing shape: `coverage`, `category_stats`, `operational`, `drift`, `findings`,
`validity_tier_census`, `diagnostic_observations`, `review_cases`, `limitations`. Adds
`target_id`, `task_id`, `suite_id` and an `identity` block distinguishing **declared** from
**inferred** provenance.

`findings[]` entries keep `finding` (the frozen `Finding` object), `subfamily`,
`failure_mode`, `validity_tiers`, `affected_cases`, and gain **`remediation_detail` as a
sibling of `finding`** — not a field inside it, and not a replacement for the legacy
`Finding.remediation` string.

### 6.3 Rates and units

Original core rates and `format_rate` behaviour are preserved exactly.

Every **new** rate is an object:

```json
{"numerator": 9, "denominator": 88, "rate": 0.102273}
```

`rate` is a ratio in `[0, 1]`, or **`null`** when the denominator is zero. `null` renders as
`N/A`. **Never convert `N/A` to zero**, and never mix ratios with percentage points: "no
cases were eligible" and "no cases failed" are different claims and only one of them is
supported by an empty denominator.

### 6.4 Drift and paired deltas

Per-target drift keeps the existing rules, including the clean-confidence threshold of
**0.60**. It measures **prediction consistency against that target's own clean
prediction** — it is not accuracy. Clean-label correctness is reported separately.

A paired delta uses the **intersection of eligible case ids in both targets**, and shows
that common denominator. Each target's own eligible denominator stays in its own summary
and is not interchangeable. Subtracting one target's rate from the other's would be a
difference between differently filtered populations, which is not a matched improvement.

### 6.5 Coverage

Classes `in_scope`, `out_of_scope`, `not_targeted`, `mixed`.

- Labels describe **intended input-control coverage**. They are not effectiveness and not
  causal attribution.
- C3 error handling is **cross-cutting**: evaluate its observable responses, claim no
  isolated causal proof.
- Strict type/schema tests exercise a declared control **even when both wrappers already
  reject the input**. State the shared framework behaviour via an `incremental_vs_v1`
  note; do not delete the cases.
- Per-case exceptions where a subfamily is not uniform.
- Selected attacks partition into `eligible_pass`, `eligible_fail`, `review`, `diagnostic`,
  `unevaluable`. Not-selected and not-executed stay visible **separately**.
- One case contributes **at most once** to a failure numerator.
- Within-control counts may overlap and **must not be summed as if disjoint**.
- A new case with no valid declaration **fails validation**; it never receives an invented
  class.

There are no fixed acceptance numbers. The 643/1,217/26 split from the earlier draft was a
hypothesis and is not a target.

### 6.6 Additional evaluation (OCES)

Exactly two families: `oces.paraphrase` and `oces.distractor`, under the existing
invariant / `label_should_match_baseline` oracle. **No negation family, no directional
oracle, no 0.15 score-drop threshold, no new severity weights.**

Every planned case has exactly one per-target status: `meets_expectation`,
`violates_expectation`, `excluded`, `unevaluable`, `not_executed` — with a reason where
one is needed. Semantic rates exclude the last three. An absent prediction is never
counted as successful invariance. Operational failures stay visible and are not semantic
successes.

Tiers: hand authorship alone is **not** GOLD. Anything with a possible meaning, sentiment,
emotion or discourse shift stays `REVIEW`, stays visible, and does not enter automatic
semantic rates. Do not force a case into a scored tier to hit a quota, and do not select or
review content using model predictions.

Required wording, verbatim in substance:

> Additional evaluation authored after the evaluated defenses were frozen; the authors were
> aware of the defenses; not a blind holdout.

Do not call it design-independent. Valid JSON, an acceptable type, bounded tokens and an
unchanged `clean_text` result establish only that those specific input gates accept the
text unchanged. They do not prove the exception handler is irrelevant and they do not prove
semantic preservation.

### 6.7 `remediation_detail`

| Field | Meaning |
| --- | --- |
| `rule_id`, `rule_version`, `rule_sha256` | Which reusable rule produced this. |
| `observed` | Recorded behaviour, with case references. Facts only. |
| `significance` | Why it matters. |
| `diagnosis_confidence` | `supported` (the rows establish it) or `suspected` (consistent with, not established by). Never collapse the two. |
| `fix` | The actual fix, for the actual target. |
| `verification` | `target_id`, runnable `command`, `case_set_file`, `includes_baselines`, `expected`. |
| `unavailable_evidence` | What is missing and why, stated rather than filled in. |

Hard rules:

- **A generic 500 does not establish an internal model crash, process death or a leak.**
  The hardened V2 handler itself returns 500. Say "observed server-error response".
- **A token limit does not protect against oversized HTTP bodies.** Tokenization happens
  after the body is read and parsed. Request-body limits and token-count checks are
  different controls.
- No invented leak, byte count or missing field. Historical raw-body lengths are
  `unavailable` unless reconstructed from exact proven payload bytes and labelled
  `reconstructed`.
- Verification must name the **affected or patched** target, an emitted or committed
  case-set file, the necessary baselines, a runnable command and the exact condition to
  inspect. **Never reroute a sentiment finding to `emotion_v2` as its fix.** Running a
  request collector is not "passing a gate".
- Model-level weaknesses get an evaluation/remediation procedure and an honest statement
  of the limitation — not an invented endpoint control.
- New findings also get a concise, evidence-specific `Finding.remediation` string for
  legacy consumers. **Historical strings are unchanged.**

---

## 7. Policy and gate

### 7.1 Pure policy **[contract — Khalid]**

```python
analysis.policy.evaluate_policy(*, policy, analysis, run_metas, results_by_target) -> GateOutcome
```

Keyword-only. **Pure**: no file, process, network or model I/O. `results_by_target` holds
parsed `RunResult` lists, so operational checks can inspect **every selected request**,
including ones excluded from semantic scoring — without changing historical report scoring
to make that possible.

### 7.2 The first policy

Candidate `emotion_v2` at the candidate revision and pinned model. Reference: the frozen
approved clean-output snapshot from the preserved original run — no second live V1 service
is required.

**Blocking checks:** valid policy and candidate identity, model revision, expected
suite/selection hashes, metadata integrity, non-empty expected selection · all selected
requests accounted for and completed with valid records · every selected valid baseline
returns HTTP 200 with a coherent prediction in the declared label space, finite scores and
the correct score-vector shape · clean top labels match the approved reference on the
frozen ids · **zero** observed 5xx, timeouts, transport failures or failed post-request
health checks · **zero** detected leak signatures (state the detector's limits) · every
case whose oracle requires clean rejection returns an allowed rejection status — a missing
response is **never** counted as a rejection.

**Informational, never blocking:** slow counts, attack flip rates, finding-group counts.
There is no 200-eligible-case minimum, no +0.05 flip tolerance and no 80% positive-control
threshold. Those were removed as unjustified.

Agreement with the approved reference is reported **separately** from ground-truth
accuracy. The reference is not assumed correct.

**Outcomes:** infrastructure, configuration, invalid evidence or no readiness →
`execution_error` (2). A well-recorded candidate failure, including an abort after observed
loss of health → `policy_failure` (1), with unexecuted cases retained. Structural errors
take precedence when results cannot be trusted. **Zero executed checks or a draft policy
cannot pass.** No threshold recalibration during candidate evaluation.

A gate pass claims compliance with this named policy on this selection. It is not
comprehensive model-level adversarial robustness and not production certification.

### 7.3 Gate CLI **[contract — Rayyan]**

```
python -m runner.gate --policy PATH --out DIR [--evaluation ci.emotion] [--html-only]
```

`runner.gate` calls `run_all.run_experiment` and then `analysis.policy.evaluate_policy`.
**`run_all` must never import `runner.gate`** — that reverse edge would be a circular
orchestration dependency. Optional imports are deferred so `--help` and offline tests load
no models.

Emit `gate_result.json` and readable reasons on error paths whenever the destination is
writable. Use `null` for unavailable measured values; never fabricate candidate or
reference evidence. The exit code must reach the shell — do not swallow it after report
generation.

### 7.4 Resolving the hashes that cannot exist yet

`analysis/case_sets/ci_core_v1.json` deliberately contains no manifest or coverage hash,
because only a real feature run can produce those. Khalid resolves them before the first
gate demonstration: run the real `ci.emotion` evaluation, hash the produced manifest and
coverage bytes, write them under an explicit `resolved_from` block naming the run id,
artifact paths and commit, and flip `status` from `draft` to `frozen` in the same change.

**Until then the policy must raise.** A draft policy never passes, never
warns-and-continues, and never substitutes a placeholder.

---

## 8. Orchestration, status and downloads **[contract — Ahsan]**

```python
run_all.run_experiment(mode, run_name=None, results_root=None, progress_callback=None,
                       *, evaluation_ids=None, html_only=False) -> dict
```

Existing positional arguments preserved; `evaluation_ids=None` keeps the original emotion
behaviour exactly. Returns the existing fields plus `run_id` and `evaluations`. Supports
`full`, `demo` and an internal `ci` mode. Browser opening stays CLI-only.

API surface:

| Endpoint | Notes |
| --- | --- |
| `GET /api/targets` | Trusted configured choices only. No free-form URL entry. |
| `POST /api/run` | Existing empty/default request still means emotion. Unknown target or mode → **422** in the agreed shape. |
| `GET /api/status` | Carries `run_id` **and** evaluation identity. |
| `POST /api/lab/run` | Same single global job lock as Demo; **409** while busy. |

**Stale-result rule:** a status response whose `run_id` or evaluation identity differs from
the active run must be **discarded**, not rendered. Switching model clears prior results
and links. Polling a previous run must never overwrite a newly selected view. Example:
`tests/fixtures/stage3/api/status_stale.json`.

Interactive input privacy and existing retention behaviour are preserved: arbitrary user
text never enters committed fixtures or final benchmark evidence.

---

## 9. Approved import edges

Allowed, and nothing else without a recorded amendment:

```
everyone            -> contract
runner.run          -> baseline.load.load_baseline
                    -> attacks.library (public functions)
                    -> endpoint.targets           (model-free; no weights)
                    -> endpoint.model.tokenizer / MAX_SEQUENCE_LENGTH   (existing)
runner.gate         -> run_all
                    -> analysis.policy
run_all             -> runner.run, attacks.library, baseline.load, analysis, report
analysis            -> contract only, plus manifests/overlays read from run ARTIFACTS
report / web        -> analysis output documents, contract
```

Two edges that must not exist:

- **`analysis` must never import from `attacks`.** Oracle data reaches analysis through the
  written manifest and the coverage overlay. That is what makes the oracles
  pre-registered rather than decided after the results are in.
- **`run_all` must never import `runner.gate`.** The gate calls the orchestrator, not the
  other way round.

`endpoint.targets` imports nothing from `endpoint.model`, `transformers` or `torch`. That
is covered by a test, not just by convention.

---

## 10. Amending this contract

1. Do **not** change a shared signature or JSON key locally to make your branch pass.
2. Open a request to Ahsan naming the exact field or signature, why the current one blocks
   you, and what you propose.
3. Ahsan lands a foundation amendment: `contract.py` and/or this file, the fixture pack,
   the version below, and a note in `docs/stage3/DECISIONS.md`.
4. Everyone rebases onto the same amendment. There is never a second definition living on
   one branch.

`CONTRACTS_VERSION` in `contract.py` must match the heading of this file. Additive changes
bump the minor version; anything that could break a consumer bumps the major.
