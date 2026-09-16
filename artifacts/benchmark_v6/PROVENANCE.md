# benchmark_v6 — preserved original evidence

This directory is the raw run behind the published V6 benchmark report, copied
**byte-for-byte**. Nothing here is regenerated, reformatted, enriched or extended.
No field was added to the original manifest or run metadata. Any later
classification (coverage classes, new schema fields) must be written as a separate
overlay file that references these hashes — never by editing these bytes.

`.gitattributes` marks this tree `-text` so the CRLF line endings the runner wrote
survive checkout on every platform. The hashes below are of the bytes as stored.

## Source

| Item | Value |
| --- | --- |
| Source run directory | `results/repro_1` (gitignored, local to Ahsan's checkout) |
| Published report it produced | `artifacts/verified_full_report/` |
| Identity proof | `results/repro_1/report/analysis.json` is byte-identical to `artifacts/verified_full_report/analysis.json` (`12d47b35…37da`), which is also the `source_sha256` recorded in `artifacts/verified_full_report/export_meta.json` |
| Run started / ended (V1) | 2026-09-09T18:51:42+00:00 to 2026-09-09T18:52:44+00:00 (UTC) |
| Run IDs | V1 `f5dc2d3d8135`; V2 recorded in `run/run_meta_v2.json` |
| Source revision | **Not recorded in the run artifacts.** The run predates commit `4083e5c`; the pipeline source it used is byte-identical to `main` at `c507033` for `contract.py`, `endpoint/v1.py`, `endpoint/v2.py`, `baseline/`, `attacks/`, `runner/` and `analysis/`. The only pipeline file that changed between `c507033` and the foundation base `a17fc5b` is `endpoint/model.py` (see Known limitations). |

## Preserved files

| Path | SHA-256 | Bytes | Copied from |
| --- | --- | --- | --- |
| `run/manifest.json` | `0471bccbf293095d15287904a7ddfdef15161e3fb2efdcb773ccd1b952cca717` | 1887715 | `results/repro_1/v1/manifest.json` |
| `run/results_v1.jsonl` | `f617ac34a1a0148ee4507491effcf89183fbc3c5c385416f0a554ef1a4ebcb82` | 1658639 | `results/repro_1/v1/results_v1.jsonl` |
| `run/results_v2.jsonl` | `0b37eb18b91521ea6bb0228462a1cf3fef85c2580e0d178a2502bac50a79273f` | 1665935 | `results/repro_1/v2/results_v2.jsonl` |
| `run/run_meta_v1.json` | `e32d8a68409ea6df301b296cfdfaa0fcc57ea1d104e6cb10f94140308ea67c04` | 377668 | `results/repro_1/v1/run_meta_v1.json` |
| `run/run_meta_v2.json` | `646170e1143d9a8d6130baa9899432130c626fcaeb394428824c629bdc8ca276` | 377667 | `results/repro_1/v2/run_meta_v2.json` |
| `run/demo_evidence.json` | `ecdf11d687076082b4b40ea64e2eb1e1a178860ba4b59393e78e409dfeb85792` | 3333 | `results/repro_1/demo_evidence.json` |
| `analysis/analysis.json` | `12d47b35c700c6c172ceff5fc071f78952aef7a8695473dc457e9d69229737da` | 309305 | `results/repro_1/report/analysis.json` |
| `analysis/export_meta.json` | `e1212b048a380f59f56c2cd926fd79cf7464afe7ca937651952d04b0afa042e5` | 424 | `results/repro_1/report/export_meta.json` |
| `source/baseline.json` | `78ea8914dd7aeade060a10d9a14671c3ed455cbe9a3ae087b63ab448db7c0ace` | 9018 | `baseline/baseline.json` (unchanged since commit `2afc3ec`, 2026-09-08) |

`results/repro_1/v1/manifest.json` and `results/repro_1/v2/manifest.json` are
byte-identical (both `0471bccb…`), so the manifest is stored once. The equality was
asserted at copy time, and `analysis.run_analysis` independently refuses to score a run
whose two manifest files differ.

`analysis/export_meta.json` records the hashes of the report HTML/PDF rendered *in that
run directory*. Those differ from `artifacts/verified_full_report/export_meta.json`
because the published HTML/PDF were rendered in a separate pass; the `source_sha256` and
the `analysis.json` hash — the numbers the report is derived from — are identical in both.

## Verification performed (2026-09-15, Claude Opus 5, Windows, Python 3.11.9)

1. **Payload fingerprint reproduces from source.** Rebuilding the suite from the
   foundation base (`sorted(load_baseline(), key=baseline_id)` then
   `library.build_suite` with the real emotion tokenizer, `max_tokens=512`) reproduces
   the run's recorded `planned_suite_sha256` =
   `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430`, and the full
   ordered `case_ids.planned` list of 1928 entries matches exactly.
2. **Manifest reproduces from source.** `attacks.library.write_manifest` produces bytes
   hashing to `0471bccb…cca717`, equal to both the recorded `manifest_sha256` and the
   hash of the preserved `run/manifest.json` file.
3. **Numerical reproduction.** Re-running `analysis.run_analysis` over the *preserved*
   bytes in this directory reproduces `schema_version`, `summary_v1`, `summary_v2` and
   `comparison` identically to the published `analysis.json`. The published file's only
   additional top-level key is `demo_evidence`, which `run_all.py` injects from
   `run/demo_evidence.json` (preserved here, hash above).

## Verified figures (from the published analysis; do not restate from memory)

| Figure | V1 | V2 |
| --- | --- | --- |
| Planned / completed cases | 1928 / 1928 | 1928 / 1928 |
| Coverage rate | 1.0 | 1.0 |
| Unhandled 5xx | 91 | 0 |
| Timeouts / connection failures / service unavailable | 0 / 0 / 0 | 0 / 0 / 0 |
| Slow responses | 1 | 1 |
| Info leaks | 0 | 0 |
| Invalid input accepted | 1 | 0 |
| Eligible flip comparisons | 1370 | 1373 |
| Qualifying prediction flips | 218 | 112 |
| Flip rate | 0.1591240875912409 | 0.08157319737800436 |
| Baseline denominator | 36 of 42 eligible (threshold 0.60) | 36 of 42 eligible |
| Finding groups | 29 | 14 |
| Validity-tier census | GOLD 8, SILVER 21 | GOLD 1, SILVER 13 |

Comparison block: `planned_match` true, `manifest_match` true,
`whole_suite_comparable` true; 15 findings resolved, 14 remaining, 0 unavailable,
0 newly appearing, 0 inconclusive.

Suite composition: 42 baselines + 1886 attacks (33 standalone, 1853 derived) = 1928
cases per endpoint; `boundary_source` "tokenizer", `max_tokens` 512.

## Legacy target mapping

The run predates the target registry. Its `version` field values map as:

| Recorded `version` | Registry `target_id` |
| --- | --- |
| `v1` | `emotion_v1` |
| `v2` | `emotion_v2` |

This mapping is explicit and applies **only** to rows in this directory. New runs must
record `target_id` directly. Nothing may silently default an unknown identity to an
emotion target.

## Known limitations — state these, do not paper over them

- **The model revision is not recorded in the run artifacts.** At the time of this run,
  `endpoint/model.py` called `from_pretrained(MODEL_NAME)` with no `revision=`, so it
  resolved whatever `main` pointed to. The pin
  `0e1cd914e3d46199ed785853e12b57304e04178b` was added to `endpoint/model.py` *after*
  this run, recording the commit the local Hugging Face cache had resolved `refs/main`
  to. That cache state was re-verified on 2026-09-15
  (`huggingface_hub.scan_cache_dir`: `refs/main` -> `0e1cd914…`). The identity is
  therefore **strongly supported but not independently attested by the run itself**.
  Treat it as the best available evidence, not as a recorded pin.
- `RunResult` rows in this run carry no `target_id`, `suite_id`, `request_body_bytes` or
  `request_body_sha256`. There is no sender-recorded request-byte evidence for this run,
  and none can be reconstructed after the fact. Findings that require request-byte
  evidence are **unavailable** for this run, not absent.
- No coverage classification exists in these artifacts. Any classification is a later
  derivation and belongs in an overlay.
- `run_meta` records no model, tokenizer or dataset identity of any kind.
- The two `results_*.jsonl` files and `manifest.json` were written with CRLF line
  endings. That is the original byte form and is preserved deliberately.

## Defense freeze point (for OCES authoring)

The hardened endpoint evaluated in this run is unchanged at the foundation base:

| File | Git blob | SHA-256 of working-tree bytes | Last content change |
| --- | --- | --- | --- |
| `endpoint/v2.py` | `b71787e3bf39e4062f883c9e34fae78d5b7c6263` | `cf364b70c80c25081a5cb5a0ff83c844fe9199d7cbc65a517b59177ccf434a9e` | `e23d365`, 2026-09-08 |

`endpoint/v2.py` is byte-identical at `c507033`, `bba3a7b` and the foundation base
`a17fc5b`. OCES cases must be authored against this frozen defense and must not be
written before it, so the attack author cannot tune cases to a defense they just read
changing underneath them.
