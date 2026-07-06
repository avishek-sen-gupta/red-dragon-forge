# red-dragon-forge

**Monorepo for RedDragon's COBOL coprocessor runtimes, and the composition layer that wires
them together.**

Three independent coprocessor runtimes, each emulating one legacy COBOL execution
environment on top of [RedDragon](https://github.com/avishek-sen-gupta/red-dragon) (a
general-purpose multi-language interpreter, vendored separately, never modified by this repo):

- **[`cicada/`](cicada/)** — the CICS runtime: pseudo-conversational transaction dispatch,
  VSAM KSDS file control, BMS screen handling.
- **[`squall/`](squall/)** — the EXEC SQL coprocessor runtime (Db2-attached COBOL programs).
- **[`jackal/`](jackal/)** — the JCL/batch execution engine (job/step orchestration, IDCAMS,
  generation data groups).
- **[`red_dragon_forge/`](red_dragon_forge/)** — the composition layer. Assembles multiple
  coprocessor extensions into one compiled, runnable COBOL program — without any one runtime
  knowing about the others — via a generic `CoprocessorSpec` seam
  (`interpreter.project.coprocessor_compile`, contributed to RedDragon itself). See
  [`docs/design/2026-07-04-cics-sql-composition-design.md`](docs/design/2026-07-04-cics-sql-composition-design.md)
  for the composition design.

## Repository structure

Cicada, Squall, and Jackal were originally three separate repos, merged into this one via
`git subtree` (full commit history preserved — `git log --follow -m` on any file inside them
still walks back across the merge boundary). Each keeps its own `CLAUDE.md`, `Makefile`,
`pyproject.toml`, and test suite, and remains fully independently buildable and testable —
merging them didn't couple their release cadences or make them depend on each other.
Cross-package imports are enforced against by a shared root
[`.importlinter`](.importlinter) contract; only `red_dragon_forge/` is allowed to import
from more than one of them. See
[`docs/superpowers/specs/2026-07-05-monorepo-migration-design.md`](docs/superpowers/specs/2026-07-05-monorepo-migration-design.md)
for the full migration design and rationale.

```
red-dragon-forge/
  vendor/red-dragon/       # the ONE shared RedDragon submodule
  cicada/                  # CICS runtime, full history preserved via git subtree
  squall/                  # EXEC SQL runtime, full history preserved via git subtree
  jackal/                  # JCL/batch runtime, full history preserved via git subtree
  red_dragon_forge/        # composition-layer package (this repo's own code)
  pyproject.toml           # uv workspace root (members: cicada, squall, jackal)
  Makefile                 # root orchestrator — builds the shared JAR once, runs all suites
  .importlinter            # cross-package independence contract
  .pre-commit-config.yaml  # consolidated hooks (static checks global, test suites per-package)
```

## Setup

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup   # init submodules + build the shared ProLeap bridge JAR + uv sync --all-packages
```

## Tests

Each package is independently testable from its own directory:

```bash
cd cicada && make test    # 348 tests — unit + integration + CardDemo e2e
cd squall && make test    # 271 tests + 1 skipped — needs SQUALL_DB2_DSN + a running Db2 (make db2-up)
cd jackal && make test    # 127 tests
```

Or run every package's suite in one pass from the repo root, building the shared ProLeap
bridge JAR exactly once regardless of how many packages need it:

```bash
make test-all
```

`red-dragon-forge`'s own composition-layer tests (`make test`, run from the repo root) need
the same `SQUALL_DB2_DSN` as Squall for their one live-Db2 end-to-end test.

## Issue tracking

Uses [Beads](https://github.com/gastownhall/beads) (`bd`). `.beads/` (the local Dolt working
DB) is gitignored; `issues/issues.jsonl` is the tracked git source of truth. See `CLAUDE.md`
for the full convention.
