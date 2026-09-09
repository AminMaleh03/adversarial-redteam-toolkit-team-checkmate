---
title: Team Checkmate — Adversarial Input Red-Teaming Toolkit
emoji: ♟️
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
fullWidth: true
header: mini
---

# Adversarial Red-Teaming Toolkit — Team Checkmate

Toolkit for automated robustness testing of AI inference endpoints.

## What This Project Does

This toolkit fires adversarial and malformed inputs at an AI inference endpoint and produces a
robustness report. The target is a Hugging Face text classifier wrapped in FastAPI. We build two
versions of the endpoint, an unhardened V1 and a hardened V2, and run the same attack suite against
both. The report measures the difference between them, showing which attacks break V1 and which of
those the V2 defenses actually stop.

## Model

We use [`j-hartmann/emotion-english-distilroberta-base`](https://huggingface.co/j-hartmann/emotion-english-distilroberta-base),
which classifies English text into 7 emotion labels: anger, disgust, fear, joy, neutral, sadness,
and surprise.

The exact revision is pinned in [`endpoint/model.py`](endpoint/model.py) so every teammate's
cache and both endpoint versions resolve to identical weights regardless of what `main` points
to later:

```
MODEL_ID       j-hartmann/emotion-english-distilroberta-base
MODEL_REVISION 0e1cd914e3d46199ed785853e12b57304e04178b
```

## Development Environment

- Python 3.11
- A local virtual environment named exactly `.venv`, because that is the name `.gitignore` ignores
- Dependencies pinned in `requirements.txt`

Python 3.11 is not a preference, it is a hard requirement. `torch==2.5.1` publishes no wheel above
CPython 3.12, so on Python 3.13 the install fails outright at torch. Check with `python --version`
before creating the environment.

Create the environment with an explicit Python 3.11 interpreter. On Windows:

```bash
py -3.11 -m venv .venv
```

On macOS/Linux, use `python3.11 -m venv .venv`.

Activate it on Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

Then install:

```bash
pip install -r requirements.txt
```

### Note on WeasyPrint

WeasyPrint needs system libraries that `pip` does not install. On Windows this means the GTK
runtime, and on macOS it means installing `pango` and its dependencies through Homebrew. Follow the
[WeasyPrint installation docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) for
your platform. Everything except PDF generation works without it.

The failure is confusing because `pip install` **succeeds** — WeasyPrint is pure Python and the
missing pieces are native libraries loaded at import time. Verified on Windows: the install exits 0
and then `import weasyprint` raises

```
OSError: cannot load library 'gobject-2.0-0': error 0x7e.
```

If you see that, it is not a bug in our code. Install the
[GTK3 runtime for Windows](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases)
and reopen your shell so the DLLs are on `PATH`.

## Folder Structure

```
run_all.py                Single-command orchestration: full experiment, fast demo, reproducible runs.
Team Checkmate Logo.png   The real project logo. Required -- report generation refuses to
                          substitute a placeholder if this file is missing. Do not rename/edit it.
contract.py               Frozen shared dataclasses; integration boundaries are in AGENTS.md.
endpoint/                 The FastAPI target: shared model loading, unhardened V1, hardened V2.
baseline/                 Clean sentences that attacks mutate and analysis compares against.
attacks/                  Attack generators, one module per category, assembled by library.py.
runner/                   Sends every case to both endpoints and records the results.
analysis/                 Turns results into findings: drift, severity, V1 vs V2 comparison.
report/                   Jinja2 templates (full audit report + short demo report) and the
                          renderer that produces the HTML and PDF.
artifacts/                Stable, project-relative location for the canonical verified full
                          benchmark report that demo mode links to. Not gitignored like
                          results/; see "Verified full-benchmark artifact" below.
tests/                    Pytest suites, one per component.
results/                  Run output. Gitignored and created at runtime, never committed.
```

## Team Workflow

Development happens on individual feature branches, one per person, merged into `main` through pull
requests. Only Ahsan merges to `main`.

## Running the Toolkit

`run_all.py` is the single entry point. It starts V1, runs the attack suite against it, stops
it, starts V2, runs the same suite against V2, stops it, then runs analysis and renders the
report -- using the existing runner/analysis/report components unchanged. From the repository
root with `.venv` active:

**Full experiment** (all 42 baselines + 1,886 attacks per version, including the 10 MB case).
Renders the complete technical/audit report: full results, the complete finding register,
Method, and the audit appendix.

```powershell
python run_all.py --mode full
```

**Fast demo**, for judges or a quick check. Same endpoints, same attack definitions, same
runner, same real inference and analysis -- only a small curated subset of real attacks is
sent, so it finishes in well under a minute instead of several minutes. One case,
`malformed.oversized_10mb`, is excluded from the demo's curated subset only (it sits right at
the 10-second request deadline and has been observed to land as either a slow-but-completed
response or a genuine timeout depending on machine load, which would make a live demo look
like it found a new V2 regression purely from timing noise). It is untouched everywhere else:
still built, still registered in the manifest, still sent in full mode.

