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

## Development Environment

- Python 3.11
- A local virtual environment named exactly `.venv`, because that is the name `.gitignore` ignores
- Dependencies pinned in `requirements.txt`

Python 3.11 is not a preference, it is a hard requirement. `torch==2.5.1` publishes no wheel above
CPython 3.12, so on Python 3.13 the install fails outright at torch. Check with `python --version`
before creating the environment.

Create the environment and install dependencies:

```bash
python -m venv .venv
```

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
contract.py     Shared dataclasses. The only thing any folder imports from another.
endpoint/       The FastAPI target: shared model loading, unhardened V1, hardened V2.
baseline/       Clean sentences that attacks mutate and analysis compares against.
attacks/        Attack generators, one module per category, assembled by library.py.
runner/         Sends every case to both endpoints and records the results.
analysis/       Turns results into findings: drift, severity, V1 vs V2 comparison.
report/         Jinja2 template and the renderer that produces the HTML and PDF report.
tests/          Pytest suites, one per component.
results/        Run output. Gitignored and created at runtime, never committed.
```

## Team Workflow

Development happens on individual feature branches, one per person, merged into `main` through pull
requests. Only Ahsan merges to `main`.

## Running the Endpoint

TODO — commands do not exist yet.

## Running the Toolkit

TODO — commands do not exist yet.

## Generating the Report

TODO — commands do not exist yet.
