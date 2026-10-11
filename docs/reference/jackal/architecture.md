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
2. Expand. `jackal.expansion.expand_procs(job, library)` returns an `ExpandedJob` or a
   `JclError` value, before anything runs. It inlines each PROC call found in the `ProcLibrary`
   (`DirectoryProcLibrary` reads `<dir>/<PROC>.prc` through the same JAR), resolving symbolic
   parameters in the caller's scope and applying the call's `COND`, `PARM` and DD overrides by
   the JCL Reference's rules (an unqualified `COND` reaches nested PROCs' steps too); an override DD merges with the PROC's DD per parameter, keeping
   what it does not write (an unwritten DISP is `NotCoded`). A `SET` statement defines symbols for the statements after it,
   job-level steps included, whichever IF branch it sits in; a value on the calling `EXEC` or a
   PROC default takes precedence over it. A call whose PROC is in no library stays an `UnexpandedCall`. Every
   step reference (in `COND`, referbacks and IF terms) becomes a `StepReference`: a path of
   PROC-call coordinates and a target step, each coordinate resolved (holding what was found) or
   unresolved (holding the name). A name that matches nothing, or a step inside a PROC in no
   library, is an unresolved coordinate and a logged warning, not an error. The `JclError`s are
   the mistakes in the JCL itself: a reference to a later step, to a PROC call, or through a
   program step; an override naming no step; a PROC that calls itself. A name used by more than
   one run of a PROC resolves to the same run, with a warning. `expand_or_fail` raises the error
   as `ExpansionFailed` for callers that want an exception.
3. Run steps in order (`jackal.runner.JobRunner`). The runner is given an
   `UnresolvedReferenceStrategy` (`jackal.unresolved`, blueprint D7); both behaviours are
   jackal's own, since z/OS rejects a job with an unresolved reference at conversion:
   - `RaiseErrorStrategy` raises `UnresolvedReference` before any step runs, naming the first
     `UnexpandedCall` or step whose `COND` or referback holds an unresolved reference.
   - `IgnoreStrategy` runs the job. A `COND` test naming an unresolved step is false, as for a
     step that did not run. An `UnexpandedCall`, and a step with an unresolved referback, go
     through the gate like any step (an `UnexpandedCall` with no `COND`); where the gate would
     run them they are recorded as `SkippedUnresolved`; later `COND` tests skip them as they skip a bypassed step.

   The runner is also given a `MissingDataStrategy` (`jackal.missing_data`) for a DD the
   catalog cannot allocate: a dataset not found, a temporary dataset no earlier step created,
   or a `NEW` dataset whose name already exists in the job.
   - `StrictAllocation` fails the step, as z/OS does: the program does not run, and the step's
     outcome is `AllocationFailed(ddname, error)`.
   - `LenientAllocation` allocates an empty dataset in its place (overwriting, for a duplicate
     name), logs a warning, and runs the step. The CLI uses it.

   And a `MissingProgramStrategy` (`jackal.missing_program`) for a program that is neither a
   utility nor found as COBOL source (`jackal.program_sources`):
   - `AbendMissingProgram` abends the step `S806`, as z/OS does when it cannot find the load
     module.
   - `StubMissingProgram` completes the step with RC 0 in the program's place and logs a
     warning. The CLI uses it.

   For each step:
   - These are refused with `UnsupportedStep` until each is supported: a step under an IF
     (guards are parsed and attached but not yet evaluated) and a concatenated DD.
   - Each step ends with one outcome (`jackal.results`): `Completed(rc)`, `Abended(code)`,
     `Bypassed(reason)`, `Flushed(cause)`, `SkippedUnresolved` or
     `AllocationFailed(ddname, error)`. `JobResult.outcome` is decided by the first step that
     abended (`JobAbended(step, code)`) or failed allocation (`JobAllocationFailed(step,
     failure)`), else is `JobCompleted` with the highest return code among completed steps.
     Once a step fails allocation, every later step, PROC call and step with an unresolved
     referback is `Flushed(AfterAllocationFailure(step))`, whatever its `COND`, `EVEN` or
     `ONLY` says, as z/OS ends a job at a JCL error.
   - `jackal.cond.gate` decides whether a step runs. A failed allocation is checked first;
     otherwise it reads only completed steps' return codes. Once a JOB card's `COND` test is met, this step and every later one are
     `Flushed(AfterJobCond(step))`, naming the step that met it. Otherwise a true test of the
     step's own `COND` is `Bypassed(COND_SATISFIED)`. After an abend, a step without `EVEN`
     or `ONLY` is `Flushed(AfterAbend(step))`; an `EVEN` or `ONLY` step goes on to its own
     `COND` tests. With no abend, a `COND=ONLY` step is `Bypassed(ONLY_WITHOUT_ABEND)`.
   - Referbacks (`DSN=*.STEP.DD`) copy the DSN written on the referenced DD, whether or not
     that step ran, as z/OS does. The copied name is then allocated like any other: a dataset
     the referenced step never made is `DATASET_NOT_FOUND` or `TEMP_NOT_CREATED`.
   - The runner allocates every DD before the program starts (`jackal.allocation`), in order: a
     dataset through the catalog, `DD *` cards written out as 80-byte EBCDIC records, `DUMMY` and
     `SYSOUT` as empty sinks. STEPLIB and JOBLIB are skipped: jackal finds programs as source,
     not in load libraries. The program receives the allocations as a `DdEnvironment`. If a
     DD fails under `StrictAllocation`, the step's in-stream and sink files are released and the
     `NEW` datasets it had already created are deleted.
   - The step is dispatched. A program in the utility table runs the emulated utility.
     Any other program found as `<source-dir>/<PGM>.cbl` is run as COBOL. A program found as
     neither is settled by the `MissingProgramStrategy`.
   - A dataset allocated `DISP=MOD` is positioned at its end: a COBOL `OPEN OUTPUT` on it
     appends, through jackal's own file handler over red-dragon's file drivers.
   - After the program, the runner applies each DD's normal DISP, or its abnormal DISP if the
     step abended, and releases the sinks.
     Programs never allocate or dispose themselves.
