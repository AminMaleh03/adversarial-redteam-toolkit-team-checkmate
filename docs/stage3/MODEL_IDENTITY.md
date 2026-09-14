# Resolved model, tokenizer and dataset identity

Resolved 2026-09-15 against the authoritative sources (Hugging Face Hub API and the
local `huggingface_hub` cache), by Claude Opus 5, on the foundation base
`a17fc5b3d06f1a069ebfa0b85a95f14fe01d344e`. Every value below is a real value read from
source. There is no placeholder, no `main`, and no invented SHA anywhere in this file.

## Emotion model (existing; verified, not changed)

| Field | Value | How verified |
| --- | --- | --- |
| Canonical repo ID | `j-hartmann/emotion-english-distilroberta-base` | `endpoint/model.py` |
| Revision (40 hex) | `0e1cd914e3d46199ed785853e12b57304e04178b` | `huggingface_hub.scan_cache_dir()` on this machine reports this repo with `refs/main` -> this commit; the value matches the pin in [`endpoint/model.py`](../../endpoint/model.py) |
| Architecture | `RobertaForSequenceClassification` | cached `config.json` |
| Label mapping | 0 anger, 1 disgust, 2 fear, 3 joy, 4 neutral, 5 sadness, 6 surprise | cached `config.json` `id2label` |
| `max_position_embeddings` | 514 | cached `config.json` |
| Tokenizer `model_max_length` | 512 | cached `tokenizer_config.json` |
| Usable limit the code uses | `MAX_SEQUENCE_LENGTH = tokenizer.model_max_length` = 512 | `endpoint/model.py` reads it from the tokenizer rather than hardcoding |

Cached revision files: `config.json`, `merges.txt`, `pytorch_model.bin`,
`special_tokens_map.json`, `tokenizer.json`, `tokenizer_config.json`, `vocab.json`.
A second cached revision `7e9d7fe536a4d2bb472f9e883cc6cbbe81f68961` exists under
`refs/pr/3017` and holds only `model.safetensors`; it is **not** the pinned revision
and must not be used.

**Caveat carried forward:** the pin is correct for current and future runs, but the V6
benchmark run itself predates it and recorded no model identity. See
`artifacts/benchmark_v6/PROVENANCE.md`.

## Sentiment model (new; pinned here for the first time)

| Field | Value | How verified |
| --- | --- | --- |
| Canonical repo ID | `distilbert/distilbert-base-uncased-finetuned-sst-2-english` | `HfApi().model_info(...).id` |
| Revision (40 hex) | `714eb0fa89d2f80546fda750413ed43d93601a13` | `HfApi().model_info(...).sha` |
| Architecture | `DistilBertForSequenceClassification` | `config.json` at that revision |
| `finetuning_task` | `sst-2` | `config.json` |
| Label mapping | 0 `NEGATIVE`, 1 `POSITIVE` | `config.json` `id2label` / `label2id` |
| `max_position_embeddings` | 512 | `config.json` |
| Tokenizer `model_max_length` | 512 | `tokenizer_config.json` |
| Tokenizer casing | `do_lower_case: true` (uncased) | `tokenizer_config.json` |
| Tokenizer identity | shares the model repo and revision; vocabulary is `vocab.txt` at the same revision | files fetched at the pinned revision |

File hashes at the pinned revision (metadata only; **no weights were downloaded**):

| File | SHA-256 |
| --- | --- |
| `config.json` | `582122c8f414793d131e10022ce9ba04e3811a9da6389137ee2f18665b4f4d15` |
| `tokenizer_config.json` | `5ab9097b4149371c5fd52b2d6e26cb6f9c07c0d19fcfdda895b1adad6b57c3e0` |
| `vocab.txt` | `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3` |

**The label space is uppercase.** `NEGATIVE` / `POSITIVE`, not `negative` / `positive`
and not the emotion label set. Anything that lowercases, title-cases or maps these onto
emotion labels is a defect, and a target whose identity cannot be resolved must fail
loudly rather than fall back to an emotion target.

## Sentiment evaluation data (for Task 4)

| Field | Value |
| --- | --- |
| Dataset repo ID | `stanfordnlp/sst2` |
| Dataset revision (40 hex) | `8d51e7e4887a4caaa95b3fbebbf53c0490b58bbb` |
| Config | default (the repo exposes a single config; files are `data/{train,validation,test}-00000-of-00001.parquet`) |
| Split to use | `validation` |
| Split file | `data/validation-00000-of-00001.parquet` |
| Split file SHA-256 | `fb00fe008f6828f86ba2beda8415a4cf5da0c884f21c5f238c87131b5aa19529` (72813 bytes) |
| Rows | 872 |
| Source schema | `idx` int32, `sentence` string, `label` int64 |
| Label distribution | 428 label 0 (negative), 444 label 1 (positive) |
| Label meaning | matches the model's mapping: 0 -> `NEGATIVE`, 1 -> `POSITIVE` |

Sentences carry the SST tokenisation artefacts, e.g.
`"it 's a charming and often affecting journey . "` — spaced punctuation and a trailing
space. Task 4 must decide explicitly whether to keep them verbatim (recommended: the
baseline is the input as distributed) and record the decision; it must not silently
clean them, because whitespace handling is itself one of the attack families.

### Two rules for selecting sentiment baselines

1. **Do not select examples using model outputs.** Picking the sentences the model gets
   right, or the ones it is confident on, manufactures the baseline confidence the flip
   oracle then depends on. Select by dataset-recorded label and by mechanical criteria
   (length, label balance) only.
2. **Do not claim the validation split is unseen by the model developers.** SST-2
   validation is a standard public benchmark split that this checkpoint's authors could
   have used for model selection. It is a reproducible, pinned, public evaluation set —
   nothing more. Any wording suggesting a held-out or contamination-free guarantee is
   false and must not appear in the report or the UI.

## What is verified now vs. still a runtime acceptance requirement

**Verified now (offline-safe, no weights loaded):**

- Both repo IDs resolve, and both revisions are real 40-hex commits.
- Both label mappings, both tokenizer limits, and the sentiment tokenizer's casing.
- The dataset revision, split file, its byte hash, row count and column schema.
- The emotion pin matches the local cache's `refs/main`.

**Still a runtime acceptance requirement (Task 2's real validation):**

- That the sentiment weights load at the pinned revision and the served endpoint returns
  the pinned label space verbatim.
- That the sentiment target's usable length limit behaves as 512 in practice, and that
  **no truncation is introduced anywhere** on the new path — pipeline, direct tokenizer
  call, or request handler. The project's standing rule applies unchanged to the new
  model: silent truncation neutralises two attack categories, and it is easy to
  reintroduce by accident while fixing an unrelated error.
- That a target whose declared identity does not match what the loaded model reports
  fails the run rather than continuing.

Registry loading, registry validation and offline fixture tests must **not** load model
weights. Only metadata and tokenizer assets may be fetched for readiness.
