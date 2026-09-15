# Task 3 handover — Khalid: analysis v3, coverage, remediation, CI policy

Branch `stage3/khalid`, based on the frozen foundation `257e15f3432aa29a3942d52b2cf3befb12ba3354`.

Written for Ahsan's acceptance. It records what is implemented and tested, what is verified
against **real preserved evidence** versus **synthetic fixtures**, and what still needs a live
integrated run that I could not perform from this branch.

---

## 1. Commits

| SHA | What |
| --- | --- |
| `f6a74d7` | Run identity and declared label space (item 1, validation layer) |
| `14ccf34` | Schema v3 envelope (item 1, shape layer) |
| `3b5af88` | Pairing identity, coverage, OCES, remediation, pure CI policy (items 1, 3-6) |

Final SHA is the branch tip at the time the PR is opened; see the PR head.

### Changed files

**New:** `analysis/coverage.py`, `analysis/oces.py`, `analysis/remediation.py`,
`analysis/remediation_rules.json`, `analysis/policy.py`, `tests/test_policy.py`,
`tests/test_analysis_identity.py`, `tests/test_analysis_coverage_oces.py`,
`docs/stage3/handoffs/khalid.md`.

**Modified:** `analysis/validation.py`, `analysis/drift.py`, `analysis/analyze.py`,
`analysis/compare.py`, `tests/test_analysis_remediation.py`.

Nothing outside `analysis/**`, `tests/test_analysis*`, `tests/test_policy.py` and this
handoff was touched. `contract.py`, `runner/`, `endpoint/`, `attacks/`, `baseline/`,
`report/`, `web/` and the shared fixtures are unmodified.

---

## 2. Test results

```
.venv/Scripts/python.exe -m pytest tests/test_analysis.py tests/test_analysis_identity.py \
    tests/test_analysis_coverage_oces.py tests/test_analysis_remediation.py \
    tests/test_policy.py tests/test_baseline.py -q
343 passed in 3.20s
```

| File | Tests |
| --- | --- |
| `tests/test_analysis.py` | 139 |
| `tests/test_analysis_remediation.py` | 75 |
| `tests/test_analysis_coverage_oces.py` | 44 (new) |
| `tests/test_analysis_identity.py` | 37 (new) |
| `tests/test_policy.py` | 29 (new) |

Import rule re-checked: `analysis/` imports only stdlib, `contract` and same-package
`analysis.*`. No `attacks`, `runner`, `endpoint` import anywhere in the package.

---

## 3. Original-number reconciliation (real evidence)

Reanalysis of the byte-preserved run in `artifacts/benchmark_v6/run/` against the published
`artifacts/benchmark_v6/analysis/analysis.json`:

| Metric | Reanalysis | Published | |
| --- | --- | --- | --- |
| emotion_v1 qualifying flips | 218 | 218 | match |
| emotion_v1 eligible comparisons | 1370 | 1370 | match |
| emotion_v1 unhandled 5xx | 91 | 91 | match |
| emotion_v1 findings | 29 | 29 | match |
| emotion_v2 qualifying flips | 112 | 112 | match |
| emotion_v2 eligible comparisons | 1373 | 1373 | match |
| emotion_v2 findings | 14 | 14 | match |
| findings resolved / remaining / new | 15 / 14 / 0 | 15 / 14 / 0 | match |

Manifest SHA-256 of the preserved run:
`0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717`.

Per-category eligible/failed on emotion_v1, derived from the actual manifest and selection:
malformed 4/21, boundary 1/11, perturbation 45/377, encoding 104/931, whitespace 68/210,
truncation 88/168.

**Nothing was adjusted to make these agree.** The reproduction was established before any
refactor and re-checked after every commit; it is the regression guard for this branch.

---

## 4. Public interfaces

```python
# identity and validation
analysis.validation.resolve_identity(rows, *, labels=None, target_id=None,
                                     suite_id=None, expected_version=None) -> Identity
analysis.validation.validate_rows(rows, expected_version=None, *, labels=None, identity=None) -> str
analysis.validation.validate_run(rows, meta, manifest, version, manifest_sha, *,
                                 labels=None, identity=None) -> None

# drift (labels threaded through its internal validate_rows)
analysis.drift.compute_drift(results, manifest, *, labels=None, identity=None) -> DriftSummary

# v3 documents
analysis.analyze.run_analysis_from_dir(run_dir) -> dict           # schema_version 3
analysis.analyze.run_single_target_analysis(...) -> dict          # comparison: null
analysis.analyze.build_evaluation_block(...) -> dict
analysis.analyze.legacy_v2_view(document) -> dict                 # v2 projection

# pairing
analysis.compare.check_pairing_identity(meta_a, meta_b) -> PairingCheck

# coverage
analysis.coverage.load_coverage_map(document, *, sha256, source) -> CoverageMap
analysis.coverage.build_coverage(...) -> dict
analysis.coverage.rate(numerator, denominator) -> dict
analysis.coverage.matched_delta(rate_a, rate_b, common_denominator) -> dict

# OCES
analysis.oces.classify_case(...) -> CaseOutcome
analysis.oces.build_oces_block(*, outcomes_by_target, seed_hashes=None) -> dict

# remediation
analysis.remediation.load_rules(path=None) -> dict
analysis.remediation.build_remediation_detail(...) -> dict
analysis.remediation.build_finding_remediation_string(detail, finding) -> str

# policy
analysis.policy.evaluate_policy(*, policy, analysis, run_metas, results_by_target) -> GateOutcome
```

