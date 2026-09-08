# Handoff — Team Checkmate

## Current Checkpoint

- Updated: 2026-09-09 01:08 +04:00 (Asia/Dubai).
- Agent: Claude Code, working with Ahsan in the local shared checkout. The preceding
  documentation edit in this checkpoint was made by Codex.
- Branch / observed HEAD: `main` / `470b314` before this commit. The previous checkpoint recorded
  `24ea950`, which was already stale; `470b314` was the actual tip and is corrected here.
- Active request: keep Codex and Claude Code instructions synchronized, then commit and push.
- Progress: Codex corrected the cross-component import rule to permit the runner's documented
  public integration points while retaining the analysis-to-attacks prohibition, and `CLAUDE.md`
  now imports the shared rules with `@AGENTS.md`. Claude verified the three named integration
  points resolve against the real code (`baseline.load.load_baseline`; `attacks.library`
  exposing `standalone_cases`, `build_derived`, `build_suite`, `write_manifest`;
  `endpoint.model.tokenizer` with `MAX_SEQUENCE_LENGTH` = 512) and that `git diff --check` is
  clean. Documentation-only change, so the application test suite was not rerun.
- Changed files this turn: `AGENTS.md`, `CLAUDE.md`, and this checkpoint. Committed and pushed
  directly to `main` on Ahsan's explicit instruction, the documented exception to the
  feature-branch rule. No application code changed.
- Running processes / temporary files: none left running. Claude created scratch verification
  scripts outside the repository, under the session scratchpad; nothing to clean up in-tree.

## Verified Pipeline Snapshot

Verified locally by Codex on 2026-09-09, at implementation HEAD `33e2dcc` (unchanged by `24ea950`):

| Component | Owner | State |
| --- | --- | --- |
| `contract.py` | Ahsan | Four implemented dataclasses; frozen |
| `endpoint/` | Rayyan | V1 and V2 implemented; existing tests pass |
| `baseline/` | Khalid | 42 committed sentences and `baseline.load.load_baseline()` |
| `attacks/` | Lamei | Six categories; default suite builds 1,886 attacks |
| `runner/` | Amin | Stub; immediate blocker to a full run |
| `analysis/` | Khalid | Stubs |
| `report/` | Ahsan | Renderer and HTML template are stubs |

No local `results/` directory existed at verification. Component tests passing does not mean
the full V1/V2 run, analysis, or report has happened.

Validation already completed by Codex before this documentation task:

- `.\.venv\Scripts\python.exe -m pytest -q`: **64 passed, 1 warning in 53.44s**.
  The warning is Starlette's deprecated AnyIO `BlockingPortal` alias.
- In-memory `load_baseline()` -> `build_suite(baselines)` check: 42 baselines, 1,886 attacks,
  1,886 unique attack IDs, zero orphaned baseline references. This used default approximate
  boundaries, not the real-tokenizer mode intended for the actual runner.
- Category counts: malformed 21, boundary 11, perturbation 377, encoding 973, whitespace 252,
  truncation 252.

## Decisions and User Scope to Preserve

Source: Ahsan's local Claude Code conversations from 8–9 September, recovered by Codex and
checked against the repository where possible.

- **Leave the runner to Amin.** Ahsan explicitly stopped Claude from implementing it on
  8 September, late evening. A general takeover request does not reverse that instruction.
- Khalid handles analysis after Amin's runner work; Ahsan handles the report afterward.
  Do not start those implementations based solely on this handoff.
- Ahsan specifically authorized the baseline loader, its tests/cosmetic cleanup, and V2's
  explicit `truncation=False` fix. Those exceptions are completed, not continuing permission
  to edit Khalid's or Rayyan's components.
- Loader merge: `f4c49f3`; truncation merge: `33e2dcc`. Both exist locally; Claude reported
  pushing them and deleting the feature branches.
- Latest Claude documentation request: update contracts/rules only if needed. No dataclass
  change was needed. Claude saved the manifest rule and corrected scaffold status but hit
  its limit before final verification. These facts now live in the shared files.

## Runner Brief — Specified, Not Implemented

Ahsan wrote a ClickUp brief and asked Claude to review it. Preserve its requirements when
reviewing Amin's future work:

- Use the baseline loader; build a deterministic suite, with real-tokenizer counts and explicit
  `truncation=False` for exact boundaries.
- Export `results/manifest.json` after building the suite and before sending any request.
- Send clean baselines, standalone attacks, then derived attacks in stable order.
- Preserve raw bodies/headers, including invalid UTF-8 bytes and valid JSON of the wrong shape.
- Explicit target/version CLI arguments, smoke-run limit and a skip option.
- Record every `RunResult` field, full response body, timing, and health after each request.
  Append and flush results incrementally; separate output by version; stop after failed health.
- Fingerprint the ordered inputs so the V1/V2 comparison can establish matching inputs.

Claude's review proposed three clarifications. The transcript does not establish that the
ClickUp task was subsequently edited or sent:

1. Store the fingerprint in a separate metadata file, e.g. `results/run_meta_<version>.json`;
   do not add a field to the frozen `RunResult`.
2. Explicitly require `all_scores`.
3. Explain differing skips/limits and their effect on fingerprints/comparability. The precise
   distinction between the full planned suite and selected/executed inputs still needs to be
   made explicit in the runner metadata design.

## Open Questions and Parked Work

- Ahsan's supplied Khalid task now specifies the six unchanged top-level categories, rates with
  explicit eligible denominators, exclusion of unresolved review/diagnostic cases, grouping by
  category/subfamily/failure mode, and maximum supporting-instance severity rather than sums.
  This resolves the original mapping/raw-count concern at the specification level. It is not
  yet implemented or validated; descriptive rates remain dependent on the suite composition.
- Apply the manifest's per-case oracle and validity tier. `REVIEW` and `DIAGNOSTIC` cases must
  not be automatically counted as vulnerabilities; see `attacks/INTEGRATION_NOTES.md`.
  Claude proposed qualified language for `SILVER` cases; report implementation remains pending.
- Measure handwritten baseline confidence in the clean run; do not silently rewrite committed
  baseline sentences to improve scores. Claude raised this as a limitation to assess.
- Permanent endpoint tests for over-length rejection/non-truncation and Unicode cleanup remain
  parked. Claude reported temporary live checks passing; those are historical evidence.
- Documentation inconsistencies to resolve within an authorized task: the older `contract.py`
  comment equating raw mode with invalid JSON; integration notes using
  `attack_manifest.json` instead of the agreed `manifest.json`; README's plain-Python venv
  command. Do not quietly edit other owners' code while resolving documentation.
- Endpoint orphaned docstrings remain a parked cosmetic issue.
- Claude previously verified Python 3.11.9 and GTK/WeasyPrint on Ahsan's machine; Codex has not
  repeated the WeasyPrint import check. Other teammates may lack GTK; follow the shared rules.

## Next Action

The revised runner and analysis briefs passed review and are ready for ClickUp. No component
implementation is assigned to the agent. Amin can implement the runner while Khalid builds and
unit-tests analysis against synthetic fixtures; real runner output then provides integration
validation. Ahsan implements the report after the analysis output shape is available.

For a takeover, read `AGENTS.md` and this file, inspect Git state, and resume only the latest
user-authorized task. Update this checkpoint whenever progress or scope changes.
