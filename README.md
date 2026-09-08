<p align="center">
  <img src="docs/assets/banner.png" alt="red-dragon-forge — CICS · SQL · JCL" width="100%">
</p>

# red-dragon-forge

**Monorepo for RedDragon's COBOL coprocessor runtimes, the composition layer that wires them
together, and the static analyser that reads the same corpora without running them.**

Each runtime emulates one legacy COBOL execution environment on top of
[RedDragon](https://github.com/avishek-sen-gupta/red-dragon) — a general-purpose
multi-language interpreter, vendored as a submodule and never modified by this repo.

| Package | What it is |
| --- | --- |
| [`cicada/`](cicada/) | The **CICS runtime**: pseudo-conversational transaction dispatch, VSAM KSDS file control, BMS screen handling. |
| [`squall/`](squall/) | The **EXEC SQL coprocessor runtime** for Db2-attached COBOL programs. |
| [`jackal/`](jackal/) | The **JCL/batch execution engine**: job/step orchestration, IDCAMS, generation data groups. |
| [`red_dragon_forge/`](red_dragon_forge/) | The **composition layer** — this repo's own code. |
| [`cobble/`](cobble/) | **Corpus onboarding and knowledge-graph extraction**, analysis only. |

**The composition layer** assembles multiple coprocessor extensions into one compiled,
runnable COBOL program — without any one runtime knowing about the others — via a generic
`CoprocessorSpec` seam (`interpreter.project.coprocessor_compile`, contributed to RedDragon
itself). See
[`docs/design/2026-07-04-cics-sql-composition-design.md`](docs/design/2026-07-04-cics-sql-composition-design.md).

**Cobble** parses and walks the ASG, and never lowers to IR or executes. On top of the
program/file/transaction graph it builds field-level byte dataflow: a source-level CFG,
variable dependency graphs, and a byte-range trace that follows a commarea across LINK
boundaries. Its pipeline runs from `cobble/` as `make parse CONFIG=…` then
`make build CONFIG=…` (TOML configs), or via the `cobble-*` entry points; the parse is the only
stage that starts a JVM, and every stage after it reads the one ASG cache it wrote.

## Quick start

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup      # init submodules + build the ProLeap + JCL bridge JARs + uv sync --all-packages
make test-all   # every package's suite, building the shared JARs exactly once
```

`make test-all` expects a running Db2 for the two suites that talk to one — see
[Tests](#tests).

The CICS end-to-end and fitness-golden paths additionally require the native `hlasm_export`
binary (BMS symbolic-map generation). Build it with a native toolchain (cmake / ninja / clang)
via [`cicada/third-party/che-che4z-lsp-for-hlasm-fork/build.sh`](cicada/third-party/che-che4z-lsp-for-hlasm-fork/build.sh)
(`./build.sh --target hlasm_export`); CI builds it in the `cicada` and `forge` jobs.

## Repository structure

```
red-dragon-forge/
  vendor/red-dragon/       # the ONE shared RedDragon submodule
  cicada/                  # CICS runtime, full history preserved via git subtree
  squall/                  # EXEC SQL runtime, full history preserved via git subtree
  jackal/                  # JCL/batch runtime, full history preserved via git subtree
  cobble/                  # corpus onboarding + knowledge-graph extraction, via git subtree
  red_dragon_forge/        # composition-layer package (this repo's own code)
  tests/                   # root composition + integration suites
  pyproject.toml           # uv workspace root (members: cicada, squall, jackal, cobble)
  Makefile                 # root orchestrator — builds the shared JARs once, runs all suites
  .importlinter            # cross-package independence contract
  .pre-commit-config.yaml  # consolidated hooks (static checks global, test suites per-package)
```

Cicada, Squall, Jackal, and Cobble were originally separate repos, merged in via `git subtree`
with full commit history preserved — `git log --follow -m` on any file inside them still walks
back across the merge boundary. Each keeps its own `CLAUDE.md`, `Makefile`, `pyproject.toml`,
and test suite, and remains fully independently buildable and testable: merging them didn't
couple their release cadences or make them depend on each other. See
[`docs/superpowers/specs/2026-07-05-monorepo-migration-design.md`](docs/superpowers/specs/2026-07-05-monorepo-migration-design.md)
for the migration design and rationale.

### Package independence

A shared root [`.importlinter`](.importlinter) contract enforces the boundaries; run
`uv run lint-imports` to check.

- The three runtimes must not import each other.
- Only `red_dragon_forge/` and `cobble/` may import from more than one of them.
- Cobble is static analysis, so three further contracts hold it to the static surface: it must
  not import the interpreter, nor any runtime (cicada's dispatcher/VSAM/BMS/strategy, jackal's
  runner/catalog/IDCAMS, squall beyond `statements`), and nothing in the workspace may import
  it.

Whole-system graph extraction once lived here as a `knowledge_graph/` package, with per-runtime
extractors inside Cicada and Jackal. It was deleted ahead of folding cobble in — cobble was a
VM-free successor, not a lagging copy, so the stack arrived with cobble rather than being merged
into its own ancestor, and has since grown the byte-level dataflow work above. See
[`docs/superpowers/specs/2026-09-01-delete-stale-graph-stack-design.md`](docs/superpowers/specs/2026-09-01-delete-stale-graph-stack-design.md).

## Tests

Each package is independently testable from its own directory:

```bash
cd cicada && make test    # unit + integration + CardDemo e2e
cd squall && make test    # needs SQUALL_DB2_DSN + a running Db2 (make db2-up)
cd jackal && make test
cd cobble && make test    # no JVM, no Db2 — static analysis only
```

`make test-all` from the repo root runs every one of those plus `red-dragon-forge`'s own
composition-layer suite (`make test`), building the shared ProLeap + JCL bridge JARs exactly
once regardless of how many packages need them. The composition-layer suite needs the same
`SQUALL_DB2_DSN` as Squall for its one live-Db2 end-to-end test.

> **Db2 on a small VM fails in a way that doesn't look like a memory problem** — the container
> stays up and healthy while `db2sysc` is OOM-killed underneath it, surfacing as `SQL30081N`.
> Give the container VM 6 GiB or more and cap `INSTANCE_MEMORY`:
> [`docs/db2-container-memory.md`](docs/db2-container-memory.md).

## Issue tracking

Uses [Beads](https://github.com/gastownhall/beads) (`bd`). `.beads/` (the local Dolt working
DB) is gitignored; `issues/issues.jsonl` is the tracked git source of truth. See `CLAUDE.md`
for the full convention.