---

## 5. Example v3 output

Paired (the preserved emotion run):

```json
{ "schema_version": 3, "contracts_version": "3.0.0",
  "run_identity": {"run_id": "f5dc2d3d8135", "provenance": "inferred_legacy", ...},
  "evaluations": [{
    "evaluation_id": "emotion.core", "kind": "paired",
    "task_id": "emotion_7", "suite_id": "core",
    "targets": ["emotion_v1", "emotion_v2"],
    "summaries": {"emotion_v1": {...}, "emotion_v2": {...}},
    "comparison": {...}, "coverage": null, "oces": null }],
  "limitations": [...] }
```

Single target: identical envelope, `"kind": "single"`, one target, and
`"comparison": null` — always present, never `{}`, never a fabricated improvement.
`build_evaluation_block` **raises** if a single-target block is handed a comparison, so the
null is structural rather than a convention someone can forget.

Legacy provenance is explicit. The preserved run declares no target, so its
`v1 -> emotion_v1` mapping appears under `identity.inferred` with its reason and rule, and
`identity.declared.target_id` is `null`. A reader cannot mistake it for a declaration.

---

## 6. Coverage

Counts derive from the actual manifest and selection. The 643/1,217/26 split from the early
draft is **not** implemented and is not a target.

- Classes: `in_scope`, `out_of_scope`, `not_targeted`, `mixed`, plus `undeclared`.
- Per class: planned / selected / completed, the five eligibility buckets
  (`eligible_pass`, `eligible_fail`, `review`, `diagnostic`, `unevaluable`), unique failure
  numerator and an explicit denominator.
- Not-selected and not-executed ids stay visible separately.
- Per-control totals overlap by construction and carry a note saying they must not be
  summed as a partition.
- Zero denominator → `rate: null`, never `0`.
- New data with no declaration **fails validation**; the historical run's undeclared
  attacks are counted as `undeclared`, never given an invented class.
- Labels are intent only. The block states that a class is not effectiveness and not causal
  attribution, that the error handler is cross-cutting with no isolated causal proof, and
  that strict type/schema cases still exercise a declared control where both wrappers
  already reject at the framework layer.

**Not yet populated for the benchmark:** `coverage` is `null` in the emitted block because
Lamei's overlay does not exist yet. See section 9.

---

## 7. Remediation rules

`analysis/remediation_rules.json`, version `1.0.0`, SHA-256
`829a3f8942430d885620f2c4736d9ad54332343d4f2aa16415cc33705d26b894`, 11 rules.

Selection is by observed failure mode + family + subfamily, most specific first — never one
rule per sequential finding number. Coverage of the real observed combinations:

| Rule | Covers |
| --- | --- |
| `RM-5XX-OVERSIZED` | unhandled_5xx on `oversized_*` |
| `RM-5XX-OVERLENGTH` | unhandled_5xx in truncation/boundary |
| `RM-5XX-GENERIC` | any other unhandled_5xx |
| `RM-INVALID-ACCEPTED` | invalid_input_accepted |
| `RM-LEAK` | info_leak |
| `RM-TIMEOUT` | timeout |
| `RM-UNAVAILABLE` | service_unavailable |
| `RM-FLIP-MODEL` | prediction_flip (model-level) |
| `RM-FLIP-NORMALISABLE` | prediction_flip on homoglyph families |
| `RM-SLOW` | slow_response |
| `RM-FALLBACK` | anything unmatched, flagged `is_fallback` |

Constraints enforced and tested: a generic 500 is described as an observed server-error
response and never as a crash, process death or leak; a token limit is never claimed to stop
oversized HTTP bodies; model-level weaknesses get an evaluation/retraining procedure and a
stated limitation instead of an invented endpoint control; unavailable evidence is listed
rather than filled in; verification names the **affected** target, so a sentiment finding is
never verified by re-running `emotion_v2`.

---

## 8. Policy

`analysis.policy.evaluate_policy` is pure — a test asserts the module source contains no
file, network, subprocess or model access.

