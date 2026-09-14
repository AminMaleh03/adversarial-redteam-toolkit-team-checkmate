# Frozen CI case selections and policy references

**Owner: Khalid** (this directory follows `analysis/`). The foundation task created the
first frozen selection and its clean reference once, from real artifacts. Every later
change is Khalid's, and nothing here is auto-approved.

**Path assumption (unresolved).** The foundation task specified "their agreed
`analysis/case_sets` and policy-reference locations". `analysis/case_sets/` is named
literally; the policy-reference location was not, so the clean reference was placed at
`analysis/policy_reference/ci_core_v1_clean_reference.json`. If the final plan names a
different path, move the file and update every reference to it — the contents do not
change.

## Files

| File | What it is |
| --- | --- |
| `ci_core_v1.json` | The frozen CI case selection, `case_set_id` `ci_core_v1`, `suite_id` `core`. |
| `../policy_reference/ci_core_v1_clean_reference.json` | Approved clean-reference top labels, for regression detection only. |

## How `ci_core_v1` was frozen

Derived from the actual source suite at the foundation base
(`a17fc5b3d06f1a069ebfa0b85a95f14fe01d344e`, tag `v6.0.0`), rebuilt with the real
emotion tokenizer, and cross-checked against the preserved benchmark evidence:

- `planned_suite_sha256` of the full source suite reproduces as
  `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430`, matching the
  benchmark run's recorded fingerprint.
- `manifest_sha256` reproduces as `0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717`.

Selection rule, applied in that order:

1. **Every** clean baseline case in the original core suite — 42. All of them are kept
   because derived attacks are meaningless without their clean reference, and a partial
   baseline set would silently change the flip denominator.
2. **Every** standalone attack except the explicit exclusions — 32 of 33.
3. **Every** derived attack for the first two baseline IDs in sorted order
   (`dataset-anger-0`, `dataset-anger-1`) — 88, i.e. 44 per baseline.

Total: **162 cases**. The ordered ID lists are stored in the file; the counts are
derived from those lists, not asserted independently.

### Exclusions and why

| Excluded | Rationale |
| --- | --- |
| `malformed.oversized_10mb` | A 10 MB body makes CI wall-clock time and peak memory unpredictable on a shared runner. `malformed.oversized_100kb` and `malformed.oversized_1mb` remain in the selection and exercise the same failure mode, so nothing is lost in kind. |

Sorted order is the runner's own order: `runner.run.main` sorts baselines by
`baseline_id` before building and fingerprinting the suite, so "first two sorted
baseline IDs" is well defined and stable against `baseline.json` being rewritten in a
different file order.

## The clean reference is not ground truth

`ci_core_v1_clean_reference.json` records the top label each clean baseline received
from the **verified original `emotion_v2` run** (`artifacts/benchmark_v6/run/results_v2.jsonl`,
SHA-256 `0b37eb18b91521ea6bb0228462a1cf3fef85c2580e0d178a2502bac50a79273f`), under model
`j-hartmann/emotion-english-distilroberta-base` at revision
`0e1cd914e3d46199ed785853e12b57304e04178b`.

A mismatch means **behaviour changed relative to the published benchmark**. It does not
mean the new label is wrong, and it is not a certification that the recorded label is
correct. Do not describe it as ground truth anywhere in the report or the UI. The model
revision caveat in `artifacts/benchmark_v6/PROVENANCE.md` applies to this reference too.

## Hashes that cannot exist yet

`ci_core_v1.json` deliberately contains **no** manifest or coverage hash for artifacts
that only a future feature implementation can produce. Those do not exist at foundation
time and must not be guessed.

Procedure for resolving them — Khalid, before the first gate demonstration:

1. Execute the real `ci.emotion` evaluation end to end and keep its output directory.
2. Read the produced manifest and coverage-declaration bytes and hash them.
3. Write those hashes into the policy under an explicit `resolved_from` block naming the
   run ID, the artifact paths and the commit the run was produced at.
4. Flip the policy's `status` from `draft` to `frozen` in the same change.

Until step 4, the policy **must raise an error** when it is evaluated. A draft or
unfinalised policy never passes, never warns-and-continues, and never substitutes a
placeholder hash. A gate that cannot say what it is scoring against has not passed; it
has failed to run.
