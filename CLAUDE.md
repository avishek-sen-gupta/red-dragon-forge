# Squall — Agent Instructions

## Project

Squall is the **EXEC SQL coprocessor runtime** for the RedDragon multi-language
interpreter. It runs real, unmodified COBOL programs that contain embedded static SQL
(`EXEC SQL … END-EXEC`, Db2-style) — `SELECT … INTO`, `INSERT`/`UPDATE`/`DELETE`,
cursors, `COMMIT`/`ROLLBACK`, `SQLCODE`/`SQLCA`, host variables — against a **pluggable
database backend** (SQLite first), without modifying RedDragon's core VM.

Squall is a **peer of Cicada** (the CICS runtime), not a dependent of it. EXEC SQL is a
*coprocessor extension*, not part of the COBOL language and not a CICS facility — the same
tier as EXEC CICS, handled historically by the Db2 precompiler. Squall therefore:

- **runs standalone** — a plain COBOL VM with the SQL strategy injected, zero CICS; the
  shape a batch program under JCL would use;
- **composes with Cicada** — for CICS + Db2 programs (e.g. CBSA), Cicada submodules Squall
  and both the CICS and SQL strategies are wired into the same `CobolFrontend`.

Unlike CICS, **EXEC SQL imposes no higher-level execution semantics**: every statement is a
synchronous call (the precompiler rewrites it to `CALL 'DSNHLI'`). Squall is therefore
**passive** — lowering strategy + binding engine + builtins + backend, with **no runtime
driver** (no region, no dispatcher, no suspend/resume). It is invoked via `CallFunction`
during whatever execution context is already running and returns synchronously.

RedDragon lives at `vendor/red-dragon` as an editable submodule (`pip install -e`).
The top-level package is `squall/`.

## Core engineering tenets

These are non-negotiable, alongside the invariants below.

1. **TDD.** Write the failing test first, watch it fail, then implement the minimal code to
   pass. No production code without a test that drove it. The parser has a per-directive test
   matrix + a che4z cross-check oracle; the binding engine is tested against a fake backend
   before any DB.
2. **Functional-programming style.** The core is **pure functions over data**: parsing/host-var
   extraction, the clean-query rewrite, and the byte codec take values in and return values out,
   with **no side effects** and no hidden global mutable state. Side effects are pushed to the
   edges and isolated — the only effectful boundaries are the VM memory region (writes go through
   the binding engine) and the DB connection (behind `SqlBackend`). Prefer expressions,
   comprehensions, and composition over imperative mutation. Enforced by `python_fp_lint` (the
   same FP linter RedDragon/cicada use) in the pre-commit hook.
3. **Immutability.** All value types are **frozen dataclasses** (`ParsedSql`, `SqlResult`, the
   parse-tree-derived structures, config). Prefer tuples over lists for fixed sequences. Never
   mutate inputs or shared state; produce new values. The mutable VM region and DB connection are
   the *only* mutable state, owned by their boundary modules (binding engine / backend) and never
   leaked.

## Setup

```bash
git clone --recurse-submodules <repo>
cd squall
uv sync
# All Java artefacts — ProLeap parser + bridge (JDK 17+ and Maven required):
make jar      # or `make jar-force` after a red-dragon bump
```

## Tests

```bash
uv run --no-sync python -m pytest tests/unit/ -x -q        # unit tests (binding engine vs a fake backend; no JAR)
uv run --no-sync python -m pytest tests/integration/ -x -q # integration tests (real VM + SQLite; needs ProLeap JAR)
```

Quality gates (pre-commit, mirroring RedDragon/cicada/jackal): `black` (format), **`python_fp_lint`**
(enforces the FP tenet), `pyright` (types), **`import-linter`** (architectural contracts, see
`.importlinter`), and the test suite.

## Key invariants

1. **No edits to RedDragon's core engine** (`interpreter/vm/**`, `ir.py`, `run.py`,
   `executor.py`, `cfg.py`). Every SQL behaviour reaches the VM only through `CallFunction`
   IR to registered builtins — the same mechanism any language frontend uses.
2. **No dependency on Cicada / CICS.** Squall must run a plain batch COBOL + SQL program
   with no CICS present. `squall/` must not import `cics`, and `cics` must not import
   `squall`; they compose only at application wiring time (the strategy registry).
