# Runner

Owner: Rayyan. Two entry points: `runner.run` fires a suite at one target and records
what came back; `runner.gate` runs the CI evaluation and turns the policy's verdict
into a process exit code.

Run from the repository root with the Python 3.11 `.venv`. Start the chosen endpoint
separately, bound to the loopback port its registry entry declares.

```bash
.venv/bin/python -m runner.run --target http://127.0.0.1:8000 --version v1
.venv/bin/python -m runner.run --target http://127.0.0.1:8001 --target-id emotion_v2
.venv/bin/python -m runner.run --target http://127.0.0.1:8002 --target-id sentiment_v1 \
    --evaluation-id sentiment.core
```

The runner records observations and operational bookkeeping. It never decides whether
what happened was a defect: no flip detection, no crash rate, no severity. Analysis
owns all of that, and reads only what is written here.

## Identifying what is under test

`version` does not identify a model. `sentiment_v1` and `emotion_v1` are both version
`v1`, so a row recording only `v1` cannot say which one produced it. Every run
resolves a real `target_id` from `endpoint/targets.json` and records it on every row.

| Flag | Status | Notes |
| --- | --- | --- |
| `--target URL` | existing | required |
| `--version v1\|v2` | existing | still works; resolves to the **emotion** target of that version, explicitly and through the registry |
| `--target-id ID` | new | derives `version`. Supplying both in conflict is an error |
| `--suite core\|oces` | new | default `core` |
| `--case-set PATH` | new | a frozen selection file, executed exactly |
| `--evaluation-id ID` | new | the registry evaluation this run is one target of; resolves the baseline file |
| `--parent-run-id HEX` | new | `run_id` of the enclosing multi-target run, recorded as `evaluation_run_id` |
| `--out`, `--limit`, `--skip`, `--predict-path`, `--health-path`, `--timeout`, `--health-timeout` | existing | unchanged |

Conflicts are errors, not precedence rules. `--target-id emotion_v2 --version v1`,
a target outside its evaluation, an evaluation whose suite disagrees with `--suite`,
and an unknown id all exit **2** before anything is built or sent. There is no code
path where an unrecognised identity quietly becomes emotion.

`--suite oces` requires `--evaluation-id`: the OCES seed file is an evaluation-level
override of the task default, and running the core baseline under an OCES label would
record the hash of a file the run did not use.

### Output file names

| Invoked with | Writes |
| --- | --- |
| `--version` only (legacy) | `results_<version>.jsonl`, `run_meta_<version>.json` |
| `--target-id` | `results.jsonl`, `run_meta.json` |

The target-scoped names are the Stage 3 layout
(`tests/fixtures/stage3/runs/<evaluation>/<target_id>/`), so two targets of one
evaluation write into their own directories without a version suffix colliding.
Both share `manifest.json` and, when a selection is used, `case_selection.json`.

## Frozen selections

```bash
.venv/bin/python -m runner.run --target http://127.0.0.1:8001 \
    --target-id emotion_v2 --evaluation-id ci.emotion \
    --case-set analysis/case_sets/ci_core_v1.json --out results/ci/emotion_v2
```

The file's ids and order are the contract. Nothing is reordered, deduped or completed
to make a selection usable — anything that would need repairing is an error, because
a selection quietly repaired here no longer matches the one the policy was frozen
against. Rejected: unknown ids, duplicates, an empty selection, an `order` that is not
exactly the selected ids, a `suite_id` that is not `core` or `oces`, and any derived
attack whose baseline is not also selected.

`--limit` and `--skip` cannot be combined with `--case-set`. Dropping a case from a
frozen selection would leave a run still claiming the frozen `case_set_id` while
having executed something else.

Both the common format (CONTRACTS.md §5.2) and the shape frozen into
`analysis/case_sets/ci_core_v1.json` are accepted: when `attack_ids` is absent,
`standalone_attack_ids` followed by `derived_attack_ids` is read in that order, which
is the runner's own send order, and `order` is optional for the same reason.

### The five planned partitions

`planned` is always the **full built suite** and is never reduced by any flag, so a
bounded CI selection still refers to the whole `core` suite's identity and shares its
`planned_suite_sha256`. Every planned case then falls into exactly one bucket:

```
planned = selected + skipped + limit_excluded + deselected
```

`deselected` is new and is cases a frozen selection simply did not choose — not a
skip, not a limit, nothing went wrong. Without it the arithmetic would not close and a
reader would have to infer which bucket absorbed the difference. `completed` and
`missing` then describe execution within `selected`. Coverage rate stays
completed/planned.

