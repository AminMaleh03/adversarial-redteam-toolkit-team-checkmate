# Endpoint

Owner: Rayyan. Three servable targets, one registry, two models, and one rule that
matters more than the rest: **nothing on any of these paths truncates input.**

Run from the repository root with the Python 3.11 `.venv`. Ports come from
`targets.json`; bind to loopback.

```bash
.venv/bin/python -m uvicorn endpoint.v1:app           --host 127.0.0.1 --port 8000
.venv/bin/python -m uvicorn endpoint.v2:app           --host 127.0.0.1 --port 8001
.venv/bin/python -m uvicorn endpoint.sentiment_v1:app --host 127.0.0.1 --port 8002
```

Never add `--reload` when running attacks. Reload silently restarts the app on a
change or a crash, which hides exactly the failures the toolkit is built to find.

## What is here

| File | What it is |
| --- | --- |
| `targets.json` | The static registry: models, tasks, targets, evaluations. Data only. |
| `targets.py` | Parses and validates that file into the model-free types in `contract.py`. Imports no model. |
| `model.py` | The **emotion** model, loaded at import time. Emotion-specific by design. |
| `v1.py` / `v2.py` | The original emotion endpoints, unchanged. V2 has exactly four defenses. |
| `loader.py` | Registry-driven loading for *any* target, plus tokenizer-only loading for callers that need token counts and not a model. |
| `sentiment_v1.py` | The V1-equivalent sentiment endpoint. No hardening, and deliberately no sentiment V2. |

## The registry is the only source of targets

```python
from endpoint.targets import load_registry, missing_requirements, require_runnable

registry = load_registry()
registry.target("sentiment_v1").app_path        # "endpoint.sentiment_v1:app"
registry.model_for("sentiment_v1").labels       # ("NEGATIVE", "POSITIVE")
registry.baseline_file_for("emotion.oces")      # the evaluation's own seed file
```

Loading it imports no endpoint module, no `transformers` and no `torch`;
`TargetSpec.module` is a recorded string that is never imported here. Everything
knowable from the file is checked at load — cross-references resolve, revisions are
exact 40-hex pins, ports are unique and in range, module paths are dotted, configured
paths are repo-relative. Whether a module or a baseline file *exists* is checked by
`require_runnable`, immediately before an evaluation runs, so a component another
member has not landed yet cannot break the working emotion path for everyone.

There is no free-form target input anywhere on this side. A caller names a configured
`target_id` or it gets a `ContractError`; an unknown id never falls back to emotion.

## Loading a target

```python
from endpoint.loader import load_target_model, load_target_tokenizer

loaded = load_target_model("sentiment_v1")      # weights: once per process, at import
context = load_target_tokenizer("sentiment_v1") # tokenizer + config only, no weights
```

`load_target_tokenizer` exists because the runner needs token counts and length
boundaries for the target under test, and must not pay for a model to get them —
still less for the *wrong* model. `endpoint/model.py` loads the emotion classifier as
an import side effect, so reaching it during a sentiment run would both load a model
nobody asked for and count sentiment text with an emotion tokenizer, putting every
boundary case on the wrong token. Neither `loader.py` nor `sentiment_v1.py` imports
`endpoint.model`, `endpoint.v1` or `endpoint.v2`, and a test enforces it.

### Declared identity vs. what actually loaded

Both loaders refuse to serve a target whose real identity contradicts the registry:

- **Label space.** `config.id2label` must equal `ModelSpec.labels` in order and in
  exact case. Sentiment is `NEGATIVE`, `POSITIVE` — uppercase. Lowercasing them,
  title-casing them or mapping them onto the emotion label set is a defect, not a
  formatting choice, and a reordered mapping with the same two labels is a silently
  inverted classifier.
- **Usable input limit.** Read from the live tokenizer's `model_max_length`, never
  copied from a model card. `transformers` reports `int(1e30)` when a tokenizer
  config sets no limit; that sentinel is rejected rather than believed.
- **Inference capacity.** Cross-checked against the pinned `config.json`, because a
  model card's *training* sequence length is prose and the position-embedding table
  is the architectural ceiling. RoBERTa-family models reserve the first two position
  ids, so the emotion model's `max_position_embeddings=514` is a real limit of 512;
  DistilBERT reserves none, so 512 means 512. When a config declares no position
  table the capacity is recorded as unknown, never guessed.

A mismatch raises `ModelIdentityError`. That is the point: a run that continued would
record results under an identity that did not produce them.

## Truncation

Disabled explicitly at every point text reaches a tokenizer or a model:
`truncation=False` on the pipeline construction, on each pipeline call, and on every
direct `tokenizer.encode`. This is not belt-and-braces for its own sake — Hugging
Face's pipeline defaults have changed across versions, and silent truncation
neutralises two whole attack families at once. An oversized payload would come back
as a normal, confident prediction, and the report would record a defence that does
not exist.

Verified behaviour on the sentiment target: an input over the 512-token limit reaches
the model and fails there, surfacing as HTTP 500. That is the V1-equivalent
behaviour, and it is correct. V1-equivalent means unguarded, not lenient.

## The sentiment target

`sentiment_v1` is a wrapper, not a new design. Same two routes, same response
contract (`label`, `confidence`, `all_scores`), same absence of hardening as
`endpoint/v1.py`: no length limit, no character cleanup, no custom error handling
beyond FastAPI's own.

**There is deliberately no sentiment V2**, and the emotion V2 defences are not
retro-fitted here. Tuning a defence in response to new evaluation results would make
the evaluation a fitting procedure rather than a measurement.

## Measured startup and resource cost

On an Apple M-series CPU, Python 3.11, `transformers` 4.46.0, `torch` 2.5.1:

| | sentiment_v1 |
| --- | --- |
| First start (weights downloaded at the pinned revision) | ~57 s |
| Warm start (weights already in the Hugging Face cache) | see `docs/stage3/handoffs/rayyan.md` |
| Peak RSS after load and a prediction | ~310 MB |
| Cached repo size on disk | 256 MB |

The pinned revision is `714eb0fa89d2f80546fda750413ed43d93601a13`. Cache the model in
the image rather than downloading it at container start; `docs/stage3/handoffs/rayyan.md`
carries the exact file list and hashes for the Dockerfile, which is Ahsan's to edit.

## Tests

```bash
.venv/bin/python -m pytest tests/test_endpoint.py -q
```

Importing `v1`/`v2`/`sentiment_v1` loads real weights, so this suite is slow the first
time and a few seconds after. The loader's identity checks are tested offline against
hand-built stand-ins; the tests that need real weights say so and **skip with a stated
reason** when the pinned model is unavailable. A skipped sentiment test is a gap in
the evidence, never a pass.
