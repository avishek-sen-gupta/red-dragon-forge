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
| [`cicada/`](cicada/) | The **CICS runtime**: pseudo-conversational transaction dispatch, VSAM KSDS file control, BMS screen handling, and a TN3270 server (`cicada-tn3270`) for stock 3270 emulators. |
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
boundaries. Its pipeline runs from `cobble/` as the `cobble-*` entry points
(`uv run cobble-parse-corpus --config …` then `uv run cobble-build --config …`, TOML configs,
after `. ../bridge-env.sh`); the parse is the only stage that starts a JVM, and every stage after it reads the one ASG cache it wrote.

Each package was originally its own repository, merged in via `git subtree` with full history,
and each stays independently buildable and testable. What may import what is enforced by a root
[`.importlinter`](.importlinter) contract and recorded in
[`docs/design/2026-09-09-package-boundaries.md`](docs/design/2026-09-09-package-boundaries.md).

How the field dataflow works, for engineers new to it: [`docs/explainers/`](docs/explainers/index.html).

## Quick start

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup      # init submodules + build hlasm_export + the ProLeap + JCL bridge JARs + uv sync --all-packages
make test-all   # every package's suite, building the shared JARs exactly once
```

`make test-all` expects a running Db2 for the two suites that talk to one — see
[Tests](#tests).

`make setup` builds the native `hlasm_export` binary (BMS symbolic-map generation) too, so it
needs CMake, Ninja and a C++ toolchain, and names whichever is missing; `make hlasm` builds it
alone. `. ./bridge-env.sh` exports `PROLEAP_BRIDGE_JAR`/`JCL_BRIDGE_JAR` for running a tool by
hand.

## Running CardDemo

Two servers, because CardDemo ships two source trees. Everything below is verified, not
inferred — if a command here does not work, that is a bug in this section.

### The plain server (VSAM options)

```bash
. ./carddemo-env.sh          # FORGE_ROOT + CARDDEMO_HOME + the bridge JARs
uv run cicada-tn3270 --config cicada/config/carddemo-tn3270.toml --port 3270
c3270 -model 3279-2-E localhost:3270
```

### The Db2 server (adds admin 5 and 6)

Preparing the database and serving it are **separate commands**: `make db2-seed` is the only
thing that ever issues `DROP TABLE`, so a routine server start can never destroy your tables.

```bash
make db2-status              # 0 = up, 1 = dead, 2 = DSN unset
. ./carddemo-env.sh
. tests/integration/db2_env.sh
make db2-seed                # once — drops, recreates from the vendored DDL, reseeds
uv run carddemo-db2-cli --config cicada/config/carddemo-db2-tn3270.toml --port 3271
c3270 -model 3279-2-E localhost:3271
```

Re-run `make db2-seed` whenever you want the world reset; the server never resets it for you.
The VSAM options reset themselves on every start regardless — they seed a *copy* into a temp
directory, so the vendored EBCDIC data is never touched.

**Use a `3279` model with `-E`.** Colour is carried by the extended data stream, and the server
only emits colour attributes when the terminal negotiates a name ending in `-E`
(`cics/tn3270/negotiation.py`'s `TerminalType.extended`). A `3278` is a monochrome terminal, so
`-model 3278-2` gives you correct — but entirely green — screens.

Startup compiles every program in the config through the ProLeap bridge, which takes about a
minute and names each program as it goes. The server is ready when it logs `serving … on …`.

### Signing on

`ADMIN001` / `PASSWORD` reaches the admin menu; any other user gets the main menu only.

| Menu | Option | Program | Works? |
|---|---|---|---|
| Main | `01`–`08`, `10` | various | yes |
| Main | `09` | `CORPT00C` | **no** — needs JCL job submission behind the JOBS TDQ, which no server here drives. Not in either config's `[transactions]`. |
| Main | `11` | `COPAUS0C` | **no** — no source ships. Degrades gracefully: COMEN01C guards this one XCTL with `EXEC CICS INQUIRE PROGRAM`. |
| Admin | `1`–`4` | `COUSR00C`/`01C`/`02C`/`03C` | yes — user list / add / update / delete, VSAM-backed |
| Admin | `5` | `COTRTLIC` | Db2 server only — transaction type list/update |
| Admin | `6` | `COTRTUPC` | Db2 server only — transaction type maintenance |

**Selecting an unwired option drops the connection.** That is `forge-6jj` (open, P1): an XCTL to
a program the region never compiled correctly abends `PGMI` internally, but the result still
reaches the driver marked `XCTL`, so it steps a terminated region and raises
`RuntimeError: step() called on a region that has terminated` instead of painting the abend.
Option `09` is the reachable route on both servers; admin `5`/`6` is the route on the plain one.
Option `11` is the only unwired option that fails gracefully, because it is the only one guarded.

## Tests

Each package is independently testable from its own directory:

```bash
. ./bridge-env.sh
(cd cicada && uv run --no-sync python -m pytest)   # unit + integration + CardDemo e2e
(cd squall && . db2/dsn-env.sh && uv run --no-sync python -m pytest)   # needs a running Db2 (make db2-up)
(cd jackal && uv run --no-sync python -m pytest)
cd cobble && uv run pytest    # no JVM, no Db2 — static analysis only
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