Demo mode renders a short, single-page, judge-facing report instead of the full audit report:
a partial-suite banner (real executed/planned counts, never hardcoded), one featured server
failure and one featured prediction flip with the actual input text and a visually highlighted
changed character, a concise demo-subset comparison, and a short Method section -- roughly 5
PDF pages instead of the full report's ~47. Its navbar links to **View Detailed Report**,
which opens the canonical [verified full benchmark](#verified-full-benchmark-artifact) in a
new tab, so a judge can go from the live demo straight to the authoritative evidence.

```powershell
python run_all.py --mode demo
```

Both modes automatically open the generated `report.html` in your default browser when they
finish. Pass `--no-open` to skip that (CI, Docker, headless runs, automated tests) -- the run
still completes and the report still gets written, it just is not opened:

```powershell
python run_all.py --mode demo --no-open
python run_all.py --mode full --no-open
```

Browser launching lives only in the CLI (`run_all.py main()`); the reusable
`run_experiment()` function below never touches a browser, so a future server/Docker/Hugging
Face caller can invoke it directly with no risk of it trying to open a window.

**Reproducibility**: run full mode twice with different names and compare the two reports.
Each name gets its own output directory, so the second run never overwrites the first:

```powershell
python run_all.py --mode full --run-name repro_1
python run_all.py --mode full --run-name repro_2
```

Add `--run-name NAME` to any mode to control the output directory name; otherwise it defaults
to a UTC timestamp (`full_20260909_135157`, `demo_20260909_140301`, ...). Do not pass
`--reload` to anything in this pipeline -- it would silently restart the endpoint mid-suite
and hide exactly the failures being measured.

### Output layout

```
results/<run-name>/
├── v1/                    manifest.json, results_v1.jsonl, run_meta_v1.json, v1_server.log
├── v2/                    manifest.json, results_v2.jsonl, run_meta_v2.json, v2_server.log
├── demo_evidence.json     featured failure + featured prediction flip, machine-readable
└── report/                report.html, report.pdf, analysis.json, export_meta.json
    └── detailed/          demo mode only: a portable copy of the verified full benchmark
                            (report.html, report.pdf, analysis.json, export_meta.json) that
                            "View Detailed Report" links to. Present only if
                            artifacts/verified_full_report/ exists when the demo report is
                            generated.
```

Open `results/<run-name>/report/report.html` in a browser (this happens automatically unless
you passed `--no-open`), or `report.pdf` in a PDF viewer. `demo_evidence.json` carries a
`literal_crash_case_available` flag: it is only `true` when a request in that run actually
made the post-request health check fail (observed unavailability). An HTTP 5xx alone, with the
service still answering health checks afterward, is reported as an unhandled server error, not
a crash -- this distinction is preserved even though the demo report keeps that specific note
small and out of the way rather than in a large warning box.

Every generated `report.html`/`report.pdf` embeds the real Team Checkmate logo (read once from
`Team Checkmate Logo.png` at the repo root and inlined as a `data:` URI), so the report is
fully self-contained and portable -- it displays correctly wherever the file is opened from or
copied to, with no separate asset file and no absolute path. If that source file is missing,
report generation fails loudly rather than substituting a placeholder logo.

`run_all.py` also exposes `run_experiment(mode, run_name=None)` as a plain Python function
(no interactive prompts, project-relative paths, returns a structured result dict) for a future
deployment UI to call directly instead of shelling out to the CLI.

### Verified full-benchmark artifact

`artifacts/verified_full_report/` is the stable, project-relative copy of the canonical full
benchmark report that demo mode's "View Detailed Report" link points to. Unlike `results/`,
it is not gitignored by the same blanket rule and is meant to be a durable reference, not
run output -- decide with the team whether to commit it.

It holds a plain copy of a `report.generate.generate_report(..., mode="full")` bundle
(`report.html`, `report.pdf`, `analysis.json`, `export_meta.json`) produced from one already-
validated full run's `analysis.json` (1928/1928 coverage both versions, matching planned and
manifest fingerprints). To (re)create or refresh it after a template change, without rerunning
the 1,928-case benchmark, re-render an existing validated `analysis.json`:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -c "from pathlib import Path; from report import generate as r; r.generate_report(Path('results/<validated-run>/report/analysis.json').read_bytes(), 'artifacts/verified_full_report', mode='full')"
```

Only do this from a run that already met the full-coverage/matching-fingerprint bar above --
never from a partial or demo run, and never by inventing new results.

### Manual component commands (troubleshooting)

For debugging one stage in isolation, run the components directly. Use separate terminals from
the repository root with `.venv` active:

```powershell
python -m uvicorn endpoint.v1:app --host 127.0.0.1 --port 8000
python -m runner.run --target http://127.0.0.1:8000 --version v1 --out results/my-benchmark/v1
# stop V1 (Ctrl+C), then:
python -m uvicorn endpoint.v2:app --host 127.0.0.1 --port 8001
python -m runner.run --target http://127.0.0.1:8001 --version v2 --out results/my-benchmark/v2
```

Both endpoints expose `POST /predict` and `GET /health`. For a smaller smoke run use
`--limit 20` on the runner. See [runner/README.md](runner/README.md) for coverage, artifact
behavior and exit codes.

Then analyze and render manually:

```powershell
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
python -m analysis.analyze results/my-benchmark | python -m report.generate --input - --out results/my-report
```

Add `--html-only` to `report.generate` to render without the native PDF runtime, and
`--mode {full,demo}` to pick the presentation (default `full`). The output directory must not
already exist. The [report guide](report/README.md) covers saved input, interpretation,
safety and testing; the [analysis guide](analysis/README.md) defines the schema and
comparison rules.

## Deployment (System V4)

`web/` is a thin FastAPI layer around the same `run_experiment()` used by `run_all.py` --
it does not reimplement any attack/runner/analysis/report logic. It serves a public
welcome page, a "Run Live Attack Test" button that starts one background demo run at a
time (protected by an in-process lock), and serves the resulting report over HTTP. See
`AGENTS.md` for the full architecture and ownership rules.

Local (without Docker):

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.app:app --host 0.0.0.0 --port 7860
```

Then open `http://localhost:7860/`.

With Docker (matches the Hugging Face Docker Space build):

```bash
docker build -t team-checkmate-v4 .
docker run --rm -p 7860:7860 team-checkmate-v4
```

Only port 7860 is public; V1/V2 (`127.0.0.1:8000`/`8001`) run and are attacked entirely
inside the container during a live run and are never exposed to the host or the browser.

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

For cached-model offline testing, set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` in
the shell first. Report tests include real PDF export when the native runtime is available.
