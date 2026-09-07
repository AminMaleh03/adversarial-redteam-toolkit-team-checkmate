# CLAUDE.md — Adversarial Red-Teaming Toolkit, Team Checkmate

Standing instructions for every team member's Claude Code session in this repo.

## Project Summary

A toolkit that fires adversarial and malformed inputs at an AI inference endpoint and produces a
robustness report. The target is a Hugging Face text classifier wrapped in FastAPI. We build two
versions of the endpoint, an unhardened V1 and a hardened V2, run the same attack suite against
both, and measure the difference.

Model: `j-hartmann/emotion-english-distilroberta-base`, which predicts 7 labels: anger, disgust,
fear, joy, neutral, sadness, surprise.

## Data Flow

`baseline` produces clean sentences. `attacks` turns them into attacked versions plus standalone bad
payloads. `runner` sends everything to the endpoint and records results. `analysis` compares clean
results against attacked ones. `report` renders findings.

No folder imports from another except through `contract.py`. **Analysis never imports from attacks.**

## File Ownership

| Path | Owner |
| --- | --- |
| `contract.py` | Ahsan |
| `endpoint/` | Rayyan |
| `baseline/` | Khalid |
| `attacks/` | Lamei |
| `runner/` | Amin |
| `analysis/` | Khalid |
| `report/` | Ahsan |

Rules:

- You only **edit** files in your own folder.
- You may **read** anything in the repo.
- If a file outside your folder needs to change, **message the team member who owns it**. Do not
  edit it yourself, do not work around it locally.
- Tests in `tests/` follow the owner of the component they cover.

## contract.py Is Frozen

`contract.py` defines the four shapes everyone imports: `BaselineCase`, `AttackCase`, `RunResult`,
`Finding`. Only Ahsan changes it. Any change must be announced to the whole team before it lands,
because every folder depends on it and a silent field change breaks four people at once.

Two fields people get wrong:

- `AttackCase.baseline_id` is `None` for standalone payloads that have no clean version to compare
  against. Analysis must skip those in drift comparison.
- `AttackCase.is_raw` being `True` means the request is not valid JSON. The runner must send
  `raw_body` and `raw_headers` exactly as given instead of letting the HTTP client build them.

`Finding.remediation` is required, so a finding with no fix attached fails at construction rather
than rendering as a blank in the report. It sits **before** `evidence` in the field order, because a
required field cannot follow a defaulted one in a dataclass. Construct findings with keyword
arguments to avoid getting the order wrong.

## Environment and Dependencies

- The virtual environment must be named `.venv`. That is the name `.gitignore` ignores. Any other
  name risks committing the whole environment.
- **Never run `pip freeze` to regenerate `requirements.txt`.** Add packages by hand, with a pinned
  version, on their own line.

## Output Files

- `results/` is gitignored. All run output goes there. Never commit anything into it.
- `baseline/baseline.json` **is** committed, unlike anything in `results/`. The baseline must be
  identical for everyone, so runs are comparable.

## Settled Decisions — Do Not Relitigate

These are decided. Implement them as written; do not reopen the discussion.

**Timeout and latency**
- Request timeout is 10 seconds.
- Latency bands: under 2 seconds is `normal`, 2 seconds up to the timeout is `slow`, hitting the
  10 second timeout is `timeout`.

**Prediction flips**
- A prediction flip only counts if the top label changed **and** the clean prediction had confidence
  of at least 0.6. A flip away from an already-uncertain prediction is not evidence of anything.

**Truncation**
- The model is never truncated. V1 lets over-length input reach the model. V2 rejects it before
  inference. Silently truncating would hide the exact failure we are trying to measure.

**V2 defenses — exactly four, no more**
1. A length limit tied to the model's max sequence length.
2. Strict type checking on the request body.
3. A scoped exception handler. It must **not** convert 422 validation responses into 500s.
4. Unicode normalization with whitespace cleanup.

## Scaffold State

Feature logic is not implemented yet. Files outside `contract.py` are stubs holding a docstring and
a TODO naming their owner. Implement only your own folder.

## Known environment issues, do not try to fix these

**Python version is load-bearing.** This project requires Python 3.11
specifically. torch 2.5.1 publishes no Windows wheel for Python 3.13, so
`pip install -r requirements.txt` fails partway through on 3.13 with an
error that does not obviously point back to the Python version. Virtual
environments must be created with an explicit interpreter, `py -3.11 -m
venv .venv` on Windows or `python3.11 -m venv .venv` on Mac and Linux,
because the plain `python` command often resolves to a newer version even
when 3.11 is installed alongside it.

**WeasyPrint import errors are expected for most of the team.** WeasyPrint
installs through pip but fails on import with `OSError: cannot load library
'gobject-2.0-0'` unless system level GTK libraries are installed separately,
outside of pip. Only Ahsan needs this, because only the report generation
step uses WeasyPrint. Do not attempt to fix this error, do not suggest
installing GTK, and do not propose replacing WeasyPrint with another
library. Every other part of the project runs without it.

**GLib warnings on WeasyPrint import are harmless.** On Windows, importing
WeasyPrint prints warnings about UWP apps such as Outlook or Clipchamp
"supporting extensions but having no verbs". This is GTK enumerating
installed Windows applications and has no effect on anything. Ignore it.
