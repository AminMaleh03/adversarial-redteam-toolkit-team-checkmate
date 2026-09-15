# Rayyan Task 2 handover

Updated 2026-09-15T16:39:09+04:00, Codex. Assigned and active branch: **stage3/rayyan**.
Tested code head: **8c5b42c631a917642b5f4b4a5ee68227ce7fa58c**.
The delivery commit adds documentation only; its SHA is the PR head / `git rev-parse HEAD`.
Base remote merge: `d55f1e223e40d9ef4c1a61e62983c74bf16f80b2`.
Python 3.11.9 in `.venv`, Windows. Ahsan: test the exact PR head before acceptance.

## Scope and delivery

The user's attached instructions authorize commits and push only to stage3/rayyan,
PR base stage3/integration, Ahsan review, and no self-merge. The earlier
stage3/rayyan-windows name was an agent-created local branch, superseded by the
assigned branch. It is not the delivery branch and has not been pushed.

Changes authored during this continuation are entirely Rayyan-owned code/tests/docs
plus the required shared HANDOFF.md. **No Khalid analysis code was edited.**
Files changed since fetched Rayyan merge: endpoint/loader.py, endpoint/targets.py,
endpoint/README.md, runner/run.py, runner/gate.py, runner/README.md,
tests/test_endpoint.py, tests/test_runner.py, tests/test_gate.py,
tests/fixtures/rayyan/sentiment_runtime.py, this handover and HANDOFF.md.
The overall PR also includes the earlier Rayyan sentiment endpoint implementation.

**Incoming-history disclosure:** tests/test_stage3_foundation.py was already changed
on the fetched Rayyan branch. This continuation did not edit that Ahsan-owned file.
Released endpoint/v1.py, endpoint/v2.py and model pins remain unchanged.

## Implementation commits

- fc8560c: reconcile incompatible runner merge, frozen selections, exact request
  evidence including serialization failure, registry/selection snapshots, label
  checks and real sentiment probe.
- f60697c: gate validates persisted rows/hashes/identities and saved analysis,
  supplies actual policy hashes and artifact paths, retains honest error context.
- 69db5b6: previous Windows verification documentation.
- 9d75993: reusable paired plans, exact coverage-map snapshot/hash, wrong tokenizer
  context rejection and corresponding tests. New optional keyword arguments preserve
  existing callers; exact public signatures are in runner/README.md.
- 8c5b42c: gate argument errors emit gate_result.json when --out is recoverable.

## Validation on this device

