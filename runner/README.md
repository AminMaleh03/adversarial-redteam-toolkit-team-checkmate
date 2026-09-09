# Runner

Run from the repository root with the Python 3.11 `.venv`. Start the chosen endpoint separately.

```powershell
.\.venv\Scripts\python.exe -m runner.run --target http://127.0.0.1:8000 --version v1
.\.venv\Scripts\python.exe -m runner.run --target http://127.0.0.1:8001 --version v2
```

For a smoke test, select an attack prefix and use a separate output directory:

```powershell
.\.venv\Scripts\python.exe -m runner.run --target http://127.0.0.1:8000 --version v1 --limit 40 --skip malformed.oversized_10mb --out results/smoke
```

The runner sends every baseline, then selected standalone attacks, then selected derived attacks.
It records observations; analysis owns oracle interpretation, flips, severity and findings.

## Settings and coverage

- `--target` and `--version` are required. Version is never inferred from the URL.
- Prediction requests have a **10-second total deadline**, covering connection, upload, response
  headers and body. `--timeout 10` is accepted for compatibility; other values are rejected.
  A response that keeps delivering bytes cannot extend the deadline. Timeout cancels the client
  operation; it does not guarantee that the endpoint has stopped its own inference work.
- `--health-timeout` defaults to 2 seconds and must be positive and finite. The effective value
  is recorded in metadata. A health transport failure gets one retry with a fresh client;
  prediction requests are never retried.
- `--limit N` accepts non-negative integers and limits attacks only. Zero sends baselines only.
- Repeat `--skip ATTACK_ID` to exclude known cases within the limited prefix. An attack outside
  the prefix is classified as limit-excluded even if also named in `--skip`.
- The fingerprint and planned count always describe the full built suite. Ordered selected,
  skipped and limit-excluded IDs describe selection; completed and missing IDs describe execution.
  Skipped IDs are recorded even if the run stops before reaching them. Coverage is completed/planned.

## Artifacts and failure handling

The default output directory is `results/`. For each version the runner writes
`results_<version>.jsonl` and `run_meta_<version>.json`; both versions share `manifest.json`.
Every JSONL row has the frozen `RunResult` shape, including the full response body and all scores.
Raw attack bytes and supplied headers are preserved.

The attack library exports the manifest exactly once into a temporary staging directory beneath
the chosen output directory, before any HTTP request. A successful preflight publishes it as
`manifest.json` before the first prediction. Failed preflight removes staging and leaves all
previous manifest, result and metadata files unchanged; it creates no new published run.

After preflight, a new invocation replaces that version's results and metadata. Use separate
`--out` directories to retain multiple experiments. Rows are flushed and synced as they finish.
Health failure saves the current row and stops further cases. Ctrl+C preserves completed rows,
writes `termination_reason="interrupted"`, and exits 130. If interrupted during preflight,
previous artifacts remain intact and no new run metadata is published. Normal completion is
assigned only after the selected cases finish. Missing cases must never be treated as V2 fixes.

Exit codes: 0 for completed selected execution (including limits), 1 for post-request health
failure, 2 for failed preflight or invalid CLI arguments, 130 for interruption. Unexpected
exceptions propagate after recording `errored` metadata if a new result file has been opened.

## Implementation and validation

The synchronous `Runner` interface uses one `asyncio.Runner` and `httpx.AsyncClient` internally.
Requests remain sequential. Each HTTP operation is wrapped in `asyncio.timeout`; closing the
runner closes its client and event loop. Call `close()` in a `finally` block when using the class
directly. Injected transports must implement HTTPX's async transport interface (`MockTransport`
supports both). No additional dependency is required beyond the existing Python 3.11 environment.

`tests/test_runner.py` includes CLI regressions for artifact preservation, accurate settings,
early skips, interruption and invalid limits, plus a real local socket test that cancels a
dripping response at ten seconds and verifies a subsequent request succeeds.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runner.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

See [HANDOFF.md](../HANDOFF.md) for the latest verified commits, test results and integration scope.
