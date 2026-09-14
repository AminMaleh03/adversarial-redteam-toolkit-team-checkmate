# Member handovers

One file per member, written and owned by that member:

- `ahsan.md` · `rayyan.md` · `khalid.md` · `lamei.md`

This is an explicit exception to Ahsan's ownership of `docs/stage3/`. Ahsan links these and
does not rewrite them.

Each handover states, at minimum:

- branch name and the exact head SHA being handed over;
- files changed, within your own ownership boundary;
- the exact commands you ran and their real output, including failures and skips — say
  which tests were skipped and why;
- which evidence is from a **real run** and which is from **fixtures**; a fixture-rendered
  page is not a completed demonstration;
- example artifact paths and their hashes;
- what still needs integration, and any check you could not run.

Ahsan accepts the exact commit named here, and reruns affected checks after any later
change to it. If something is unfinished, say so plainly — a handover that overstates what
works costs more to unwind than it saves.
