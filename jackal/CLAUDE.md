# RedDragon — Agent Instructions

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

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

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
This repo does **not** use Dolt remote sync or `.beads/issues.jsonl`. Instead:
- `.beads/` (Dolt working DB) is **gitignored**.
- `beads/issues.jsonl` (note: no leading dot) is the **tracked** snapshot — the git source of truth for the issue graph (issues + all dependency edges).

**Whenever a change touches issues (create/update/close/dep edits), regenerate and stage the snapshot BEFORE committing** — this is a deliberate manual step, NOT a git hook:
```bash
bd export -o beads/issues.jsonl && git add beads/issues.jsonl
```
On a fresh clone, `bd import beads/issues.jsonl` rebuilds the local DB. See `beads/README.md`
and the roadmap `docs/jcl-execution-roadmap.md`.

### Building the bridge JARs
**`make jar`** builds all Java artefacts — the vendored red-dragon ProLeap COBOL bridge
(parser + bridge) **and** the `jcl-bridge` (ANTLR JCL) JAR — both gitignored build products.
It's mtime-gated (skips if built); use **`make jar-force`** after a red-dragon bump or grammar
change. `make build` (= `./build.sh`) force-rebuilds both + runs `uv sync`. (`make jar` is the
uniform entry point across cicada/jackal/squall.)

### Running tests / committing (the pre-commit hook runs the full suite)
Export these so the suite + gated e2e pass (the pre-commit hook needs them too):
```bash
export PROLEAP_BRIDGE_JAR="$(pwd)/../vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
export JCL_BRIDGE_JAR="$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar"
export CARDDEMO_HOME="$HOME/code/aws-mainframe-carddemo/app"
```

**Always invoke tools with `uv run --no-sync`** (e.g. `uv run --no-sync python -m black jackal tests`,
`uv run --no-sync pytest`). `red-dragon` is an **editable path dependency** (`../vendor/red-dragon`);
a plain `uv run` re-checks the lockfile and **rebuilds the large red-dragon editable wheel**
whenever that submodule changed — a multi-second-to-minute stall borne by the first `uv run`
(historically the Black hook). `--no-sync` skips that; red-dragon's Python is still picked up
live via its editable `.pth`. The pre-commit hooks already use `--no-sync`. **Caveat:** after
changing dependencies (pyproject/uv.lock) or on a fresh clone, run `uv sync` (or `./build.sh`)
once to refresh the env — the hooks no longer do it for you.
Talisman runs in the hook: for generated/churning files use `.talismanrc` `ignore_detectors: [filecontent]` (like `uv.lock`, `beads/issues.jsonl`); for stable files append a by-checksum entry **before** the `version:` line (append-only — never modify existing entries).
