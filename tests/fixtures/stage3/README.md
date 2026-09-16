# Stage 3 fixture pack

Offline contract examples so all four tasks can write tests on day one, before any
dependency lands. **Owner: Ahsan** (common fixtures). Per-owner examples are separated
below so nobody has to edit shared files to get started.

Regenerate and re-validate with:

```
python tests/fixtures/stage3/build_fixtures.py
```

The builder is deterministic — a second run produces byte-identical files, so any diff is
a real change. It validates its own output and exits non-zero on a problem.

## What these are, and what they are not

Everything here except `legacy/genuine_v2_analysis.json` is **synthetic** and carries a
`_synthetic` block saying so. The numbers are authored to be structurally and
arithmetically coherent. They are **not** measurements, not findings about any model, and
not evidence that any feature works. A page rendered from these fixtures is a shape check,
not a product demonstration.

Every hash in the pack is a real SHA-256 of the bytes it describes — files are written
first and hashed second. There are no placeholder digests, no ellipses and no
non-existent case ids. `MANIFEST.json` lists a real digest for every file.

`legacy/genuine_v2_analysis.json` **is genuine**: it is produced by running the real
`analysis.run_analysis` over a real subset of the preserved V6 benchmark bytes
(`artifacts/benchmark_v6/run/`), namely the `dataset-anger-0` and `dataset-anger-1`
baselines and all 88 attacks derived from them. Its `_provenance` block records the source
hashes and carries forward the benchmark's model-revision caveat.

## Layout

| Path | Contents |
| --- | --- |
| `runs/run.json` | The enclosing run index. Names every evaluation and its target directories. |
| `runs/registry_snapshot.json` | Real hash of `endpoint/targets.json` at foundation time. |
| `runs/emotion_core/` | Paired `emotion_v1` + `emotion_v2`, suite `core`, with manifest, coverage and a frozen case selection. |
| `runs/sentiment_core/` | Single `sentiment_v1`, suite `core`, **uppercase** `NEGATIVE`/`POSITIVE` labels. |
| `runs/emotion_oces/` | Both halves of the paired additional evaluation, families `oces.paraphrase` and `oces.distractor`. |
| `runs/sentiment_oces/` | Single-target additional evaluation, same two families. |
| `expected_analysis_v3.json` | The complete expected v3 document for all four evaluations. |
| `gate/` | Five gate outcomes: pass, policy failure, execution error, all-rejecting candidate, wrong clean output. |
| `api/` | Status and API examples, including a **stale** poll that must be discarded. |
| `negative/` | Inputs a correct implementation must **reject**. `_reasons.json` says why for each. |
| `legacy/` | The genuine v2 analysis, plus clearly-labelled synthetic legacy rows and layout. |

## Which fixtures each owner needs

| Owner | Start with |
| --- | --- |
| **Ahsan** (report, web, run_all) | `expected_analysis_v3.json`, `runs/run.json`, `api/*`, `legacy/genuine_v2_analysis.json` (v2 must still render), `negative/zero_denominator.json` |
| **Rayyan** (endpoint, runner, gate) | `runs/*/*/results.jsonl` and `run_meta.json` for the row/identity contract, `runs/emotion_core/case_selection.json`, all of `gate/` |
| **Khalid** (analysis, policy) | `runs/**` as input and `expected_analysis_v3.json` as the target, `legacy/*`, all of `negative/`, all of `gate/` |
| **Lamei** (attacks, baseline) | `runs/*/manifest.json`, `runs/emotion_core/coverage.json`, `runs/*_oces/` for the two-family shape |

Nobody needs to edit a shared fixture to add their own. Put owner-specific fixtures in
your own directory; changes to this pack go through Ahsan, because four test suites read
it.

## Contract points these fixtures pin down

- Single-target evaluations carry `comparison: null` — never omitted, never `{}`, and
  never a fabricated improvement figure.
- Every rate travels with its `numerator` and `denominator`. A zero denominator gives
  `rate: null`, which renders as N/A. It never becomes `0.0`.
- Paired deltas are computed over the **intersection** of eligible case ids, with that
  common denominator shown. Each target's own denominator stays in its own summary.
- `findings[].finding` keeps the frozen `contract.Finding` shape. `remediation_detail` is
  a **sibling** of it, not a replacement and not a field inside it.
- Every new row carries `target_id`, `suite_id`, `request_body_bytes` and
  `request_body_sha256`. Legacy rows carry blanks and nulls, and are routed explicitly.
- Every gate fixture is constructed through the real `contract.GateOutcome`, so the
  outcome/exit-code mapping and the "zero checks is not a pass" rule are enforced, not
  just described.
- Every planned OCES case has one of five per-target statuses. An absent prediction is
  `unevaluable`, never a successful invariance.
