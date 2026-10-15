# Forge architecture

red-dragon-forge runs and analyses COBOL programs written for IBM mainframe environments. Each
runtime emulates one environment on top of [RedDragon](https://github.com/avishek-sen-gupta/red-dragon),
a multi-language interpreter vendored at `vendor/red-dragon`. The forge never modifies
`vendor/red-dragon`.

## Packages

| Package | Python module | What it is | Reference |
|---|---|---|---|
| `cicada/` | `cics` | CICS runtime: pseudo-conversational transaction dispatch, VSAM KSDS file control over the system catalog, BMS screens, a TN3270 server. | [cicada](../cicada/architecture.md) |
| `squall/` | `squall` | EXEC SQL coprocessor runtime for Db2-attached programs. | [squall](../squall/architecture.md) |
| `jackal/` | `jackal` | JCL/batch engine: job and step orchestration, IDCAMS, a job's view of the datasets. | [jackal](../jackal/architecture.md) |
| `catnip/` | `catnip` | System catalog: datasets, clusters, alternate indexes, paths and GDG bases, shared by jackal and cicada; `catnip install` loads a data declaration. | [catnip](../catnip/README.md) |
| `litter/` | `litter` | Package: COBOL programs compiled once into a zip of linked programs, manifest and mapsets; `build` writes it, `open_package` reads it. | [litter](../litter/README.md) |
| `red_dragon_forge/` | `red_dragon_forge` | Composition layer: assembles several runtimes into one program. | this page |
| `cobble/` | `cobble` | Static analyser: corpus onboarding, knowledge graph, source CFG, field dataflow. Never runs a program. | [cobble](../cobble/config.md) |

## How runtimes plug into RedDragon

RedDragon exposes one seam, `CoprocessorSpec`, in `interpreter.project.coprocessor_compile`. A
spec bundles a dialect parser and a lowering strategy for one kind of `EXEC` block.
`compile_program` takes a list of specs and compiles one COBOL program with all of them.
It returns the `LinkedProgram` alone. Compilation runs in three stages chained through files —
`.ast.json`, `.unit.json`, `.linked.json` — named by a digest of the source and the lowering
settings, including each spec's strategy `name`; the program a caller gets is read back from
the linked file ([decision record](../../records/design/2026-10-13-compiled-cobol-is-files.md)).
A strategy's lowering leaves nothing a run needs outside the IR, so a compiled program runs in
any process.

Each runtime lowers its `EXEC` statements to `CallFunction` IR that calls builtins the runtime
registers. RedDragon's VM has no CICS, SQL or JCL knowledge of its own.

## The composition layer

`red_dragon_forge` composes runtimes that do not know about each other.

| Module | Purpose |
|---|---|
| `run.py` | `run_program(linked, specs, …)` runs a compiled program through the one spec that owns execution. CICS owns execution; SQL is synchronous and owns none. |
| `carddemo_db2_region.py` | The CardDemo region with CICS and SQL composed. |
| `carddemo_db2_schema.py` | CardDemo's Db2 schema and seed data. |
| `carddemo_db2_seed.py` | `carddemo-db2-seed`: drops, recreates and seeds the schema. Run it as `make db2-seed`. |
| `carddemo_db2_cli.py` | `carddemo-db2-cli`: serves the composed region over TN3270. See [Run CardDemo](../../how-to/run-carddemo.md). |
| `db2_status.py` | `make db2-status`: connects and queries Db2. Exit codes: 0 up, 1 down, 2 DSN unset. |

Design record: [CICS + SQL composition](../../records/design/2026-07-04-cics-sql-composition-design.md).

## Package boundaries

`.importlinter` at the repo root is the enforced contract. Run it with `uv run lint-imports`.

- `cics`, `squall` and `jackal` must not import each other.
- `catnip` imports none of `cics`, `squall`, `jackal`, `cobble` or `red_dragon_forge`. `cics` and
  `jackal` import it.
- `litter` imports none of `cics`, `squall`, `jackal`, `cobble`, `catnip` or `red_dragon_forge`.
- `red_dragon_forge` may import any runtime.
- `cobble` may import only the static surface of the other packages (parsers, models,
  `cobol_asg`). It must not import the interpreter, any runtime module, `catnip` or `litter`,
  and nothing imports `cobble`.

Rationale: [package boundaries](../../records/design/2026-09-09-package-boundaries.md); catnip's
placement: [the catnip decision record](../../records/design/2026-10-14-catnip-catalog-extraction.md).

## Native and Java build products

| Product | Built by | Used by | Path exported by `. ./bridge-env.sh` |
|---|---|---|---|
| ProLeap COBOL bridge JAR | `make jar` (from `vendor/red-dragon/proleap-bridge`) | every runtime, cobble's parse stages | `PROLEAP_BRIDGE_JAR` |
| JCL bridge JAR | `make jar` (from `jackal/jcl-bridge`) | jackal, cobble's JCL stages | `JCL_BRIDGE_JAR` |
| `hlasm_export` | `make hlasm` | BMS symbolic-map generation | `HLASM_EXPORT` |