## Request-byte evidence

Every row records `request_body_bytes` and `request_body_sha256`: the length and
SHA-256 of the exact serialised body that went on the wire, taken from the prepared
`httpx.Request` — and that same request object is the one sent, with nothing
re-serialising it in between.

It is never a character count, a response length or a manifest text length. A JSON
body is not its text: `{"text": "déçu"}` escapes non-ASCII on the wire, so the byte
count and the character count differ, and the old reports guessed. Raw attacks are
measured as the bytes they are, including deliberately invalid UTF-8, which is not
decoded or repaired first.

The evidence survives transport failure — a request that got no response still has a
known attempted body, and that is exactly when "how big was it really?" gets asked.
If serialisation fails before any bytes exist, both fields are `null` **and** the
reason is recorded on `error` with the `serialization_error:` prefix, counted
separately from transport failures because nothing reached the endpoint. `null` means
unavailable; it never means zero. Any serialization failure makes the collector exit 2
with `termination_reason="errored"`, while preserving the recorded rows.

## Tokenizers and boundaries

Length boundaries are built with the pinned tokenizer **of the target under test**,
loaded through `endpoint.loader.load_target_tokenizer` — which loads the tokenizer and
config and **no model weights**. This target-aware CLI path never imports `endpoint.model`, which
would load the emotion classifier as an import side effect and count sentiment text
with an emotion tokenizer, putting every boundary case on the wrong token.

The tokenizer's reported limit is validated against the registry and against the
architecture's real position-table capacity before any case is built; an implausible
limit is refused rather than stamped into the manifest as exact. `--no-tokenizer` is
a hidden testing flag that produces approximate boundaries and says so in the metadata
(`boundary_source: "approximate"`); it is not for real runs.

## Manifest isolation

The suite is built **once**, inside `attacks.metadata.scoped_registry()`, and the
manifest is written from that same build before any request is sent. The scope clears
the shared metadata registry on entry, which is the part that matters: without it, a
suite built here inherits every case already registered in the process, so the
manifest for an emotion run also stamps in sentiment cases built a moment earlier —
and the analysis then scores results against an oracle set describing different cases.

## Artifacts, staging and failure handling

Readiness — registry load, target resolution, `require_runnable`, baseline load,
tokenizer validation, suite build, manifest write, selection validation, preflight —
all happens against a staging directory beneath the output directory. Nothing already
published is replaced until the endpoint has answered its health check, so **a
readiness failure never overwrites a previous successful run.** After that, a new
invocation replaces that target's results and metadata; use separate `--out`
directories to retain multiple experiments.

Rows are flushed and fsynced as each completes, so the case that killed an endpoint is
already on disk. A post-request health failure records the current row and stops:
everything after a dead endpoint is a connection error carrying no information.
Missing cases are recorded as missing and must never be read as "the candidate fixed
it". Prediction requests are never retried; the health ping retries once on a fresh
connection, because uvicorn answers a 500 with `Connection: close` and the innocent
next ping would otherwise fail on a dead pooled socket.

Exit codes: **0** completed selected execution (including limits), **1** post-request
health failure, **2** failed preflight, invalid arguments or any configuration and
readiness or serialization failure, **130** interruption.

### What `run_meta.json` records

Everything the old file had, plus `evaluation_run_id`, `evaluation_id`, `target_id`,
`task_id`, `suite_id`, `case_set_id`, a `model` block (ids, revisions, labels), a
`baseline` block (path and SHA-256 of the file **actually used**), `registry` and
`case_set` snapshots with their hashes, a `tokenizer` block recording what was
verified, `code_provenance` (`app_commit`, `dirty`), and three new fingerprints. The
per-invocation `run_id` stays distinct from `evaluation_run_id`; a standalone
invocation records `null` for the parent rather than copying its own.

| Fingerprint | What it is |
| --- | --- |
| `planned_suite_sha256` | The full built suite. Unchanged, and never reduced by a flag. |
| `selection_sha256` | SHA-256 of the case-selection **file** this run was pointed at, so a reviewer can confirm which committed selection was used. `null` when no selection file was used — there is then no file whose bytes could be hashed. |
| `selected_order_sha256` | SHA-256 of what was **actually executed**, in order. Always present, including for runs with no selection file. |
| `results_sha256` | SHA-256 of the results file as written. |

`selected_order_sha256` hashes this canonical JSON document — sorted keys, UTF-8, no
incidental whitespace:

```json
{"case_set_id": <str|null>, "order": [<case keys, in order>], "suite_id": <str>}
```