| Exact command | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest -q tests/test_endpoint.py tests/test_runner.py tests/test_gate.py --tb=short` | **230 passed**, no skips, 20.88 s |
| `.\.venv\Scripts\python.exe -m pytest -q --tb=short -rs` | **841 passed, 30 skipped, 1 failed**, 26.66 s |
| `.\.venv\Scripts\python.exe results/task2-full-sentiment-core/validate.py` | Real full sentiment core: **1931/1931**, zero missing; runner exit 0 |
| `.\.venv\Scripts\python.exe results/task2-full-sentiment-core/check_planning.py` | Real pinned tokenizers: paired plan uses one build; cross-task manifests remain isolated; precise OCES readiness error |
| Gate command below, followed by `exit $LASTEXITCODE` | **2** reaches PowerShell; error JSON written |
| `git diff --check` | clean |

Full log: results/task2-rayyan-completion-tests-final.txt. Skips: 27 browser and
3 native PDF cases. The failure is the existing Ahsan-owned registry test at
 tests/test_stage3_foundation.py:278: it asserts sentiment has not been imported
in the shared pytest interpreter, after legitimate endpoint tests imported it.
**Request to Ahsan:** run that registry-isolation assertion in a fresh subprocess,
checking torch/transformers/endpoint apps remain absent after loading only targets.
Do not weaken the isolation check. No whole-repository green claim is made.
An initial broad test attempt collected duplicate tests from the exported dependency
snapshot. The snapshot is now .source inside the ignored evidence directory; the
normal full-suite command above was rerun successfully through collection.

## Real full sentiment core evidence

Directory: **results/task2-full-sentiment-core/**. Source export combines Rayyan
8c5b42c631a917642b5f4b4a5ee68227ce7fa58c with Lamei attacks/baseline
f619e513bdd10f5eb5c94830ce9efc3f11c28c4a. source_revisions.json records these
exact SHAs; this is real dependency integration, **not a single integrated commit**.
No other owner's code was modified or added to this branch. Latest Lamei 089e54d
changes only his handover/tests relative to that production snapshot.

- run/run_meta.json, results.jsonl, manifest.json, registry.json, coverage_map.json
  hold actual evidence. summary.json records measurements. Local validation scripts
  and immutable source export are retained under this ignored directory.
- **1931 planned, selected and completed; 0 missing/skipped/limit-excluded.**
  The generated count is 42 baselines plus 1889 attacks; it was not forced to 1928.
- **1931 independent received-body observations match sender lengths and SHA-256.**
- 85 HTTP 5xx responses; zero timeouts, connection errors, health failures or
  serialization failures. V1 collection completed; this is not a gate/policy pass.
- Cached readiness **3.457 s**, runner **43.467 s**, service peak working set
  **1,138,769,920 bytes**. These are Windows measurements, not container estimates.
- Service and launcher PIDs handled separately; configured port 8002 closed after run.
- Planned SHA: `ff9cc7cffa91b1c1a25c491a5836e7f3cc5a0c156ff190e982394cd034c207ca`.
- Manifest SHA: `f694ab3d303fc10d0eb971bf6eee2a92f44e7f54c73ad0e919ce50f8532b8336`.
- Map SHA: `650674889799fe217390dcb97c5e50ad542c3e187fa2e708d5cc9fbd2631f02a`.
- Results SHA: `1329072eb2ae897c491a5d893d2382f34622fd93d8d58a2c2296d9a1f317dc61`.

On an integrated checkout, with the real service on its configured loopback port:

```powershell
.\.venv\Scripts\python.exe -m uvicorn endpoint.sentiment_v1:app --host 127.0.0.1 --port 8002
# In another terminal:
.\.venv\Scripts\python.exe -m runner.run --target http://127.0.0.1:8002 --target-id sentiment_v1 --suite core --evaluation-id sentiment.core --out results/sentiment-core-new
```

## Pinned identity, no truncation and Docker cache

Model/tokenizer: distilbert/distilbert-base-uncased-finetuned-sst-2-english at
**714eb0fa89d2f80546fda750413ed43d93601a13**. NEGATIVE id 0, POSITIVE id 1.
Real inference/tokenizer capacity is **512 tokens including special tokens**;
model-card training length is not the inference limit. Full score vectors and
health responses verified. Sentiment loads no emotion module/weights.
Emotion pin remains 0e1cd914e3d46199ed785853e12b57304e04178b.

Ahsan's sentiment cache files: config.json (629 B), tokenizer_config.json (48 B),
vocab.txt (231508 B), model.safetensors (267832558 B). Dockerfile was not edited.
Metadata hashes:

- config: `582122c8f414793d131e10022ce9ba04e3811a9da6389137ee2f18665b4f4d15`
- tokenizer config: `5ab9097b4149371c5fd52b2d6e26cb6f9c07c0d19fcfdda895b1adad6b57c3e0`
- vocab: `07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3`

Earlier real probe results/task2-windows-sentiment-3/: 26/26, 512 tokens HTTP 200,
513 tokens HTTP 500 with healthy service. Run it using:

```powershell
.\.venv\Scripts\python.exe tests/fixtures/rayyan/sentiment_runtime.py --out results/sentiment-probe-new
```

Exact sender/receiver body examples from that probe:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| ASCII positive | 52 | 9b1567774afc4e78894f97bfd82e9df05d2ff9107f03291998c9b56687ceb82e |
| Unicode | 55 | dc5bf8b4697a29aed7225e174d8cbe2159db328491022daef8272f5ff254d76a |
| Raw malformed UTF-8 | 15 | 0cce6ee85f97f0d683347b368e35bc762dd3c61cc418e576791a8a029be47dff |

Probe cached readiness 2.858 s, first request 105.93 ms, repeat median 12.88 ms,
p95 13.73 ms; service peak 495775744 B. Probe 1 measured the launcher memory and
is explicitly invalid for resource claims; probe 2 detected incomplete cleanup;
probe 3 is the accepted probe. All processes are stopped.

## Gate, OCES and remaining integration requirements

```powershell
.\.venv\Scripts\python.exe -m runner.gate --policy analysis/policies/ci_core_v1.json --out results/gate-new --evaluation ci.emotion --html-only
exit $LASTEXITCODE
```

Actual final error: results/task2-rayyan-final-gate/gate_result.json:
`outcome=execution_error`, `exit_code=2`, check `gate_policy_readable`, reason missing
policy file; observed/threshold null, candidate/reference empty. Fixture tests
exercise real GateOutcome pass/fail/error mapping to 0/1/2 using explicit doubles
for missing orchestration/policy interfaces. They are not integrated gate verdicts.

Earlier real emotion V2 collection: results/task2-windows-ci/emotion_v2/,
162/162 frozen selected cases complete, full core identity 1928, no operational
failures; startup 3.284 s, run 7.216 s. Its precommit metadata correctly records
d55f1e2 dirty=true. No artifacts were relabeled as clean-commit evidence.

1. **Ahsan:** integrate dependencies and call runner.plan_run once per task/suite,
   then runner.main(..., reuse_plan=plan) for both paired targets. Real tokenizer
   planning proves reuse/isolation; final run_all integration remains unverified.
2. **Ahsan/Khalid:** land frozen run_experiment/index/report support and the real
   frozen policy JSON. The analysis implementation exists on stage3/khalid, but
   the policy JSON and Ahsan's Stage 3 orchestration are still absent here.
   Run real policy pass/fail and html_only acceptance after integration.
3. **Lamei:** implement the approved public OCES suite loading path. Freeze A
   5e01825f7e399ae2019671f0f964b6b83be52a71 and provenance B f619e51 exist.
   Correct sentiment.oces readiness currently raises: build_suite generates core
   only; OCES variants are frozen data files, not generated here. All **20 seeds
   and 40 variants** have individual not_executed reasons in planning_summary.json.
   No OCES predictions were sent. An earlier invalid evaluation-ID probe remains
   in summary.json for audit; planning_summary.json is the corrected readiness check.
4. **Ahsan:** run failing/corrected candidates under the same frozen policy using
   existing isolated stage3/rayyan-regression-demo at
   d0a5fdaa38bd09e3fa6abcee1b2ef285174ccd4c. It removes length rejection only.
   The exception handler may return a generic HTTP 500; no process crash or stack
   trace is promised. Never merge the demo; released V2 retains its defense.
5. **Ahsan:** fix the owned foundation test above and test the exact PR head before
   acceptance. No PDF/Docker deployment or complete integrated gate is claimed.

---

## Historical Mac handover (superseded by the current record above)


# Historical Mac handover (different code head and machine)

The following record predates d55f1e2 and this Windows continuation. Its measured
results are historical; use the current section above for this checkout's status.

# Handover — Rayyan (Task 2)

Sentiment endpoint, target-aware runner, gate CLI.

| | |
| --- | --- |
| Branch | `stage3/rayyan` |
| **Code head to test** | **`d6143aec181bac63ae0e2bb664640310fe56d0d4`** |
| Branch tip | this document's own commit, a documentation-only child of `d6143ae`. A commit cannot contain its own SHA, so the code SHA is named instead — same trick the foundation used. `git diff d6143ae stage3/rayyan --stat` shows only `HANDOFF.md` and this file. |
| Base | `257e15f` (Stage 3 foundation, tag `stage3-foundation-v1`) |
| Demo branch (never merge) | `stage3/rayyan-regression-demo` @ `d0a5fdaa38bd09e3fa6abcee1b2ef285174ccd4c` |
| Environment | macOS (Apple silicon), Python 3.11.14, `.venv`, `torch` 2.5.1, `transformers` 4.46.0 |
| Date | 2026-09-15 |

Ahsan: please run the checks in §6 against **that exact SHA**. Everything below is
either a command you can re-run or a number measured on this machine at that commit.
Where something was *not* verified, it says so — §8 is the list of what is still open,
and §9 is four defects I found that belong to other owners.

---

## 1. Commits

| SHA | What |
| --- | --- |
| `9813c13` | (pre-existing on this branch) registry-driven loader + sentiment V1 endpoint |
| `b9d8c3b` | Real identity validation in the loader; tokenizer-only loading with no weights |
| `235b151` | Target-aware runner: identity, request-byte evidence, frozen selections, staging |
| `f19d6d4` | The gate CLI |
| `d6143ae` | Regression guard for V2's length defense (see §9.4) |

Endpoint/runner and the gate are separate commits, as the task requires: `b9d8c3b` and
`235b151` can merge ahead of Khalid's `analysis.policy` and Ahsan's orchestration.

## 2. Files changed — all inside my ownership

```
endpoint/README.md        new    component README
endpoint/loader.py        +316   tokenizer-only loading, identity + capacity validation
endpoint/sentiment_v1.py  +62    (landed in 9813c13)
runner/README.md          +308   rewritten for the new surface
runner/gate.py            new    the gate CLI
runner/run.py            +1068   target awareness, byte evidence, selections, staging
tests/test_endpoint.py    +384   9 existing kept, 26 added
tests/test_gate.py        new    32 tests
tests/test_runner.py      +701   59 existing kept, 55 added
```

Nothing outside `endpoint/**`, `runner/**`, `tests/test_endpoint.py`,
`tests/test_runner.py` and `tests/test_gate.py` was touched. `run_all.py`, `web/`,
`report/`, `analysis/`, `attacks/`, `baseline/`, the root `README.md`, `Dockerfile`
and `contract.py` are unchanged — `git diff --stat 257e15f stage3/rayyan` shows nine
files, all mine.

## 3. Model and tokenizer — real, loaded, verified

| | Value |
| --- | --- |
| Sentiment model | `distilbert/distilbert-base-uncased-finetuned-sst-2-english` |
| Revision (model **and** tokenizer) | `714eb0fa89d2f80546fda750413ed43d93601a13` |
| Labels served | `NEGATIVE`, `POSITIVE` — uppercase, id 0 → `NEGATIVE` |
| Tokenizer `model_max_length` | 512, read from the live tokenizer |
| Inference capacity from pinned config | 512 (`distilbert`, `max_position_embeddings` 512, 0 reserved positions) |
| Emotion model | unchanged, `0e1cd914e3d46199ed785853e12b57304e04178b`, capacity 512 (`roberta`, 514 positions − 2 reserved) |

The registry pin was **not** taken on trust. The loader loads the real model and
config and refuses to serve a target whose `id2label` does not equal `ModelSpec.labels`
in order and case, whose tokenizer reports the `int(1e30)` "unset" sentinel, or whose
declared limit contradicts the architecture's position table. The training sequence
length a model card mentions is prose; the position table is the ceiling, and that is
what is checked.

Three file hashes recorded in `MODEL_IDENTITY.md` were re-confirmed against the actual
download: `config.json` `582122c8…`, `tokenizer_config.json` `5ab9097b…`,
`vocab.txt` `07eced37…`. All three match.

**Registry lookup stays model-free.** `load_target_tokenizer("sentiment_v1")` in a
clean subprocess leaves `endpoint.model` absent from `sys.modules` — asserted by
`tests/test_endpoint.py::test_reading_the_pinned_tokenizer_loads_no_weights`. (`torch`
*is* imported, because `transformers` imports it; no weights are loaded, which is the
claim being made.)

## 4. Public commands

```bash
# emotion, legacy flag — unchanged behaviour, legacy file names
.venv/bin/python -m runner.run --target http://127.0.0.1:8000 --version v1

# any target, by id — target-scoped file names
.venv/bin/python -m runner.run --target http://127.0.0.1:8001 --target-id emotion_v2

# the frozen CI selection, exactly as the gate runs it
.venv/bin/python -m runner.run \
    --target http://127.0.0.1:8001 --target-id emotion_v2 \
    --evaluation-id ci.emotion --case-set analysis/case_sets/ci_core_v1.json \
    --parent-run-id <enclosing run_id> --out results/ci/emotion_v2

# the gate
.venv/bin/python -m runner.gate --policy analysis/policies/ci_core_v1.json \
    --out results/ci --evaluation ci.emotion [--html-only]

# the sentiment service, on its configured loopback port
.venv/bin/python -m uvicorn endpoint.sentiment_v1:app --host 127.0.0.1 --port 8002
```

New public functions in `runner/run.py`, all documented in the module:
`resolve_target`, `emotion_target_for_version`, `build_token_counter_for_target`,
`load_case_set`, `apply_case_set`, `fingerprint_selection`, `default_send_order`,
`code_provenance`, `plan_run`, `Runner.prepare_request`, `Runner.run_ordered`.
Existing signatures are unchanged: `build_meta` gained keyword arguments with
defaults, `build_suite_once` gained keyword-only `suite`/`task_id` with the legacy
defaults, and `Runner.__init__` gained `target_id`/`suite_id` at the end.

New in `endpoint/loader.py`: `load_target_tokenizer`, `TokenizerContext`.
New in `runner/gate.py`: `main`, `run_gate`, `load_policy`, `collect_evidence`,
`parse_results`, `execution_error`, `write_gate_result`, `GateExecutionError`.

## 5. Test output — exact, including what is skipped

```
$ TOKENIZERS_PARALLELISM=false .venv/bin/python -m pytest -q
3 failed, 790 passed, 30 skipped, 1 warning in 26.63s

$ .venv/bin/python -m pytest -q tests/test_endpoint.py     35 passed
$ .venv/bin/python -m pytest -q tests/test_runner.py      114 passed
$ .venv/bin/python -m pytest -q tests/test_gate.py         32 passed
```

**The three failures are pre-existing and are not mine.** I confirmed that by running
the untouched branch tip `9813c13` in a separate worktree: `3 failed, 98 passed`, the
same three. They are all in `tests/test_stage3_foundation.py` (Ahsan's file) and all
three are diagnosed in §9. Baseline before my changes was 674 passed; it is now 790,
so 116 tests were added and none removed.

**The 30 skips are all pre-existing browser-acceptance tests** in
`tests/test_ui_browser.py`, each skipped with `Set REDLAB_BROWSER_TESTS=1`.
**Nothing in my three test files is skipped** — including the tests that need the real
sentiment weights, which really loaded them. Those tests are written to skip with an
explicit "NOTHING below was verified" message if the model is unavailable offline; on
this machine they did not skip.

One caveat, reported rather than smoothed over: one full-suite invocation aborted with
a native fault in `torch`/`tokenizers` while two `uvicorn` servers from the real runs
below were still alive in the background. A clean re-run with those killed passed as
above, and I could not reproduce it a second time. If CI ever sees this, it is
process-level contention and not a test failure — but I am recording it rather than
leaving it out.

## 6. Checks to re-run at `d6143ae`

- [ ] `TOKENIZERS_PARALLELISM=false .venv/bin/python -m pytest -q` → expect
      790 passed, 30 skipped, and the same 3 pre-existing foundation failures.
- [ ] `.venv/bin/python -m runner.gate --help` returns instantly and imports no model.
- [ ] The real CI-selection run in §7 reproduces
      `planned_suite_sha256 = 7fcccf16…a430`.
- [ ] `.venv/bin/python -m runner.run --target ... --version v1 --limit 30` still
      writes `results_v1.jsonl` / `run_meta_v1.json`.

## 7. Real runs — what was actually executed

`results/` is gitignored, so these directories are local. Counts, hashes and paths are
recorded here so they can be re-derived.

### 7.1 The frozen CI selection against a live `emotion_v2`

`endpoint.v2` on `127.0.0.1:8001` (the port `targets.json` declares), real pinned
emotion model, real tokenizer boundaries — no `--no-tokenizer`.

```
results/real_ci/emotion_v2/
  results.jsonl    160901 B  36f481a40b69f05954fee06ca3438a48c1ff043174e8c25d7d9f79475c3c4c4f
  run_meta.json    259345 B  7a78a537225164c67b73abf78994fcfa6f699b9c938ebce762bce41f3bbb73b6
  manifest.json   1840564 B  374dbee592ad2dadb6aecf850b6be21a22a1ca7b5f70f1a34833a93fffae0c84
  case_selection.json  517 B 4df2ca06411c76d9c4b88da8ab76c9bcfbd28e63103d97516c5d8bcd9fd6e85d
```

| | |
| --- | --- |
| Cases | 162 planned-selected, **162 completed, 0 missing**, termination `completed`, exit 0 |
| Wall clock | 6 s for the 162 cases (endpoint start excluded) |
| Coverage partitions | selected 162 + skipped 0 + limit_excluded 0 + **deselected 1766** = planned 1928 |
| `planned_suite_sha256` | `7fcccf16989784ca046317158a97fca6fcb52299eae99deda62ab0c63914a430` |
| `selection_sha256` | `25573a71931259a3da4241af4ee507314544fd783f796c74c32d0fa88c56ec9d` |
| `selected_order_sha256` | `3f74cfe741a679fbcbeb7856e8b1758d3c37b37d4f46b3fcb76008efba3f739e` |
| Status codes | 200 × 135, 422 × 24, 400 × 3, **5xx × 0** |
| Transport counts | all zero, including the new `serialization_errors` |

Two things worth pointing at:

- `planned_suite_sha256` is **exactly** the fingerprint recorded for the preserved V6
  benchmark. The suite still re-derives identically through the new registry-driven
  tokenizer path, so nothing about the change moved the case set.
- `selection_sha256` is **exactly** the value the shared gate fixtures carry. I had
  originally defined that field as a hash of the ordered selection; the fixture run
  metadata (`null` for the runs with no case set, the file's own hash for the one with
  one) settled it, and I changed the implementation to match the fixtures rather than
  the other way round. The ordered-execution hash is kept alongside as
  `selected_order_sha256`.

### 7.2 Legacy compatibility

`endpoint.v1` on `127.0.0.1:8000`, `--version v1 --limit 30`:
72 rows, `results_v1.jsonl` + `run_meta_v1.json` (legacy names),
`identity_resolved_from: "--version v1 (explicit emotion_7 default)"`,
`target_id: emotion_v1`, same `planned_suite_sha256`, termination `stopped_on_limit`.

### 7.3 Sentiment

The real sentiment **endpoint** is verified (§3, §5). A real sentiment **core run** is
blocked: `baseline/sentiment_baseline.json` is Lamei's Task 4 and does not exist yet.
The runner reports that rather than working around it — `--target-id sentiment_v1`
exits 2 naming the missing file, sends nothing, and leaves the output directory empty.
That is a checked behaviour, not an untested path
(`test_a_missing_dependency_is_reported_not_worked_around`).

**No sentiment case count is claimed, and 1,928 is not forced anywhere.** The
generated count will be whatever the builders produce for that task.

## 8. Request-byte evidence, with real numbers

`request_body_bytes` / `request_body_sha256` are taken from the prepared
`httpx.Request`, and that same object is sent. From `results/real_ci`, with an
independent recompute of the expected wire body confirming both fields on every case
checked:

| Case | chars | wire bytes | status |
| --- | --- | --- | --- |
| `baseline:dataset-anger-0` | 136 | 148 | 200 |
| `dataset-anger-0.encoding.homoglyph.leading.d1` | 136 | 153 | 200 |
| `dataset-anger-0.encoding.homoglyph.leading.d3` | 136 | 163 | 200 |
| `dataset-anger-0.encoding.homoglyph.leading.d5` | 136 | 173 | 200 |
| `malformed.malformed_utf8` (raw) | — | 14 | 400 |
| `malformed.utf8_bom` (raw) | — | 25 | 200 |
| `malformed.oversized_100kb` | — | 102412 | 422 |
| `malformed.oversized_1mb` | — | 1048588 | 422 |

Four payloads of **identical character length** and four different wire sizes. That is
the whole reason this is recorded by the sender rather than derived downstream from the
text, and it is what the old reports were guessing at.

`baseline:dataset-anger-0` independently recomputed: 148 bytes, sha256 `5ee693d6b440…`
— identical to the recorded row. Unicode and raw malformed cases are covered by unit
tests against `MockTransport`-captured bytes as well.

## 9. Four defects found, none of them mine to fix

### 9.1 The OCES freeze-point hash is a Windows-only value — *Ahsan, Lamei*

`FOUNDATION_READINESS.md` §5 and
`tests/test_stage3_foundation.py::test_defense_freeze_point_still_matches_the_checked_in_file`
record `endpoint/v2.py` as SHA-256 `cf364b70…`. That is the **CRLF** rendering. The
committed blob (`b71787e3…`, LF, which is what git actually stores) hashes to
`b71193bef639410c828ec78e9aacc172e5da6a1c3b9fd8e5f7041ee6afc78baf`, and
`sha256(blob.replace(b"\n", b"\r\n")) == cf364b70…` exactly. So the assertion fails on
every macOS and Linux checkout, and Lamei is being told to author OCES against a hash
that depends on who checked the file out. `.gitattributes` scopes `-text`/`binary` to
`artifacts/**` and the fixture pack; `endpoint/v2.py` is not covered.

Suggested fix, Ahsan's call: use the git blob id `b71787e3…` (already recorded, and
platform-independent), or the LF SHA-256 above.

### 9.2 The frozen CI manifest hash has the same problem, and it will hit CI — *Khalid*

`analysis/case_sets/ci_core_v1.json` records
`frozen_from.manifest_sha256 = 0471bccb…`. My real run's freshly written manifest
hashes to `374dbee592ad2dadb6aecf850b6be21a22a1ca7b5f70f1a34833a93fffae0c84`, and
`sha256(mine.replace(b"\n", b"\r\n")) == 0471bccb…` exactly — same CRLF relationship,
47151 line endings apart.

This one matters more than §9.1 because the manifest is **generated output** under
`results/`, so `.gitattributes` cannot help: the bytes depend on the platform that
*wrote* them. A policy asserting `manifest_sha256 == 0471bccb…` passes on a Windows
laptop and fails on a Linux CI runner.

Concrete request to **Lamei**: `attacks.metadata.write_manifest` opens with
`open(path, "w", encoding="utf-8")`, which translates `\n` on Windows. Adding
`newline="\n"` makes the manifest byte-identical everywhere, at no cost to anything
else. Concrete request to **Khalid**: resolve the policy's manifest hash from a run on
the platform CI will actually use, after that change.

### 9.3 The fixture builder is not deterministic across platforms — *Ahsan*

`TestFixturePack::test_builder_is_deterministic` fails on macOS/Linux. The content is
identical; only the key **order** in `MANIFEST.json` differs: `README.md` sorts before
`negative/…` here and after it on Windows, because `sorted()` over `Path` objects uses
case-insensitive comparison on Windows (`readme.md` > `negative\…`) and case-sensitive
on POSIX (`README.md` < `negative/…`). Sorting by
`p.relative_to(FIXTURES).as_posix()` as an explicit string key fixes it.

Also worth knowing: running that test **writes to
`tests/fixtures/stage3/MANIFEST.json` in the working tree**, so `pytest -q` leaves the
repository dirty. I restored it each time; a `git status` surprise after a test run is
this and nothing else.

### 9.4 A released defense with no test — *found here, fixed here*

While preparing the regression branch I removed V2's length limit and ran
`tests/test_endpoint.py tests/test_lab.py`: **82 passed**. The defense was only ever
measured by the attack run, never asserted, so a release could lose it with nothing
going red. `d6143ae` adds two tests — V2 must reject over-length input with 422 before
inference, and V1 must neither reject it nor return 200 (a 200 would mean silent
truncation). Verified in both directions: both pass on `stage3/rayyan`, and the V2 one
fails on the demo branch with the intended message.

### 9.5 A stale foundation assertion — *Ahsan, one line*

`TestRegistry::test_module_paths_are_recorded_not_imported` asserts
`not (ROOT / "endpoint" / "sentiment_v1.py").exists()` and says so itself: *"this test
is meaningless once Task 2 lands the module; update it then"*. Task 2 has landed it.
The file is yours; I have not touched it.

## 10. The controlled regression demonstration

Branch `stage3/rayyan-regression-demo` @ `d0a5fda`. **Never merge it.** One change:
V2's length limit removed. Defenses 2, 3 and 4 are untouched, so a gate failure on it
is attributable to that one removal. The now-unused imports are left in place on
purpose — the revert is putting two statements back and nothing else.

**What actually happens, measured on a real uvicorn process, not assumed:**

```
over-length request   500 {"detail":"Internal server error"}
stack trace in body   no
uvicorn process       still alive, /health still 200
normal request        200
extra field           422   (defense 2 still rejecting)
```

So do not promise a stack trace or a process crash from this demonstration. FastAPI
catches per request and V2's existing generic handler converts the exception into a
flat 500. That is the expected and sufficient finding, and it is exactly what the
policy's blocking "zero observed 5xx" check sees.

**The failing run, already executed** — same machine, same model revision, same frozen
`ci_core_v1` selection, 162 cases both times:

| | 200 | 422 | 400 | **5xx** |
| --- | --- | --- | --- | --- |
| released `emotion_v2` (`d6143ae`) | 135 | 24 | 3 | **0** |
| `stage3/rayyan-regression-demo` | 135 | 17 | 3 | **7** |

The seven are exactly the over-limit cases — `malformed.oversized_100kb`,
`malformed.oversized_1mb`, `boundary.length.plus_one` and the four
`…truncation.signal_{start,end}_over_limit` — which moved from a clean 422 rejection to
an unhandled 500. Nothing else moved. Artifacts:
`results/regressed_ci/emotion_v2/results.jsonl`
sha256 `aa8bd689966759258027c3aeafa6c030ca1fd6c3f0f5b6db3a158236fa393eee`.

Once Khalid's policy lands, this is a two-run demonstration under one frozen policy
with no other variable changed. The released code retains the defense, and `d6143ae`
now makes losing it fail a test rather than only an attack run.

**OCES was not run.** Its cases and rules are not frozen yet, and no defense was
touched to improve any result.

## 11. Docker cache material for Ahsan — I did not edit the Dockerfile

Both models at their pinned revisions, from `~/.cache/huggingface/hub`:

| Model | Files at the pinned revision | Snapshot | Repo dir on disk |
| --- | --- | --- | --- |
| sentiment `714eb0fa…` | `config.json`, `model.safetensors` (267.83 MB), `tokenizer_config.json`, `vocab.txt` (0.23 MB) | **268.1 MB** | 536.1 MB |
| emotion `0e1cd914…` | `config.json`, `merges.txt`, `pytorch_model.bin` (328.54 MB), `special_tokens_map.json`, `tokenizer.json`, `vocab.json` | **331.2 MB** | 662.3 MB |

The repo-dir figures are larger because the hub cache keeps blobs plus symlinked
snapshots; a `--no-symlinks` copy or a `COPY` of the snapshot directory costs the
snapshot figure.

Measured startup and runtime for `sentiment_v1`:

| | |
| --- | --- |
| Cold start, weights downloaded at the pinned revision | 57.3 s |
| Warm start, weights already cached | **1.3 s** import + load |
| First prediction after load | 2.3 s |
| Steady-state `/predict` | 17.4 ms median, 25.1 ms p95 |
| Peak RSS after load + 20 predictions | 364 MB |

Recommendation: bake both snapshots into the image and set `HF_HUB_OFFLINE=1`. A
container that downloads at start pays 57 s and needs network at run time; with the
cache present it is up in under two seconds. Ask me for anything else you need rather
than reading it off this table.

## 12. Concrete requests to other owners

1. **Ahsan — `run_all.run_experiment`.** The gate calls the CONTRACTS.md §8 signature:
   `run_experiment("ci", run_name=…, results_root=…, evaluation_ids=[…], html_only=…)`,
   and needs the returned dict to carry `run_id` and `evaluations[]` where each entry
   has `evaluation_id` and `target_dirs: {target_id: path}`. Against the current tree
   the gate detects the old signature and exits 2 naming it, rather than falling back
   to the two-target emotion flow and scoring a different evaluation than the policy
   names. Also please have `run_all` pass `--evaluation-id` and `--parent-run-id` to
   the runner, so `run_meta.evaluation_id` / `evaluation_run_id` are populated instead
   of `null`.
2. **Ahsan — one import edge to record.** `runner.run` now imports
   `attacks.metadata.scoped_registry`, which is CONTRACTS.md §4.3's own documented
   usage (its docstring example *is* this call site), but the §9 edge table only lists
   `runner.run → attacks.library`. Please add the edge explicitly, or have Lamei
   re-export it from `attacks.library`; I did not want to silently widen the table.
3. **Khalid — `evaluate_policy`.** I call it exactly as specified, keyword-only:
   `evaluate_policy(policy=…, analysis=…, run_metas={target_id: dict},
   results_by_target={target_id: list[RunResult]})`, and I require a `GateOutcome`
   back. Anything else is exit 2. Note the two selection hashes in §7.1 and pick
   deliberately which one the policy asserts.
4. **Lamei — `attacks.library.build_suite`.** Until it accepts `suite`/`task_id`, the
   runner forwards nothing and the legacy core/emotion path is byte-identical; any
   other combination raises rather than building the emotion core suite under a
   sentiment or OCES label. Also the `newline="\n"` fix in §9.2.
5. **Lamei — `baseline/sentiment_baseline.json`.** Blocking the real sentiment core
   run, and only that.

## 13. What is not done, stated plainly

- **No real sentiment core or OCES run.** Blocked on the sentiment baseline and on the
  OCES freeze. No case count is claimed for either.
- **No gate pass on real evidence.** `analysis.policy` does not exist yet. The gate's
  exit-2 paths are demonstrated for real (it exits 2 and names the missing module);
  exit 0 and exit 1 are demonstrated against the shared fixtures with doubles for the
  orchestrator and the policy. **That is a shape check of the exit-code mapping, not a
  working release gate**, and I am not presenting it as one.
- **No two-target paired run in one parent run directory.** Each target writes into its
  own directory and two runs of the same suite share a planned fingerprint — checked in
  tests — but the enclosing `run.json` index is Ahsan's and has not landed, so the
  paired layout has not been exercised end to end.
- **No deployment, no report, no PDF.** Not mine.
- The 116 added tests prove the components. They do not prove the pipeline: while
  `analysis.policy` and the Stage 3 `run_experiment` are absent, passing component
  tests are exactly that.