4. At job end, surviving temporary datasets are deleted, and so is every dataset the job created
   with `DISP=(NEW,PASS)` that no later step received with a disposition of its own. The result is a `JobResult` holding
   one `StepResult` per step.

## COBOL steps

`jackal.cobol_step.run_cobol_step` parses the program with the ProLeap bridge JAR, maps each
`FILE-CONTROL` entry to the file of the step's DD allocation, and runs it on the
red-dragon VM. `PARM=` is passed in as an OS halfword-prefixed parameter region
(`jackal.parm`). Each program runs on red-dragon's resumable entry point with its own budget
of interpreter steps, `JobRunner`'s `program_step_budget` (the CLI gives 500,000). A program
that ends gives `Completed` with the return code read back from the VM. One still running
when its budget runs out abends `S322`, as z/OS ends a step that exceeds its CPU time.

## Datasets and the catalog

Datasets live in a **system directory** that persists across runs, standing in for a
mainframe's disks and catalog. `jackal.system_catalog.SystemCatalog` holds it: `catalog.json`
records every cataloged dataset with its label (`jackal.labels`: RECFM and LRECL for a
sequential dataset, LRECL and key extent for a KSDS, or pending for a dataset a job created,
whose label is built at its first `OPEN OUTPUT` in red-dragon-forge-8in), and `datasets/`
holds the bytes. Data enters only through `jackal catalog add`, which copies the file in with
its label; no Forge runtime accepts an unlabelled dataset. Labels are stored and checked; I/O
does not read them yet (8in). `jackal.catalog.DatasetCatalog` is one job's view of it, adding
the job's temps, passed datasets and a scratch directory. Dispositions follow SMS: `CATLG` and
`KEEP` leave a dataset cataloged and `UNCATLG` does nothing.

| DD form | Behaviour |
|---|---|
| `DISP=OLD` or `SHR` | Resolved from the system catalog. Missing is an allocation failure. |
| `DISP=MOD` | As above; created empty and cataloged if absent. |
| `DISP=NEW` | Created empty and cataloged, its label pending. A name already cataloged fails allocation. |
| `DSN=&&NAME` | Job-scoped temporary dataset, kept apart from named datasets (its file is `&&NAME`), deleted at job end. |
| `DSN=*.STEP.DD` | Referback to an earlier step's DD. |
| `DISP=(…,DELETE)` | The dataset and its file are removed when the step ends. |
| `DISP=(…,PASS)` | Handed to later steps; a later DD naming it receives it, and its own disposition then applies. One the job created and never received is deleted at job end. |
| IDCAMS `DEFINE CLUSTER` | Catalogs a KSDS with the label its `RECORDSIZE` and `KEYS` give. |

Supported organisations are sequential (PS) and VSAM KSDS. DSN types are in `jackal.dsn`;
the catalog's one in-place table is `jackal.catalog_stores`.

## Utilities

`jackal.utilities.UTILITIES` registers the emulated programs.

| Program | Behaviour |
|---|---|
| `IEFBR14` | Does nothing; the runner's allocation and disposition do its work. Return code 0. |
| `IDCAMS` | Parses the in-stream `SYSIN` and executes it; `REPRO` reads and writes the datasets its DDs were allocated. Return code is the final MAXCC. |

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
| `jackal/jackal/allocation.py` | A step's DD allocations, made before and disposed after its program. |
| `jackal/jackal/cobol_step.py` | Runs a COBOL step on the red-dragon VM. |
| `jackal/jackal/cobol_files.py` | jackal's COBOL file handler: red-dragon's, with a `DISP=MOD` file opened to append. |
| `jackal/jackal/utilities.py` | The utility table: IEFBR14, IDCAMS. |
| `jackal/jackal/catalog.py` | One job's dataset catalog: the system's datasets, temps, `PASS`, DISP lifecycle. |
| `jackal/jackal/system_catalog.py` | The persistent system catalog and the bytes it owns. |
| `jackal/jackal/labels.py`, `dataset.py` | Dataset labels, and a dataset with its file and label. |
| `jackal/jackal/cond.py` | `COND=` evaluation. |
| `jackal/jackal/model.py`, `results.py` | Immutable job model, DSN types and step results. |
| `jackal/jackal/value_parts.py` | Literal and symbolic value parts. |
| `jackal/jackal/unresolved.py` | What the runner does with unresolved references (D7). |
| `jackal/jackal/missing_data.py` | What the runner does with a DD it cannot allocate. |
| `jackal/jackal/missing_program.py` | What the runner does with a program it cannot find. |
| `jackal/jackal/program_sources.py` | Where the runner finds a program's COBOL source. |
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