The three are deliberately distinct: the planned fingerprint says what the suite is,
the selection hash says which committed selection the run was pointed at, and the
order hash says what was run and in what sequence — so a policy frozen against one
selection cannot be satisfied by a different one, or by the same one run in a
different order.

## The gate

```bash
.venv/bin/python -m runner.gate \
    --policy analysis/policies/ci_core_v1.json \
    --out results/ci \
    --evaluation ci.emotion
```

`runner.gate` calls `run_all.run_experiment` for the internal `ci` evaluation, reads
back the produced analysis, every target's `run_meta.json` and every target's parsed
`RunResult` rows, and hands all of it to `analysis.policy.evaluate_policy`. It writes
`gate_result.json` and returns `GateOutcome.exit_code`.

| Exit | Meaning |
| --- | --- |
| 0 | The named policy passed, on real evidence, on this selection. |
| 1 | A well-recorded candidate failure. The evidence is trustworthy; the candidate failed. |
| 2 | The gate could not reach a verdict: configuration, readiness, or missing/unusable evidence. |

There is no policy logic in `runner/gate.py` — no threshold, no recalibration, no
skipping hard cases when CI is red — and no local stand-in policy to fall back on. A
missing `analysis.policy`, an orchestrator that raised, an absent `run_meta.json`, a
results row that is not a `RunResult`, or a policy that raised are all exit 2, each
with a readable reason written into `gate_result.json` whenever the destination can be
written. Error paths fabricate nothing: `candidate` and `reference` stay empty and
`selection_sha256` stays blank, because a placeholder there is indistinguishable from
a real value in a CI log.

Exit 1 and exit 2 are kept apart deliberately. An endpoint that died mid-suite is
data: `run_experiment` preserves it and returns normally, the policy calls it a
failure, and the gate reports 1. Turning that into 2 would lose the distinction
between "the candidate is bad" and "we could not tell", which is the distinction the
two codes exist for.

`run_all` must never import `runner.gate` — the gate calls the orchestrator, not the
reverse. Both heavy imports are deferred into the function that needs them, so
`--help`, an offline test and every error path load no model and no orchestrator.

A gate pass claims compliance with the named policy on that selection. It is not
comprehensive model-level adversarial robustness and not production certification.

## Tests

```bash
.venv/bin/python -m pytest tests/test_runner.py tests/test_gate.py -q
.venv/bin/python -m pytest -q
```

`tests/test_runner.py` runs offline against `httpx.MockTransport` with an injected
clock, plus one real local socket test that cancels a dripping response at ten seconds
and checks the next request still succeeds. `tests/test_gate.py` replaces the
orchestrator and the pure policy with doubles; it proves the gate maps a `GateOutcome`
to the right exit code and refuses to reach a verdict without evidence — it proves
nothing about whether any policy is correct or any candidate passes. That evidence
comes from a real integrated run and is reported in
[`docs/stage3/handoffs/rayyan.md`](../docs/stage3/handoffs/rayyan.md).

See [HANDOFF.md](../HANDOFF.md) for the latest verified commits and integration scope.


## Windows continuation and artifact checks

Use the repository Python 3.11 environment: `.\.venv\Scripts\python.exe`.
The complete current validation record is in
[Rayyan's handover](../docs/stage3/handoffs/rayyan.md).

`build_token_counter(target_id: str | None = None)` preserves its no-argument legacy
emotion behavior; an explicit target uses the pinned tokenizer-only loader. The CLI
uses `build_token_counter_for_target(target_id, registry)` for every target.

Evaluations declaring a case set require `--case-set`; duplicate/unknown skips,
duplicate generated IDs, conflicting split/combined selections and invalid selection
versions fail before requests. Registry bytes are copied to `registry.json`; exact
selection-file bytes go to `case_selection.json`. These copies match the recorded
hashes and are published only after readiness succeeds. Coverage-map snapshot wiring
remains an integration check when Task 4's map lands.

The gate requires exactly one matching evaluation entry, consistent row/metadata
identities, unique rows, a matching results-file hash and a saved analysis.json equal
to the orchestrator's document. It supplies the measured policy-file hash to the pure
policy function. An explicit `analysis_json` return path is accepted; otherwise it
reads `report_dir/analysis.json`. Missing optional report files are reported as null.
Only the internal `ci.emotion` evaluation is accepted by this gate.

When a PowerShell script invokes the gate, end it with `exit $LASTEXITCODE` so the
native 0/1/2 code reaches the calling workflow. The missing frozen policy currently
produces exit 2; this branch does not claim an integrated policy pass.
