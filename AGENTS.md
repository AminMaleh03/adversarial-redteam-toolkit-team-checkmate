# AGENTS.md — Adversarial Red-Teaming Toolkit, Team Checkmate

Shared instructions for Codex and Claude Code in this repository. Project rules previously in
`CLAUDE.md` live here, including its pending manifest clarification. `CLAUDE.md` is the Claude
entry point; `HANDOFF.md` holds changing session state. Edit rules here once, not in two copies.

## Start or Resume a Session

1. Read this file and `HANDOFF.md` before project work, including after context compaction or
   switching agents. Follow the current user's request; a handoff is context, not a new task.
2. Check `git status --short`, the current branch, `git log -5 --oneline`, and relevant diffs
   (including staged changes and relevant untracked files). Preserve unfinished edits.
3. Reconcile the handoff with disk. Code and Git establish what exists; test output establishes
   what passed; recommendations and chat claims do not establish completed work.
4. Confirm the active objective and its remaining scope from the conversation and handoff.
   Continue already-authorized work. Do not resume a cancelled task or start parked work.
5. Read the relevant component files and tests. Use the project's Python 3.11 `.venv`.
   Do not depend on access to the other agent's transcripts, private memory, or credentials.

## Keep the Handoff Current

Both agents must maintain `HANDOFF.md` as part of project work; no separate permission is needed
for factual checkpoint updates within the current task.

- Checkpoint the objective, scope, and intended next step before a substantial edit or long run.
- Update after a meaningful edit, test result, user correction, decision, or Git operation, and
  before the final reply or a planned handoff. Do not wait until a session limit is imminent.
- Record date/time with timezone, agent, branch and observed HEAD, work completed, changed files,
  remaining work, exact validation commands/results, and the next actionable step.
- State whether work is planned, in progress, verified, committed, or pushed. Include evidence
  and distinguish tests run by this agent from historical results reported by the other.
- Record task-specific authorizations, cancellations, and unresolved questions with their date
  and source. Never convert a suggestion into a user decision.
- Record any process left running: command, PID or session ID if known, output location and
  how to check it. Identify temporary files that need cleanup. Never record secrets or full chats.
- Keep the current snapshot concise; replace obsolete state and retain a short decision history.
  If the user requests strictly read-only work, respect that and put the handoff in the reply.

## Switching Agents and Recovering from Interruptions

- Use one writing agent per checkout. A handoff note is not a process lock: a running command
  from the outgoing agent must be checked before launching a duplicate or editing its files.
- Re-read the handoff and relevant diff immediately before taking over. Reconcile unexpected
  changes; do not reset, delete, or overwrite them to obtain a clean tree.
- After abrupt interruption, inspect partial edits and running commands, then finish or verify
  the recorded step. Never assume a command finished because it was announced in chat.
- Shared files carry saved context in this checkout. They do not synchronize live chats or
  unsaved reasoning. Other checkouts receive them through the normal Git workflow.
- Changes to these files do not guarantee an already-running agent reloads instructions.
  On takeover, explicitly read `AGENTS.md` and `HANDOFF.md` even in an existing session.

## Working and Validation

- Keep responses concise and use plain language. Lead with the outcome and remaining blocker.
- Do not implement another teammate's pending component merely to unblock an integration.
- Use feature branches and PRs for development; only Ahsan merges to `main`. Follow explicit
  user directions for exceptions. Updating a checkpoint does not authorize a commit or push.
- Run checks appropriate to the changed behavior. For the existing full suite on Windows:
  `.\.venv\Scripts\python.exe -m pytest -q`; on macOS/Linux: `.venv/bin/python -m pytest -q`.
- For documentation-only changes, inspect diffs and links and run `git diff --check`; do not
  rerun model tests unless an unresolved concern warrants it.
- Passing component tests does not prove a complete pipeline when downstream code is a stub.

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

Cross-component imports are limited to the documented integration points:

