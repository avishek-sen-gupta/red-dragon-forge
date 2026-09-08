<p align="center">
  <img src="docs/assets/banner.png" alt="red-dragon-forge — CICS · SQL · JCL" width="100%">
</p>

# red-dragon-forge

**Monorepo for RedDragon's COBOL coprocessor runtimes, and the composition layer that wires
them together.**

Three independent coprocessor runtimes, each emulating one legacy COBOL execution
environment on top of [RedDragon](https://github.com/avishek-sen-gupta/red-dragon) (a
general-purpose multi-language interpreter, vendored separately, never modified by this repo),
the composition layer that assembles them, and a static analyser that reads the same corpora
without running them:

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
- **[`cobble/`](cobble/)** — corpus onboarding and whole-system knowledge-graph extraction,
  analysis only: it parses and walks the ASG, and never lowers to IR or executes. On top of the
  program/file/transaction graph it builds field-level byte dataflow — a source-level CFG,
  variable dependency graphs, and a byte-range trace that follows a commarea across LINK
  boundaries. Its pipeline runs from `cobble/` as `make parse CONFIG=…` then
  `make build CONFIG=…` (TOML configs), or via the `cobble-*` entry points; the parse is the
  only stage that starts a JVM, and every stage after it reads the one ASG cache it wrote.

Whole-system knowledge-graph extraction used to live here as a `knowledge_graph/` package, with
per-runtime extractors inside Cicada and Jackal. It was deleted ahead of folding the standalone
**cobble** repository into this workspace: cobble was a VM-free successor to that pipeline, not
a lagging copy of it, so the graph stack arrived with cobble rather than being merged into its
own ancestor — and has since grown the byte-level dataflow stack above. See
[`docs/superpowers/specs/2026-09-01-delete-stale-graph-stack-design.md`](docs/superpowers/specs/2026-09-01-delete-stale-graph-stack-design.md).

## Repository structure

Cicada, Squall, and Jackal were originally three separate repos, merged into this one via
`git subtree` (full commit history preserved — `git log --follow -m` on any file inside them
still walks back across the merge boundary). Each keeps its own `CLAUDE.md`, `Makefile`,
`pyproject.toml`, and test suite, and remains fully independently buildable and testable —
merging them didn't couple their release cadences or make them depend on each other.
Cross-package imports are enforced against by a shared root
[`.importlinter`](.importlinter) contract; only `red_dragon_forge/` and `cobble/` may import
from more than one of them. Cobble carries three contracts of its own: it is static analysis,
so it must not import the interpreter, nor any runtime (cicada's dispatcher/VSAM/BMS/strategy,
jackal's runner/catalog/IDCAMS, squall beyond `statements`), and nothing in the workspace may
import it. See
[`docs/superpowers/specs/2026-07-05-monorepo-migration-design.md`](docs/superpowers/specs/2026-07-05-monorepo-migration-design.md)
for the full migration design and rationale.

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

## Setup

```bash
git clone --recurse-submodules git@github.com:avishek-sen-gupta/red-dragon-forge.git
cd red-dragon-forge
make setup   # init submodules + build the ProLeap + JCL bridge JARs + uv sync --all-packages
```

The CICS end-to-end and fitness-golden paths additionally require the native `hlasm_export`
binary (BMS symbolic-map generation). Build it with a native toolchain (cmake / ninja / clang)
via [`cicada/third-party/che-che4z-lsp-for-hlasm-fork/build.sh`](cicada/third-party/che-che4z-lsp-for-hlasm-fork/build.sh)
(`./build.sh --target hlasm_export`); CI builds it in the `cicada` and `forge` jobs.

## Tests

Each package is independently testable from its own directory:

```bash
cd cicada && make test    # unit + integration + CardDemo e2e
cd squall && make test    # needs SQUALL_DB2_DSN + a running Db2 (make db2-up)
cd jackal && make test
cd cobble && make test    # no JVM, no Db2 — static analysis only
```

Or run every package's suite in one pass from the repo root, building the shared ProLeap +
JCL bridge JARs exactly once regardless of how many packages need them:

```bash
make test-all
```

`red-dragon-forge`'s own composition-layer tests (`make test`, run from the repo root) need
the same `SQUALL_DB2_DSN` as Squall for their one live-Db2 end-to-end test.

### The Db2 container needs a VM with at least 6 GiB

`icr.io/db2_community/db2` is amd64-only, so on Apple Silicon it runs under emulation, and
`db2sysc` maps roughly **3 GB of virtual memory**. Give the container VM **6 GiB or more**.
A second Db2 container sharing the VM doubles the requirement.

Starved of memory, Db2 fails in a way that does not look like a memory problem: the
*container stays up and reports no restart*, while the database manager is killed underneath
it. Tests then fail with `SQL30081N` (communication error), and a local connect reports
`SQL1032N  No start database manager command was issued`. `docker stats` looks innocent —
it reports resident memory, not the mapping that triggers the kill. The real evidence is the
kernel log:

```bash
docker exec squall-db2 dmesg | grep -i oom
# Out of memory: Killed process ... (db2sysc) total-vm:3128012kB
# oom-kill: constraint=CONSTRAINT_NONE ... global_oom
```

`global_oom` means the VM ran out, not the container's cgroup — so a per-container
`mem_limit` will not help.

**Raising the VM alone does not fix this.** `INSTANCE_MEMORY` defaults to
`AUTOMATIC`, so Db2 sizes itself to a share of whatever memory it can see and grows
into it over a session's worth of connections: a 2 GiB VM died within minutes, a
6 GiB VM ran five hours and then died the same way with the container holding
5.4 GiB. Give the VM headroom **and** cap the instance:

```bash
colima stop && colima start --cpu 4 --memory 6   # colima; Docker Desktop: Settings -> Resources
docker exec squall-db2 bash -lc \
  "su - db2inst1 -c 'db2 update dbm cfg using INSTANCE_MEMORY 262144'"
cd squall && make db2-restart
```

262144 pages is 1 GiB, ample for these test databases. The setting lives in the
container's `dbm cfg`, so `make db2-clean` or a rebuilt container loses it.

**The cap alone is still not sufficient** — it bounds database manager shared
memory, not agent private memory or the process's total footprint, which is what
the kernel kills on. A capped instance has been observed OOM-killed at ~4.8 GiB
resident / ~9 GiB mapped after 23 hours, with the container still reporting
`(healthy)`. Treat the cap as reducing the frequency, not eliminating the failure;
see bead forge-zka.

`cd squall && make db2-restart` revives a killed instance in about fifteen seconds without a
re-init, which is the fast way out when it happens mid-run.

## Issue tracking

Uses [Beads](https://github.com/gastownhall/beads) (`bd`). `.beads/` (the local Dolt working
DB) is gitignored; `issues/issues.jsonl` is the tracked git source of truth. See `CLAUDE.md`
for the full convention.