Blocking: policy validity, candidate identity and model revision, selection and manifest
hashes, selection integrity and completion, coherent clean responses in the declared label
space with complete finite score vectors, approved clean-label agreement, zero selected
5xx, zero timeouts/transport failures, health after every selected request, zero leak
signatures (with the detector's limits stated), and documented rejection behaviour where the
policy names cases that must be rejected. A missing response is **never** counted as a
rejection.

Informational only: ground-truth baseline accuracy (reported separately from reference
agreement — the reference is not assumed correct), slow counts, flip rates.

Outcomes: `execution_error` (2) for invalid/draft policy, bad identity, or untrustworthy or
incomplete evidence; `policy_failure` (1) for well-recorded candidate defects; `pass` (0)
otherwise. Structural errors take precedence. Zero executed checks cannot pass.

Artifact hashes as committed:

| Artifact | SHA-256 |
| --- | --- |
| `analysis/case_sets/ci_core_v1.json` | `25573a71931259a3da4241af4ee507314544fd783f796c74c32d0fa88c56ec9d` |
| `analysis/policies/ci_core_v1_clean_reference.json` | `19ea965fc988fa10238e148e0ef934c22290a762bf177aa4e05260535d3c4034` |
| `analysis/remediation_rules.json` | `829a3f8942430d885620f2c4736d9ad54332343d4f2aa16415cc33705d26b894` |

---

## 9. Remaining integration requirements — for Ahsan's acceptance

### 9.1 Ahsan — the v3/v2 renderer and orchestrator (his Task 1 item 2)

Emitting v3 breaks two of his files at runtime. I could not edit them and did not.

- `run_all.py:544-545` reads `analysis["summary_v1"]` / `["summary_v2"]` → now `KeyError`.
- `report/generate.py:245` requires `schema_version == 2` exactly → now rejects the document.

Their own tests still pass, because they construct fixtures rather than calling
`run_analysis_from_dir`, so this will first appear at integration. `analysis.analyze.legacy_v2_view(doc)`
returns exactly `{schema_version: 2, summary_v1, summary_v2, comparison}` as a one-line
bridge if the smallest possible change is wanted.

### 9.2 Lamei — the coverage overlay (her Task 4)

`coverage` is `null` in the emitted evaluation block. `analysis/coverage.py` implements the
join, the classes, the buckets and the denominators, and is tested against synthetic
overlays — but the real per-class numbers need her overlay keyed by `attack_id` carrying
`coverage_class`, `controls_targeted`, `coverage_rationale` and `coverage_map_version`.
I did not invent a map: an unknown declaration fails for new data by design.

### 9.3 Lamei / Rayyan — OCES cases and execution

`oces.py` is implemented and tested, but no OCES suite exists yet. The block stays absent
until her cases and a real run exist.

### 9.4 Rayyan + Ahsan — the gate demonstration (CONTRACTS 7.4)

**This cannot be completed from this branch and nothing here should be presented as a real
gate demonstration.** §7.4 requires resolving `ci_core_v1`'s manifest and coverage hashes
from a real `ci.emotion` run, which needs Rayyan's runner and live endpoints. Until then the
policy **raises** on an unresolved selection, which is the specified behaviour: a draft
policy never passes, never warns-and-continues and never substitutes a placeholder.

The controlled regression demonstration (remove the V2 length guard → `policy_failure`,
restore → `pass`) likewise needs the live candidate. The policy code and its full negative
matrix are tested; the demonstration is not done.

### 9.5 Contract discrepancy for Ahsan to rule on

`analysis/case_sets/ci_core_v1.json` has **no `status` field**, but CONTRACTS §7.4 says to
"flip `status` from `draft` to `frozen`". Its shape also differs from §5.2: it has
`standalone_attack_ids` / `derived_attack_ids` / `counts` rather than `attack_ids`, `order`
and `selection_version`.

I did not edit the file or the contract. `policy.py` treats **unresolved hashes** as the
draft signal, which satisfies §7.4's intent (an unresolved policy cannot pass) without
requiring an amendment. If you want the literal `status` field, that is a foundation change
and yours to land.

---

## 10. Evidence: real versus fixture

**Real** — the byte-preserved `artifacts/benchmark_v6` run: 1,928 rows per target, its own
manifest and metadata. All reconciliation numbers in section 3 come from it.

**Synthetic** — everything in sections 6, 7 and 8. Coverage maps, OCES outcomes, policy
candidates and remediation rows in the tests are constructed fixtures demonstrating contract
behaviour. They are **not** evidence that any feature works end to end against live
endpoints, and none of them is a gate demonstration.

No live endpoint was started, no model was loaded, and no new benchmark was produced on this
branch.
