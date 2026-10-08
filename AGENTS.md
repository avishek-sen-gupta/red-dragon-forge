# Agent Instructions

Read `CLAUDE.md` and every file under `guidelines/` that it lists. They are the rules for this
repository; this file adds nothing to them except the quick reference below.

Documentation for people starts at `docs/README.md`.

## Issue tracking

Issues are tracked with `bd` (beads). The setup, the manual-export model and the fresh-clone
steps are in `guidelines/project/workflow.md`, section "Issue tracking".

```bash
bd ready                  # find available work
bd show <id>              # view an issue
bd update <id> --claim    # claim it
bd close <id>             # complete it
bd export -o issues/issues.jsonl && git add issues/issues.jsonl   # before committing issue changes
```

## Non-interactive shell commands

`cp`, `mv` and `rm` may be aliased to prompt. Use `cp -f`, `mv -f`, `rm -f`, `rm -rf`. Use
`-o BatchMode=yes` with `ssh`/`scp`.
