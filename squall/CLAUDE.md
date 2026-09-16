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

Built only from the forge root; squall has no Makefile.

```bash
make setup      # at the forge root: both bridge JARs + hlasm_export + uv sync
make jar-force  # at the forge root, after a red-dragon bump
. ./bridge-env.sh && cd squall
```

## Db2 test harness

Most of the integration suite (`tests/integration/test_db2_*`) and the `Db2Backend` unit
tests (`tests/unit/test_backend.py`) connect to a **live Db2** via
`ibm_db.connect(os.environ["SQUALL_DB2_DSN"], …)`. There is **no skip** — without a
reachable Db2 they **fail loud**. Stand one up locally with the Docker harness:

```bash
cp .env.example .env          # then edit .env: set DB2_PASSWORD (e.g. squalltest123)
make -C .. db2-up             # forge root target: docker compose up -d db2; waits until healthy
                              #   (first init is slow — minutes, much slower under
                              #    Apple-Silicon emulation; the container is reused after)
```

The DSNs are built by `db2/dsn-env.sh` from `.env`. Source it before running tests directly
(it exports `SQUALL_DB2_DSN` for `MOJO` and `SQUALL_DB2_DSN2` for the second database
`MOJO2`; it also requires `PROLEAP_BRIDGE_JAR` to be set):

```bash
. db2/dsn-env.sh
```

The DSN shape (password comes from `.env`/CI secret, never committed):

```
DATABASE=MOJO;HOSTNAME=localhost;PORT=50000;PROTOCOL=TCPIP;UID=db2inst1;PWD=<DB2_PASSWORD>
```

The forge root's `make test-all` sources it for squall's suite. (The forge root also carries a
sibling `tests/integration/db2_env.sh` for composed Cicada+Squall runs.) Harness lifecycle, all
forge root targets: `make db2-up` (idempotent), `make db2-restart` (rebind the TCP listener
without re-init), `make db2-stop` (keep container), `make db2-clean` (full reset, drops the
volume).

## Tests

```bash
uv run --no-sync python -m pytest                          # full suite (after . ../bridge-env.sh && . db2/dsn-env.sh)
uv run --no-sync python -m pytest tests/unit/ -x -q        # unit tests; mostly a fake backend, but test_backend.py needs live Db2
uv run --no-sync python -m pytest tests/integration/ -x -q # integration (real VM); test_db2_* need live Db2, all need the ProLeap JAR
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
  isolation); integration tests exercise real VM execution — the `test_db2_*` suite against a
  live Db2, other e2e tests against SQLite.
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

## Package layout

```
squall/
  strategy.py        # SqlLoweringStrategy — the SQL RedDragonExtensionLoweringStrategy injected into
                     #   CobolFrontend; also registers the __cics_task_end_hook session-reset builtin
                     #   (reset_session_fn) for the composed-with-Cicada case
  preprocess.py      # EXEC SQL / DCLGEN / INCLUDE preprocessing over the source
  parser/            # EXEC SQL parsing: grammar.lark + _grammar.py (Lark), parse.py, sql_model.py
  statements.py      # parsed statement value types
  coprocessor.py     # coprocessor entry point / wiring
  binding.py         # generic host-variable binding engine (field <-> param, INTO mapping,
                     #   SQLCODE/SQLCA) — dialect/backend-agnostic, reads/writes via data_layout
  connector.py       # connection/session management
  dclgen.py          # DCLGEN → copybook / host-structure handling
  copybooks/         # bundled copybooks (SQLCA.cpy, ACCTREC.cpy)
  backend.py         # SqlBackend protocol: execute(sql, params) -> rows / rowcount / sqlcode
  backends/
    sqlite.py        # SqliteBackend — zero-dependency backend (owns placeholder style + dialect)
    db2.py           # Db2Backend — real IBM Db2 via ibm-db; primary integration-test target
  builtins/
    exec_sql.py      # SQL service builtins (CallFunction targets): __exec_sql, cursor ops, session reset
```

RedDragon contributes the SQL seam (**built and in use**):
- bridge `serializeExecSql` — serializes the (already-parsed) `ExecSqlStatement` opaque text
- a generic `RedDragonExtensionLoweringStrategy` protocol + a strategy **registry** keyed by EXEC kind
  (CICS / SQL / SQLIMS), replacing the single hardwired `exec_cics_strategy` hook
- an `ExecSqlStatement` node + frontend dispatch

The integration tests run the real VM through this seam.
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
