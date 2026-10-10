# jackal architecture

jackal runs mainframe JCL batch jobs on the red-dragon interpreter. It parses a job, threads
a job-scoped dataset catalog through its steps, runs COBOL steps on the red-dragon VM, and
emulates utility programs in Python. The reference workload is the CardDemo batch tier in
`vendor/carddemo/app/jcl`. Command-line use is in [cli.md](cli.md); a worked run is
in [../../how-to/run-jcl-job.md](../../how-to/run-jcl-job.md). Open work is in
[../../roadmaps/jackal.md](../../roadmaps/jackal.md).

jackal requires Python 3.13. Its dependencies are `lark` and `red-dragon` (an editable path
source at `vendor/red-dragon`, which is never modified from this repo). jackal must not import
cicada or squall; `.importlinter` enforces this.

## How a job runs

1. Parse. `jackal.jcl.parser.parse_jcl` sends the JCL text to the JCL bridge JAR in a JVM
   subprocess. The JAR parses it with the ANTLR mapa grammar and returns JSON that mirrors the
   parsed model: statements (program steps, PROC calls with their overrides split from their
   qualifiers, IF blocks with their expression as a tree), and per DD its DSN kind, DISP and
   concatenated members. `jackal.jcl.bridge_parser` validates it as the Pydantic models in
   `jackal.jcl.wire`, which build an immutable `Job` (`jackal.model`).
2. Expand procedures. `JobRunner` calls `jackal.jcl.proc_expand.expand_procs` when it is given
   proclib directories. It inlines `EXEC PROC=` calls, substitutes symbolic parameters, applies
   DD overrides and handles nesting. `.prc` files are parsed by the same JAR. The CLI does not
   pass proclib directories.
3. Run steps in order (`jackal.runner.JobRunner`). For each step:
   - `COND=` from the JOB card and the step is evaluated by `jackal.cond` against the return
     codes of steps that ran. A true condition bypasses the step.
   - Referbacks (`DSN=*.STEP.DD`) are resolved to the DSN recorded for that earlier step. If
     the referenced step did not run, the referencing step is bypassed.
   - The step is dispatched. A `PGM=` in the utility table runs the emulated utility.
     Any other `PGM=` is read as `<source-dir>/<PGM>.cbl` and run as COBOL.
4. At job end, surviving temporary datasets are deleted. The result is a `JobResult` holding
   one `StepResult` per step.

## COBOL steps

`jackal.cobol_step.run_cobol_step` parses the program with the ProLeap bridge JAR, maps each
`FILE-CONTROL` entry to the file the step's DD resolves to in the catalog, and runs it on the
red-dragon VM. `PARM=` is passed in as an OS halfword-prefixed parameter region
(`jackal.parm`). The step's return code is read back from the VM.

## Datasets and the catalog

`jackal.catalog.DatasetCatalog` maps DSNs to backing files in a per-run working directory.

| DD form | Behaviour |
|---|---|
| `DISP=OLD` or `SHR` | Resolved from the catalog, then from `<data-dir>/<DSN>`. Missing is an error. |
| `DISP=MOD` | As above; created empty in the working directory if absent. |
| `DISP=NEW` | Created empty in the working directory. |
| `DSN=&&NAME` | Job-scoped temporary dataset, deleted at job end. |
| `DSN=*.STEP.DD` | Referback to an earlier step's DD. |
| `DISP=(…,DELETE)` | The dataset and its file are removed when the step ends. |
| `--dataset DSN=path` | Seeds the catalog before the job starts. |

Supported organisations are sequential (PS) and VSAM KSDS. DSN types are in `jackal.dsn`.

## Utilities

`jackal.utilities.UTILITIES` registers the emulated programs.

| Program | Behaviour |
|---|---|
| `IEFBR14` | Allocates and disposes each non-SYSOUT DD. Return code 0. |
| `IDCAMS` | Parses the in-stream `SYSIN` and executes it. Return code is the final MAXCC. |

The IDCAMS executor (`jackal.idcams.executor`) handles `DELETE`, `DEFINE CLUSTER`, `REPRO`,
`IF MAXCC … THEN` and `SET MAXCC`. The parser it uses (`jackal.idcams.parser`) is a Lark
grammar, `jackal/jackal/idcams/grammar.lark`. A second, broader Lark grammar,
`jackal/jackal/idcams/grammar/ams.lark`, parses all IDCAMS commands into typed ASTs
(`jackal.idcams.parser_comprehensive` and the `ast_*.py` modules). The executor does not use
it; see `red-dragon-forge-vqa` in the roadmap. The IDCAMS command reference is
[idcams-ref.pdf](idcams-ref.pdf).

## The JCL bridge JAR

The JAR is built from `jackal/jcl-bridge` (Maven) by the root `make jar`, which `make setup`
runs. `. ./bridge-env.sh` exports its path as `JCL_BRIDGE_JAR`, and the ProLeap JAR's path as
`PROLEAP_BRIDGE_JAR`. jackal reads both from the environment and fails if either is unset when
needed. The grammar's source and licence are recorded in
[jackal/jcl-bridge/PROVENANCE.md](../../../jackal/jcl-bridge/PROVENANCE.md).

## Package layout

| Path | Contents |
|---|---|
| `jackal/jackal/cli.py` | The `jackal` command. |
| `jackal/jackal/runner.py` | `JobRunner`: step sequencing, `COND=`, referbacks, dispatch. |
| `jackal/jackal/cobol_step.py` | Runs a COBOL step on the red-dragon VM. |
| `jackal/jackal/utilities.py` | The utility table: IEFBR14, IDCAMS. |
| `jackal/jackal/catalog.py` | Job-scoped DSN-to-file catalog with DISP lifecycle. |
| `jackal/jackal/cond.py` | `COND=` evaluation. |
| `jackal/jackal/model.py`, `results.py` | Immutable job model and step results. |
| `jackal/jackal/dsn.py`, `value_parts.py` | DSN types; literal and symbolic value parts. |
| `jackal/jackal/parm.py` | `PARM=` region for COBOL `LINKAGE`. |
| `jackal/jackal/tso.py` | Reads the programs a TSO batch step runs from its `SYSTSIN`. Used by cobble. |
| `jackal/jackal/jcl/` | JCL parsing through the bridge JAR; procedure expansion. |
| `jackal/jackal/idcams/` | IDCAMS grammars, parsers, typed ASTs and executor. |
| `jackal/jcl-bridge/` | The Java JCL bridge (Maven project, vendored mapa grammar). |
| `jackal/tests/` | `unit/` and `integration/`. CardDemo end-to-end tests carry the `carddemo_e2e` marker. |

`.importlinter` layers the package as `cli` → `runner` → `cobol_step` / `utilities` →
`catalog` → `model`, keeps `jackal.jcl` and `jackal.idcams` independent of each other, and
keeps `model` and `results` free of other jackal imports.

The JCL dataset graph and the COBOL `FILE-CONTROL` graph are built in `cobble/cobble/jcl/`
(`jcl_graph.py`, `cobol_file_graph.py`), not in jackal.

## Tests

From the repo root:

```bash
. ./bridge-env.sh
cd jackal && uv run --no-sync python -m pytest
```

The CardDemo end-to-end tests read `vendor/carddemo/app`. To use another checkout, set
`CARDDEMO_HOME` to its `app/` directory. The CLI reads the same variable as the checkout root,
one level up; see [cli.md](cli.md).
