# Cicada — Agent Instructions

## Project

Cicada is the **CICS runtime** for the RedDragon multi-language interpreter. It runs real,
unmodified COBOL programs end-to-end through a CICS emulation layer — pseudo-conversational
transaction dispatch, VSAM KSDS file control, BMS screen handling — without modifying
RedDragon's core VM.

RedDragon lives at `vendor/red-dragon` as an editable submodule (`pip install -e`).
The top-level package is `cics/`.

## Setup

```bash
git clone --recurse-submodules <repo>
cd cicada
uv sync
# COBOL bridge (JDK 17+ and Maven required):
cd vendor/red-dragon/proleap-bridge && ./build.sh && cd -
```

## Tests

```bash
uv run python -m pytest tests/unit/ -x -q        # unit tests (no JAR required)
uv run python -m pytest tests/integration/ -x -q # integration tests (needs ProLeap JAR)
```

## Key invariant

**No edits to RedDragon's core engine** (`interpreter/vm/**`, `ir.py`, `run.py`, `executor.py`,
`cfg.py`). Every CICS behaviour reaches the VM only through `CallFunction` IR to registered
builtins — the same mechanism any language frontend uses.

## RedDragon changes live in `~/code/red-dragon`, not the submodule

`vendor/red-dragon` is a **read-through checkout** for building and running Cicada — do **not**
make RedDragon changes there. The canonical RedDragon working copy (and its own Beads DB) is
the separate clone at `~/code/red-dragon`.

- **RedDragon code fixes**: edit, test, and commit/push in `~/code/red-dragon`. Then bump
  Cicada's submodule pointer (`cd vendor/red-dragon && git fetch && git checkout <sha>`, then
  `git add vendor/red-dragon` in the Cicada repo) to pick up the new commit.
- **RedDragon issues**: file/update in RedDragon's Beads DB, not Cicada's
  (`bd -C ~/code/red-dragon create …`, or `cd ~/code/red-dragon` first). Anything in
  `interpreter/**`, `proleap-bridge/**`, the PIC parser, edit pictures, lowering, or the VM is
  a RedDragon issue. Only CICS-runtime concerns (the `cics/` package) belong in Cicada's Beads DB.

## Workflow

- Write failing test first (TDD).
- Unit tests go in `tests/unit/`, integration tests in `tests/integration/`.
- Integration tests exercise real VM execution via `run_cics` / `CicsRegion`, not just IR generation.
- Run the full test suite before committing: `uv run python -m pytest tests/ -x -q`.
- Format: `uv run python -m black .`

## Package layout

```
cics/
  strategy.py          # CicsLoweringStrategy — injected into CobolFrontend
  preprocessor.py      # apply_cics_prepass (inject_dfheiblk)
  dfhresp_prepass.py   # DFHRESP ASG pre-pass
  dispatcher.py        # CicsRegion, run_cics, _advance_routing
  bootstrap.py         # compile_cics_program, run_carddemo_region
  types.py             # CicsContext, DispatchResult, DispatchKind
  terminal.py          # ScreenChannel / InputChannel protocols
  le_stubs.py          # IBM LE service stubs (CEEDAYS, etc.)
  builtins/            # CICS service builtins: flow, screen, system, vsam
  vsam/                # VsamEngine, backends, flat-file codec, dump CLI
  bms/                 # BMS symbolic map generation (bms-tools pipeline)
```

RedDragon contributes:
- `interpreter/cobol/cics_parser.py` — Lark EXEC CICS grammar (`CicsOperand`, `parse_exec_cics_text`)
- `interpreter/cobol/exec_cics_strategy.py` — `ExecCicsStrategy` protocol + `CatchAllLoweringStrategy`


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