3. **The binding engine is dialect- and backend-agnostic.** It handles only the embedded
   *envelope* — host variables (`:VAR`), the `INTO` target list, `SQLCODE`/`SQLCA`. The
   actual query is opaque text handed to the backend; dialect and placeholder style live
   entirely inside the backend.

## RedDragon changes live in `~/code/red-dragon`, not the submodule

`vendor/red-dragon` is a **read-through checkout** for building and running Squall — do
**not** make RedDragon changes there. The canonical RedDragon working copy (and its own
Beads DB) is the separate clone at `~/code/red-dragon`.

- **RedDragon code fixes**: edit, test, and commit/push in `~/code/red-dragon`. Then bump
  Squall's submodule pointer (`cd vendor/red-dragon && git fetch && git checkout <sha>`,
  then `git add vendor/red-dragon` in the Squall repo) to pick up the new commit.
- **RedDragon issues**: file/update in RedDragon's Beads DB, not Squall's. The SQL seam
  in RedDragon (the generic `RedDragonExtensionLoweringStrategy` protocol + strategy registry, the
  `ExecSqlStatement` node, the bridge `serializeExecSql`) is **RedDragon** work. Only the
  SQL-runtime concerns (the `squall/` package — binding engine, builtins, backends) belong
  in Squall's Beads DB.
- **Single RedDragon pin**: when Squall is composed under Cicada, both repos submodule
  RedDragon. Keep them pinned to **one** RedDragon commit — do not let two divergent
  RedDragon checkouts coexist in a composed environment.

## Workflow

- Write failing test first (TDD).
- Unit tests go in `tests/unit/`, integration tests in `tests/integration/`.
- Unit-test the binding engine against a **fake backend** (proves the generic layer in
  isolation); integration tests exercise real VM execution against the SQLite backend.
- Run the full test suite before committing: `uv run --no-sync python -m pytest tests/ -x -q`.
- Format: `uv run --no-sync python -m black squall tests`

## Build & Commit Process (this repo's conventions)

**Always invoke tools with `uv run --no-sync`** (pytest, black, lint-imports). `red-dragon` is
an **editable path dependency** (`vendor/red-dragon`); a plain `uv run` re-checks the lockfile
and **rebuilds the large red-dragon editable wheel** whenever that submodule changed — a stall
borne by the first `uv run` (historically the Black pre-commit hook). `--no-sync` skips that;
red-dragon's Python is still picked up live via its editable `.pth`. The pre-commit hooks
already use `--no-sync`. **Caveat:** after changing dependencies or on a fresh clone, run
`uv sync` once — the hooks no longer do it for you.

**Issue graph is version-controlled (manual-export model, not beads' Dolt sync).** `.beads/`
(Dolt working DB) is **gitignored**; `beads/issues.jsonl` (no leading dot) is the **tracked**
git source of truth. **Whenever a change touches issues, regenerate and stage the snapshot
BEFORE committing** — a deliberate manual step, NOT a git hook:
```bash
bd export -o beads/issues.jsonl && git add beads/issues.jsonl
```
`core.hooksPath` is the default `.git/hooks` (the pre-commit framework + the globally-seeded
Talisman `pre-commit.legacy` run there). On a fresh clone, `bd import beads/issues.jsonl`
rebuilds the local DB. See `beads/README.md`.

## Package layout (intended)

```
squall/
  strategy.py        # SqlLoweringStrategy — the SQL RedDragonExtensionLoweringStrategy injected into CobolFrontend
  parser.py          # EXEC SQL text analysis: host-var (:VAR) extraction, INTO stripping
  binding.py         # generic host-variable binding engine (field <-> param, INTO mapping,
                     #   SQLCODE/SQLCA) — dialect/backend-agnostic, reads/writes via data_layout
  backend.py         # SqlBackend protocol: execute(sql, params) -> rows / rowcount / sqlcode
  backends/
    sqlite.py        # SqliteBackend — first concrete backend (owns placeholder style + dialect)
  builtins/          # SQL service builtins (CallFunction targets): __exec_sql, cursor ops
```

RedDragon contributes (the SQL seam — to be built):
- bridge `serializeExecSql` — serialize the (already-parsed) `ExecSqlStatement` opaque text
- a generic `RedDragonExtensionLoweringStrategy` protocol + a strategy **registry** keyed by EXEC kind
  (CICS / SQL / SQLIMS), replacing the single hardwired `exec_cics_strategy` hook
- an `ExecSqlStatement` node + frontend dispatch

See `docs/design/2026-06-13-exec-sql-support-design.md` for the full design.

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
