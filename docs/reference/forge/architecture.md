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
| `zos/` | `zos` | COBOL and HLASM file handling against catnip datasets (`zos.cobol.io`): a COBOL call goes to its program's provider, an HLASM call (program `""`) to `DdFileIOProvider`, one file per DDNAME, which labels a pending dataset from OPEN's declared frame; `dd_definitions` turns a sequential or pending dataset into an HLASM DD. Also `program_outcome`: the abends and return code of a finished program, read by the entry program's language (COBOL `RETURN-CODE`, HLASM R15; abends from both). Imports catnip and red-dragon; jackal and plain mode build on it. | |
| `catnip/` | `catnip` | System catalog: datasets, clusters, alternate indexes, paths and GDG bases, shared by jackal and cicada; `catnip install` loads a data declaration. | [catnip](../catnip/README.md) |
| `litter/` | `litter` | Package: COBOL programs lowered once and linked into one image, zipped with a manifest and mapsets; `build` writes it, `open_package` reads it. | [litter](../litter/README.md) |
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
returns. Every run is given its builtins table (`run_linked(…, builtins=)`); no table is
process-global. A region's table is red-dragon's `core_builtins()` with each runtime's entries
composed in by `compose_builtins`, which refuses a name two of them define. RedDragon's VM has no
CICS, SQL or JCL knowledge of its own.

## The composition layer

`red_dragon_forge` composes runtimes that do not know about each other.

| Module | Purpose |
|---|---|
| `build_command.py` | `forge-build`: a `build.toml` into a litter package. See [Build](build.md). |
| `run_command.py` | `forge-run`: finds `env.toml`'s mode section and imports only that mode's command. See [Run](run.md). |
| `env_config.py` | `EnvConfig`: the settings every mode shares, `run_mode`, and the `[sql]` check against the manifest. Each command extends it with its section and checks. |
| `run_preparation.py` | What every mode starts from: its config, the opened package and its `Coprocessing`. |
| `plain_command.py` | `[plain]` (`PlainEnv`), through `plain_mode.py`. Imports neither jackal nor cics. |
| `jcl_command.py` | `[jcl]` (`JclEnv`): the job, run by jackal's `JobRunner`. Imports no cics. |
| `cics_command.py` | `[cics]` (`CicsEnv`): the region served over TN3270; `cics_region` assembles it in process. `region_builtins` composes the region's other builtins: coprocessing's, red-dragon's default HLASM run inputs (host clock with STIMER's wait, empty PARM, no DDs) and the floating-point tables, so a transaction can `CALL` an HLASM program in the package. Imports no jackal. |
| `coprocessors.py` | The coprocessors a build may name, each with its compile spec and the programs it requires linked. |
| `coprocessing.py` | `Coprocessing`: what a package's `sql` adds to a run — squall's `SqlRuntime` (its builtins and three unit-of-work hooks) and the abend rollback. `db2_connection.py` builds it; with no `sql` the runtime is empty and its hooks are no-ops. `[plain]` and `[jcl]` compose its builtins into their table; `[cics]` also packs its hooks into cicada's `TransactionHooks`. |
| `floating_point_builtins.py` | The HLASM binary, hexadecimal, decimal and PFPO floating-point tables as one; `[plain]`, `[jcl]` and `[cics]` compose it into their table. |
| `plain_mode.py` | `[plain]`: runs one program from the package image, with no job or step, and reports RC, abend or budget exhaustion; an HLASM entry reports R15 (the entry address if it never sets it), and an HLASM abend under a COBOL entry is reported. HLASM gets the host clock (with STIMER's wait), an empty PARM, and each `[plain.files]` entry as a DD. |
| `db2_connection.py` | The `[sql]` Db2 connection: installs squall's runtime over it and returns the `Coprocessing`. |
| `run.py` | `run_program(linked, specs, …)` runs a compiled program through the one spec that owns execution. CICS owns execution; SQL is synchronous and owns none. |
| `carddemo_db2_schema.py` | CardDemo's Db2 schema and seed data. |
| `carddemo_db2_seed.py` | `carddemo-db2-seed`: drops, recreates and seeds the schema. Run it as `make db2-seed`. |
| `db2_status.py` | `make db2-status`: connects and queries Db2. Exit codes: 0 up, 1 down, 2 DSN unset. |

Design records: [CICS + SQL composition](../../records/design/2026-07-04-cics-sql-composition-design.md),
[per-region builtins](../../superpowers/specs/2026-10-16-per-region-builtins-design.md).

## Package boundaries

`.importlinter` at the repo root is the enforced contract. Run it with `uv run lint-imports`.

- `cics`, `squall` and `jackal` must not import each other.
- `catnip` imports none of `cics`, `squall`, `jackal`, `cobble` or `red_dragon_forge`. `cics` and
  `jackal` import it.
- `catnip` also imports no `interpreter` (`catnip-imports-no-runtime`).
- `zos` imports none of `cics`, `squall`, `jackal`, `cobble`, `litter` or `red_dragon_forge` (`zos-imports-no-runtime`). It sits between catnip and the runtimes.
- forge-run's shared modules (`run_preparation`, `env_config`, `coprocessing`, `db2_connection`, `config_error`, `run_mode`) import neither `jackal` nor `cics` (`forge-run-shared-without-runtimes`).
- `plain_command`, `plain_mode` and `plain_run` import neither `jackal` nor `cics` (`plain-mode-without-runtimes`); `jcl_command` and `jcl_run` import no `cics` (`jcl-mode-without-cics`); `cics_command` and `cics_run` import no `jackal` (`cics-mode-without-jackal`). `run_command` imports each mode only inside its branch.
- `litter` imports none of `cics`, `squall`, `jackal`, `cobble`, `catnip` or `red_dragon_forge`.
  `jackal` and `cics` import it: a job runs against a litter package, and a TN3270 region is
  assembled from one.
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
