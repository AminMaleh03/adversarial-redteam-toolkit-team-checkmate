# Stage 3 ownership

Four implementing members: **Ahsan, Rayyan, Khalid, Lamei**. There is no work or handover
dependency on Amin.

The rule is unchanged from `AGENTS.md`: **you edit only files you own; you may read
anything.** If a file outside your folder needs to change, raise it with the owner through
Ahsan. Do not edit it, and do not work around it.

## Production files

| Path | Owner |
| --- | --- |
| `run_all.py` | Ahsan |
| `web/**` | Ahsan |
| `report/**` | Ahsan |
| `.github/**` | Ahsan |
| `Dockerfile`, `.dockerignore` | Ahsan |
| `requirements.txt` | Ahsan (central, on request — see below) |
| `contract.py` | Ahsan |
| `CONTRACTS.md` | Ahsan |
| `README.md`, `AGENTS.md`, `CLAUDE.md`, `HANDOFF.md` | Ahsan |
| `docs/stage3/**` | Ahsan, except `docs/stage3/handoffs/<name>.md` |
| `artifacts/**` | Ahsan |
| `endpoint/**` | Rayyan |
| `runner/**` | Rayyan |
| `analysis/**` | Khalid |
| `analysis/policies/**` | Khalid |
| `analysis/case_sets/**` | Khalid |
| `attacks/**` | Lamei |
| `baseline/**` | Lamei |

Component documentation follows its component: `endpoint/README.md` and `runner/README.md`
are Rayyan's, `analysis/README.md` Khalid's, `attacks/INTEGRATION_NOTES.md` Lamei's.

## Tests

| File | Owner |
| --- | --- |
| `tests/test_run_all.py`, `test_web.py`, `test_lab.py`, `test_report.py`, `test_ui_browser.py` | Ahsan |
| `tests/test_stage3_foundation.py` | Ahsan |
| `tests/fixtures/stage3/**` | Ahsan (common fixtures) |
| `tests/test_endpoint.py`, `test_runner.py`, `test_gate.py` | Rayyan |
| `tests/test_analysis*.py`, `test_policy.py`, analysis fixtures | Khalid |
| `tests/test_attacks*.py`, `test_baseline.py` | Lamei |

A shared `conftest.py` or any dependency change goes through Ahsan, so four branches cannot
collide on the same file.

## Handover files — the explicit exception

Each member owns and writes their own:

- `docs/stage3/handoffs/ahsan.md`
- `docs/stage3/handoffs/rayyan.md`
- `docs/stage3/handoffs/khalid.md`
- `docs/stage3/handoffs/lamei.md`

This is a deliberate exception to Ahsan's documentation ownership. Ahsan links them and
does not rewrite them.

## One-time foundation ownership, and where it goes

The foundation task created files in other people's folders, once, under Ahsan's
authorisation. Ownership transfers on the first member commit:

| Created by the foundation | Transfers to |
| --- | --- |
| `endpoint/targets.py`, `endpoint/targets.json` | Rayyan |
| `attacks.metadata.scoped_registry` (in `attacks/metadata.py`) | Lamei |
| `analysis/case_sets/ci_core_v1.json`, `analysis/case_sets/README.md` | Khalid |
| `analysis/policies/ci_core_v1_clean_reference.json` | Khalid |

These are starting points, not approvals of future change. Khalid in particular must
resolve the deliberately-absent manifest and coverage hashes from real artifacts — see
`analysis/case_sets/README.md` — and nothing here auto-approves a later edit to the
approved clean reference.

## Boundaries that are about correctness, not territory

- **No member edits another member's production files to make their own branch pass.**
  Request a contract change; Ahsan lands one amendment; everyone takes the same amendment.
- **Do not implement another member's pending component to unblock an integration.** A
  passing component test over a stub proves nothing about the pipeline.
- Feature branches and PRs only. **Only Ahsan merges to `main`.**
- Ahsan verifies the **exact** handover commit before accepting, and reruns affected checks
  after any later change to it.

## Requesting a change outside your folder

1. Name the exact file, field or signature, and what is blocking you.
2. Say what you propose and what it breaks.
3. Ahsan lands it centrally — `contract.py`, `CONTRACTS.md`, the fixture pack,
   `CONTRACTS_VERSION`, and a dated entry in `docs/stage3/DECISIONS.md`.
4. Everyone rebases onto that amendment.

Never carry a private divergence. Two definitions of one contract is the failure mode this
whole structure exists to prevent.
