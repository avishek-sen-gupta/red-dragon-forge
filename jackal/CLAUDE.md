# Jackal — Agent Instructions

#import .claude/core/project-context.md
#import .claude/core/workflow.md
#import .claude/core/implementation.md
#import .claude/core/tools-search.md
#import .claude/conditional/design-principles.md


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** this repo uses beads' **manual-export** model, NOT Dolt remote sync — `.beads/` (the local Dolt working DB) is fully gitignored, and the forge root's `issues/issues.jsonl` is the tracked git source of truth, regenerated with `bd export -o issues/issues.jsonl` and staged before committing (there is no `bd dolt push`). See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for the underlying sync concepts this repo deliberately opts out of.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

## Build & Commit Process (this repo's conventions)

These override the managed Beads block's defaults where they differ.

### Issue graph is version-controlled — export before committing issue changes
Issues live in the forge's one graph, not a per-package one. Jackal had its own beads DB as a
standalone repo; since the subtree merge there is a single Dolt DB at the forge root, exported
to the tracked `issues/issues.jsonl` there. See the root `CLAUDE.md` for the manual-export
rules — in particular, regenerate and stage the snapshot **before** committing anything that
touches issues:
```bash
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```
Jackal's own roadmap is `docs/jcl-execution-roadmap.md`.

### Building the bridge JARs
The forge root's **`make jar`** (part of `make setup`) builds all Java artefacts — the vendored
red-dragon ProLeap COBOL bridge (parser + bridge) **and** the `jcl-bridge` (ANTLR JCL) JAR — both
gitignored build products. It skips the ProLeap JAR once built; use **`make jar-force`** at the
root after a red-dragon bump or grammar change. Jackal has no Makefile of its own.

### Running tests / committing (the pre-commit hook runs the full suite)
Source the forge root's `bridge-env.sh` so the suite finds both JARs (the pre-commit hook sources
it itself). The CardDemo e2e reads forge's `vendor/carddemo/app` unless `CARDDEMO_HOME` says
otherwise:
```bash
. ../bridge-env.sh
```

**Always invoke tools with `uv run --no-sync`** (e.g. `uv run --no-sync python -m black jackal tests`,
`uv run --no-sync pytest`). `red-dragon` is an **editable path dependency** (`../vendor/red-dragon`);
a plain `uv run` re-checks the lockfile and **rebuilds the large red-dragon editable wheel**
whenever that submodule changed — a multi-second-to-minute stall borne by the first `uv run`
(historically the Black hook). `--no-sync` skips that; red-dragon's Python is still picked up
live via its editable `.pth`. The pre-commit hooks already use `--no-sync`. **Caveat:** after
changing dependencies (pyproject/uv.lock) or on a fresh clone, run `uv sync` (or `make python` at the forge root)
once to refresh the env — the hooks no longer do it for you.
Talisman runs in the hook: for generated/churning files use `.talismanrc` `ignore_detectors: [filecontent]` (like `uv.lock`, the forge root's `issues/issues.jsonl`); for stable files append a by-checksum entry **before** the `version:` line (append-only — never modify existing entries).
