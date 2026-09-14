# CLAUDE.md — Team Checkmate

@AGENTS.md

Before doing any project work, read [HANDOFF.md](HANDOFF.md). These instructions apply to every
team member's Claude Code session.

`AGENTS.md` is the shared rulebook for Claude Code and Codex. It contains the ownership table,
contracts, architecture, settled decisions, environment constraints, and handoff procedure.
The former rules in this file were moved there, including the pending manifest requirement.

Keep durable rule changes in `AGENTS.md` and changing task state in `HANDOFF.md`. Do not maintain
a second copy here or rely on private Claude memory as the only record of project decisions.

For Stage 3, also read [CONTRACTS.md](CONTRACTS.md) (version 3.0.0 — the frozen shapes,
signatures and CLI flags), [docs/stage3/FINAL_PLAN.md](docs/stage3/FINAL_PLAN.md) (the
reviewed plan, whose corrections supersede any earlier proposal), your own task file under
[docs/stage3/tasks/](docs/stage3/tasks/), and
[docs/stage3/FOUNDATION_READINESS.md](docs/stage3/FOUNDATION_READINESS.md) for what is
actually verified. Ownership changed: `runner/` is Rayyan's, `baseline/` is Lamei's,
`run_all.py` and `web/` are Ahsan's, and there is no dependency on Amin — see
[docs/stage3/OWNERSHIP.md](docs/stage3/OWNERSHIP.md). Working fixtures for every shape are
in `tests/fixtures/stage3/`; they demonstrate contracts, never that a feature works.

Checkpoint as work progresses and before ending a turn, following the shared procedure. When
resuming after a limit or switching from Codex, read both files again and inspect Git status
and diffs before continuing. Follow the user's latest scope and recorded cancellations.
