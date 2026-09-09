# Analysis and report input

Analysis validates the recorded files, evaluates each attack against its manifest oracle,
and emits findings and comparison evidence. The report should consume the emitted JSON;
it should not recompute drift, severity, or resolution, or import attack metadata.

## Run

Use Python 3.11 from the project's `.venv`:

```powershell
.\.venv\Scripts\python.exe -m analysis.analyze results/full_20260909_135157
```

The directory can contain `manifest.json`, `results_v1.jsonl`, `results_v2.jsonl`,
`run_meta_v1.json`, and `run_meta_v2.json` together, or retain the runner's `v1/` and
`v2/` subdirectories with each version's manifest. Both layouts are supported. Store
generated JSON/HTML/PDF under ignored `results/`; preserve original benchmark files.

The Python entry points are `run_analysis_from_dir(directory)` and `run_analysis(...)`.
The latter accepts explicit paths and an optional `manifest_v2_path` for a second retained
manifest. These return shared `Finding` objects in `findings_v1` / `findings_v2` as well
as JSON-compatible summaries. The CLI emits only JSON-compatible fields described below.

## Input validation

The file entry points reject mixed/swapped versions, duplicate case/JSON keys, invalid
result values, unknown manifest vocabulary, inconsistent coverage, result rows that do
not match metadata completion, and invalid attack/baseline associations. A recorded
incomplete run remains valid if its actual rows and metadata agree; missing comparisons
stay inconclusive. Never edit metadata to make a truncated results file appear complete.

Analysis hashes the actual manifest bytes it parses and verifies them against both run
metadata records. If two manifest files are supplied, their bytes must match. A different
planned-suite fingerprint with otherwise valid artifacts withholds comparison claims.
Manifest hashes establish file consistency, not independent proof of registration time.

Diagnostic oracles always exclude vulnerability scoring, even with another recognized
tier. The shipped `repeated_punctuation` cases use diagnostic oracle + REVIEW; analysis
preserves both values and exposes `tier_differs_from_diagnostic` in diagnostic observations.
Unknown/missing oracle or tier values are errors, never implicit passes.

## Report schema version 2

The CLI envelope contains `schema_version: 2`, `summary_v1`, `summary_v2`, and `comparison`.
This version changes comparison category rates from scalar values into count/rate objects.
The shared dataclasses in `contract.py` are unchanged.

Each version summary contains:

- `version` and verified `coverage`.
- `findings`: objects containing `finding` (the serialized shared Finding), `subfamily`,
  `failure_mode`, `validity_tiers`, and `affected_cases`. Use these fields to qualify
  SILVER evidence and link attack IDs; affected-case count expresses reproducibility.
- `category_stats`: six categories, each with `failed`, `eligible`, `failure_rate`,
  `review`, `diagnostic`, and `unevaluable`.
- `operational`: separate 5xx, timeout, connection-failure, health-unavailability,
  slow-response, information-leak, and invalid-input-acceptance counts for scored attacks.
- `drift`: qualifying flips and eligible comparisons, rate, baseline census, exclusions,
  missing predictions/references, and confidence changes. Show the baseline denominator
  beside flip rates. No prediction-accuracy claim follows from this comparison.
- `diagnostic_observations`, `review_cases`, `validity_tier_census`, and `limitations`.
  The validity census counts finding groups carrying each tier, not attack cases; a
  mixed-tier group contributes to each applicable tier.

Category failure rates count each automatically scored attack at most once, regardless of
how many modes it triggers. Their denominator covers operational checks and is distinct
from the smaller eligible-prediction-pair denominator used for flip rates.

The comparison includes compatibility flags and coverage on both versions. If
`comparison_withheld_reason` exists, render that reason and omit before/after conclusions;
the comparison fields below will be absent. Matching planned fingerprints alone do not
mean coverage was complete. Always display coverage with a comparison.

| Comparison field | Report meaning |
| --- | --- |
| `finding_comparisons` | One structured record per V1 finding group: key, status, remaining_ids, unavailable_ids, improved_ids |
| `new_finding_evidence` | New V2 groups with regression_ids that actually had usable V1 evidence showing that mode absent |
| `inconclusive_new_findings` | V2 evidence with unavailable_ids whose prior state cannot be established |
| `category_failure_rates` | Six categories, each with v1/v2 objects containing failed, eligible, rate |
| `drift` | Per-version flip counts, eligible counts, rates, and baseline-denominator statements |
| `operational` | Separate measured operational counts for each version |

A group key is `[category, subfamily, failure_mode]`. `remaining` means the same group
has positive V2 evidence, even if different attack IDs reproduce it. `resolved` means
no V2 evidence of that group and every original supporting case had usable V2 evidence
for that mode. `unavailable` means there is no positive V2 persistence evidence and at
least one original supporting case cannot be evaluated. Display this as **inconclusive**.

`improved_ids` describe original supporting cases that no longer exhibit that particular
mode; they do not mean all other modes passed. A remaining group may also have improved
and unavailable cases. Preserve those qualifiers instead of showing only its status.

A newly appearing group requires at least one demonstrated case regression. The same key
may occur in `new_finding_evidence` and `inconclusive_new_findings` when only part of its
V2 evidence has usable V1 counterparts. The ID sets are disjoint. Do not count them as
two different weaknesses. Per-version findings retain all observed V2 evidence.

Legacy convenience lists `findings_resolved`, `findings_remaining`, `findings_unavailable`,
and `findings_newly_appearing` remain available, but use the structured records above for
the report so case-level qualifications are not lost.

Example category comparison from the saved full benchmark:

```json
{
  "encoding": {
    "v1": {"failed": 104, "eligible": 931, "rate": 0.11170784103114931},
    "v2": {"failed": 63, "eligible": 931, "rate": 0.06766917293233082}
  }
}
```

Rates are fractions; multiply by 100 only for display. A zero denominator emits the
literal string `"N/A"`, not zero. Never convert missing/inconclusive evidence into a pass.

## Scoring and interpretation

Connection failure is a distinct finding scored 70/High, with no size adjustment. This
policy was added under Ahsan's delegated remediation authority on 2026-09-09. It represents
a request-level defect, like an unhandled server error; a successful subsequent health
check does not erase it. Health failure remains separately scored as observed service
unavailability. Prediction drift stays unevaluable when no prediction came back.

Severity uses the maximum unrounded supporting-instance score through tier selection.
Use the supplied `severity_tier`; never recalculate it from a rounded display value.
Near a boundary, show additional precision or a bound such as `<60` alongside Medium
instead of displaying `60 / Medium`. Existing weights and adjustments are unchanged.

Leak detection excludes reflected `input` and user-controlled `loc` only from recognizable
HTTP 422 validation entries, while scanning server-generated diagnostics and other bodies.
It remains a signature-based detector; findings are evidence for review, not a guarantee
that every possible information leak has been detected.

The saved benchmark `results/full_20260909_135157` produces 14 resolved / 14 remaining,
with 36/42 eligible clean baselines on both versions. Its 10 MB request times out on both
versions. Do not substitute measurements from another run or infer which server stage
caused that timeout. Report rendering is the next component; analysis tests do not prove
HTML/PDF generation.