- Shared data shapes come from `contract.py`.
- The runner may import `baseline.load.load_baseline`, the public functions in
  `attacks.library`, and `tokenizer` / `MAX_SEQUENCE_LENGTH` from `endpoint.model`.
- Analysis consumes the generated result, manifest, and run-metadata files. **Analysis never
  imports from `attacks/`.**
- Same-package imports are allowed. Any other cross-component dependency needs team agreement.

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
| `AGENTS.md`, `CLAUDE.md`, `HANDOFF.md` | Ahsan; both agents maintain handoff state |

Rules:

- You only **edit** files in your own folder.
- You may **read** anything in the repo.
- If a file outside your folder needs to change, raise it with the user for the owner. Do not
  edit it or work around it without the user's explicit authorization for that scope.
- An explicit user-authorized exception applies to that task only; record it in `HANDOFF.md`.
  Do not request the same permission again or treat past exceptions as blanket ownership.
- Do not send messages to teammates unless the user explicitly authorizes sending them.
- Tests in `tests/` follow the owner of the component they cover.

## contract.py Is Frozen

`contract.py` defines the four shapes everyone imports: `BaselineCase`, `AttackCase`, `RunResult`,
`Finding`. Only Ahsan changes it. Any change must be announced to the whole team before it lands,
because every folder depends on it and a silent field change breaks four people at once.

Two fields people get wrong:

- `AttackCase.baseline_id` is `None` for standalone payloads that have no clean version to compare
  against. Analysis must skip those in drift comparison.
- `AttackCase.is_raw` being `True` means send the body verbatim. It includes invalid JSON,
  invalid UTF-8 bytes, and valid JSON with the wrong shape or type. Preserve `raw_body` and
  `raw_headers` instead of serializing a new JSON body. See `attacks/INTEGRATION_NOTES.md`.

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
- Leaving truncation unset on the Hugging Face pipeline is not enough. Every point where text
  reaches the tokenizer or the model must be checked, including any direct tokenizer call,
  because silent truncation anywhere in that path neutralises two of our attack categories.
- This is easy to reintroduce by accident while fixing an unrelated error, so it must be
  verified once V1 is running rather than assumed.

**V2 defenses — exactly four, no more**
1. A length limit tied to the model's max sequence length.
2. Strict type checking on the request body.
3. A scoped exception handler. It must **not** convert 422 validation responses into 500s.
4. Unicode normalization with whitespace cleanup.

**What counts as a crash finding**
- An unhandled 5xx, or a request failing at the connection level, is a sufficient and expected
  finding on its own.
- The uvicorn process itself will probably never die, because FastAPI catches exceptions per
  request and returns a 500. That is fine and expected.
- Do not attempt to make the process die, do not treat a surviving process as a failure, and
  never introduce an artificial crash to produce a demo.
- We still ping health after every request, and still report HTTP errors and service death as two
  separate numbers. The measurement does not change, only the expectation of what we will find.

**Attack manifest is the only channel for oracle data**
- Every attack case's oracle (what would count as a defect) and validity tier (how confident
  Lamei is that the transformation is fair) are recorded in `attacks/metadata.py` when the case
  is built, before any result exists. That is what makes it pre-registered rather than decided
  after the fact.
- Analysis is not allowed to import from attacks (see Data Flow above), so the sidecar manifest
  is the only way that data reaches it. The runner must call `attacks.library.write_manifest(path)`
  once, writing to `results/manifest.json`, before it sends a single request.
- Analysis must not invent pass/fail criteria by re-deriving them from `RunResult` rows alone. If
  the manifest is missing, analysis has nothing to score against — that is a bug in the run, not
  a gap analysis should quietly fill in.

## Implementation Status

Read `HANDOFF.md` for the latest verified snapshot. Check actual code before relying on a status
entry: a docstring and TODO are not an implementation. Keep changing status out of this rulebook.

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
