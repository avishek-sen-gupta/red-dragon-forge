# Cicada — Agent Instructions

## Project

Cicada is the **CICS runtime** for the RedDragon multi-language interpreter. It runs real,
unmodified COBOL programs end-to-end through a CICS emulation layer — pseudo-conversational
transaction dispatch, VSAM KSDS file control, BMS screen handling — without modifying
RedDragon's core VM.

RedDragon lives at `vendor/red-dragon` as an editable submodule (`pip install -e`).
The top-level package is `cics/`.

## Setup

Built only from the forge root; cicada has no Makefile.

```bash
make setup      # at the forge root: hlasm_export + both bridge JARs + uv sync
make jar-force  # at the forge root, after a red-dragon bump
. ./bridge-env.sh && cd cicada
```

## Tests

```bash
uv run --no-sync python -m pytest                          # full suite (after . ../bridge-env.sh)
uv run --no-sync python -m pytest tests/unit/ -x -q        # unit tests (no JAR required)
uv run --no-sync python -m pytest tests/integration/ -x -q # integration tests (needs ProLeap JAR)
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
- Run the full test suite before committing: `uv run --no-sync python -m pytest tests/ -x -q`.
- Format: `uv run --no-sync python -m black cics tests`

## Build & Commit Process (this repo's conventions)

**Always invoke tools with `uv run --no-sync`** (pytest, black, lint-imports). `red-dragon` is
an **editable path dependency** (`vendor/red-dragon`); a plain `uv run` re-checks the lockfile
and **rebuilds the large red-dragon editable wheel** whenever that submodule changed — a stall
borne by the first `uv run` (historically the Black pre-commit hook). `--no-sync` skips that;
red-dragon's Python is still picked up live via its editable `.pth`. The pre-commit hooks
already use `--no-sync`. **Caveat:** after changing dependencies or on a fresh clone, run
`uv sync` (or the relevant `make` target) once — the hooks no longer do it for you.

**Issues live in the forge's one graph, not a per-package one.** Cicada had its own beads DB
as a standalone repo; since the subtree merge there is a single Dolt DB at the forge root,
exported to the tracked `issues/issues.jsonl` there. See the root `CLAUDE.md` for the
manual-export rules — in particular, regenerate and stage the snapshot **before** committing
anything that touches issues:
```bash
bd export -o issues/issues.jsonl && git add issues/issues.jsonl
```

## Package layout

```
cics/
  strategy.py          # CicsLoweringStrategy (RedDragonExtensionLoweringStrategy impl)
  coprocessor.py       # build_cics_spec — wraps the strategy as a CoprocessorSpec
  statements.py        # ExecCicsStatement + CicsDialectParser (DialectParser impl)
  cics_visitor.py      # ANTLR visitor: parse_exec_cics_text
  cics_parser.py       # thin re-export of parse_exec_cics_text / CicsOperand
  cics_grammar/        # ANTLR4 EXEC CICS grammar + generated parser
  preprocessor.py      # apply_cics_prepass (inject_dfheiblk)
  dfhresp_prepass.py   # DFHRESP ASG pre-pass
  dispatcher.py        # CicsRegion, run_cics, _advance_routing
  vm_init.py           # make_cics_initial_vm, make_entry_point
  csd_parse.py         # parse_csd, parse_csd_files (transid→program, file→DSNAME)
  bootstrap.py         # compile_cics_program, run_carddemo_region
  conversational.py    # pseudo-conversational suspend/resume driver
  types.py             # CicsContext, DispatchResult, DispatchKind
  terminal.py          # ScreenChannel / InputChannel protocols
  le_stubs.py          # IBM LE service stubs (CEEDAYS, etc.)
  builtins/            # CICS service builtins: flow, screen, system, vsam
  vsam/                # VsamEngine (CICS adapter over shared drivers), eibresp, seed, format, dump CLI
  bms/                 # BMS symbolic-copybook generation (hlasm_export → bms_copybook_gen; macros/ syslib)
```

The EXEC CICS grammar is **ANTLR4** (`cics/cics_grammar/CICSzLexer.g4` + `CICSzParser.g4`, with
generated `CICSzParser.py`) — not Lark. `ExecCicsStatement`, `CicsOperand`, and the
`CicsDialectParser` all live in cicada now; RedDragon has zero CICS-specific type names.

RedDragon contributes only generic, dialect-agnostic seams:
- `interpreter/frontend_extension_lowering.py` — `RedDragonExtensionLoweringStrategy` protocol
- `interpreter/frontend_extension.py` — `DialectParser` protocol (+ `NullDialectParser`)
- `interpreter/project/coprocessor_compile.py` — `CoprocessorSpec` / `compile_program`, which
  calls `compile_cobol(extension_strategies=[…], dialect_parsers=[…])`


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
