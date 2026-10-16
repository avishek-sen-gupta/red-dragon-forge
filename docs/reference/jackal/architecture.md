# jackal architecture

jackal runs mainframe JCL batch jobs on the red-dragon interpreter. It parses a job, threads
a job-scoped dataset catalog through its steps, runs COBOL steps on the red-dragon VM, and
emulates utility programs in Python. The reference workload is the CardDemo batch tier in
`vendor/carddemo/app/jcl`. Command-line use is in [cli.md](cli.md); a worked run is
in [../../how-to/run-jcl-job.md](../../how-to/run-jcl-job.md). Open work is in
[../../roadmaps/jackal.md](../../roadmaps/jackal.md).

jackal requires Python 3.13. Its dependencies are `lark`, `red-dragon` (an editable path
source at `vendor/red-dragon`, which is never modified from this repo) and
[catnip](../catnip/README.md), the system catalog. jackal must not import cicada or squall;
`.importlinter` enforces this.

## How a job runs

1. Parse. `jackal.jcl.parser.parse_jcl` sends the JCL text to the JCL bridge JAR in a JVM
   subprocess. The JAR parses it with the ANTLR mapa grammar and returns JSON that mirrors the
   parsed model: statements (program steps, PROC calls with their overrides split from their
   qualifiers, IF blocks with their expression as a tree), and per DD its DSN kind, DISP,
   concatenated members and DCB attributes (RECFM and LRECL, coded in `DCB=` or as DD keywords,
   and the model: a dataset name, `*.step.dd` or a same-step `*.dd`), the `LIKE` and `REFDD` sources,
   and GDGORDER. An override changes only the DCB subparameters, LIKE, REFDD and GDGORDER it codes
   ([decision record](../../records/design/2026-10-12-jackal-dcb-attributes.md)). `jackal.jcl.bridge_parser` validates it as the Pydantic models in
   `jackal.jcl.wire`, which build an immutable `Job` (`jackal.model`).
2. Expand. `jackal.expansion.expand_procs(job, library)` returns an `ExpandedJob` or a
   `JclError` value, before anything runs. It inlines each PROC call found in the `ProcLibrary`
   (`DirectoryProcLibrary` reads `<dir>/<PROC>.prc` through the same JAR), resolving symbolic
   parameters in the caller's scope and applying the call's `COND`, `PARM` and DD overrides by
   the JCL Reference's rules (an unqualified `COND` reaches nested PROCs' steps too); an override DD merges with the PROC's DD per parameter, keeping
   what it does not write (an unwritten DISP is `NotCoded`). A `SET` statement defines symbols for the statements after it,
   job-level steps included, whichever IF branch it sits in; a value on the calling `EXEC` or a
   PROC default takes precedence over it, and a symbol a nested PROC does not assign keeps the value of the PROC that called it (JCL Ref Table 13). An in-stream PROC (`PROC` … `PEND` in the job) is found before the library, by calls after its definition only; its body is not part of the job's own steps ([decision record](../../records/design/2026-10-12-jackal-in-stream-procs.md)). A call whose PROC is in no library stays an `UnexpandedCall`. Every
   step reference (in `COND`, referbacks and IF terms) becomes a `StepReference`: a path of
   PROC-call coordinates and a target step, each coordinate resolved (holding what was found) or
   unresolved (holding the name). A name that matches nothing, or a step inside a PROC in no
   library, is an unresolved coordinate and a logged warning, not an error. The `JclError`s are
   the mistakes in the JCL itself: a reference to a later step, to a PROC call, or through a
   program step; an override naming no step; a PROC that calls itself. A name used by more than
   one run of a PROC resolves to the same run, with a warning. `expand_or_fail` raises the error
   as `ExpansionFailed` for callers that want an exception.
3. Run steps in order (`jackal.runner.JobRunner`), against a litter package. The runner is given an
   `UnresolvedReferenceStrategy` (`jackal.unresolved`, blueprint D7); both behaviours are
   jackal's own, since z/OS rejects a job with an unresolved reference at conversion:
   - `RaiseErrorStrategy` raises `UnresolvedReference` before any step runs, naming the first
     `UnexpandedCall` or step whose `COND` or referback (in DSN, DCB or REFDD) holds an unresolved reference.
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
   utility nor held by the package:
   - `AbendMissingProgram` abends the step `S806`, as z/OS does when it cannot find the load
     module.
   - `StubMissingProgram` completes the step with RC 0 in the program's place and logs a
     warning. The CLI uses it.

   For each step:
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
   - A step inside `IF/THEN/ELSE/ENDIF` carries its construct's condition as a guard
     (`jackal.if_guard`), the ELSE branch negated and nested IFs joined. After an abend such a
     step also goes on if its guard tests `ABEND`, `ABENDCC` or `¬ABEND`. A false guard is
     `Bypassed(IF_CONDITION_FALSE)`; the guard and the step's own `COND` must both allow it
     to run. The rules and their IBM sources are in
     [the IF/THEN/ELSE decision record](../../records/design/2026-10-12-jackal-if-then-else.md).
   - Referbacks (`DSN=*.STEP.DD`) copy the DSN written on the referenced DD, whether or not
     that step ran, as z/OS does. The copied name is then allocated like any other: a dataset
     the referenced step never made is `DATASET_NOT_FOUND` or `TEMP_NOT_CREATED`.
   - The runner allocates every DD before the program starts (`jackal.allocation`), in order: a
     dataset through the catalog, `DD *` cards written out as 80-byte EBCDIC records, `DUMMY` and
     `SYSOUT` as empty sinks. STEPLIB and JOBLIB are skipped: jackal finds programs in its
     package, not in load libraries. The program receives the allocations as a `DdEnvironment`. If a
     DD fails under `StrictAllocation`, the step's in-stream and sink files are released and the
     `NEW` datasets it had already created are deleted.
   - A concatenated DD (unnamed DDs after it) allocates and disposes each member with its own
     `DISP`. A COBOL `OPEN INPUT` reads the members in order as one file
     (`jackal.concatenated_records`), each checked against the FD like the first (a later V
     member may be shorter); any other open mode fails with file status 37
     ([decision record](../../records/design/2026-10-12-jackal-concatenation.md)). IDCAMS
     `REPRO` reads one member after member, each at its own label
     ([decision record](../../records/design/2026-10-12-jackal-repro-concatenation.md)).
   - A step's in-stream and sink files are released even when its program raises.
   - The step is dispatched. A program in the utility table runs the emulated utility.
     Any other program the package holds is run as COBOL. A program found as neither is
     settled by the `MissingProgramStrategy`.
   - A dataset allocated `DISP=MOD` is positioned at its end: a COBOL `OPEN OUTPUT` on it
     appends, through jackal's own file handler over red-dragon's file drivers.
   - After the program, the runner applies each DD's normal DISP, or its abnormal DISP if the
     step abended, and releases the sinks.
     Programs never allocate or dispose themselves.
4. At job end, surviving temporary datasets are deleted, and so is every dataset the job created
   with `DISP=(NEW,PASS)` that no later step received with a disposition of its own. The result is a `JobResult` holding
   one `StepResult` per step.

## COBOL steps

jackal compiles nothing. `JobRunner` is given a [litter](../litter/README.md) package holding one
linked image, built once, and a step's `EXEC PGM=X` (or `DSN RUN PROGRAM(X)` under a TSO monitor)
enters the image at program `X` with red-dragon's `ProgramEntry("X")`, as z/OS fetches a load
module. A name the image does not hold goes to the missing-program strategy. `JobRunner`'s
`permit_unresolved_call_targets` (default true, as `jackal run` uses it) is passed to every
step's run: false makes a `CALL` to a program the image does not hold raise
`UnresolvedProgramError`; `forge-run` sets it from `env.toml`'s `[tolerant]`. Every program the
image holds is a CALL target, by literal or through a data-name; one the build did not link is
not there. The image was lowered with the coprocessors it was built with: jackal imports no
coprocessor. `JobRunner`'s required `builtins` is the table every step's run is given:
`jackal run` passes red-dragon's `core_builtins()`; `forge-run` composes squall's `__exec_sql`
into it for a package built with `sql`.

Each lowered program carries a file-definitions `Data` directive, and every COBOL file call
names the program that made it. `jackal.file_definitions` reads every program's records from
the image, each with its `program`: the `FILE-CONTROL` entry, and the record format its FD asks
for, or the dataset's own where the `SELECT` has no FD. `jackal.cobol_step.run_cobol_step` runs
the image on the red-dragon VM with a `ProgramFilesIOProvider`, which hands each file call to
the `AllocatedFileIOProvider` of the program that made it, built from that program's own
declarations. Two programs that declare the same `SELECT` name each open their own DD with
their own FD, and their open files never meet; a program with no declaration for a `SELECT`
takes the dataset its DD names as labelled. At each `OPEN` (`jackal.cobol_files`), the record format the FD asks for
(`jackal.record_format`: Enterprise COBOL's default rule, a variable format's LRECL being its
largest record plus 4) meets the dataset's label: a pending label is written from it on
`OUTPUT` or `EXTEND`; a label that contradicts it in organization, fixed against variable, or
length fails the `OPEN` with file status 39. An indexed FD is checked against a cluster's or a
path's label the same way: its largest record against the cluster's LRECL, and its `RECORD KEY`
offset and length against the cluster's key, or the alternate key for a path. Each attribute in
conflict is logged as a warning, `DSN: FIELD: declared D, FD P` (for example
`A.KSDS: key offset: declared 0, FD 3`), so the line to change can be found; the program still
gets status 39 and may handle it. `ALTERNATE RECORD KEY` clauses are not compared, because a
cluster's label does not list its AIXs. `RECORDING MODE U` and `S` are refused. The
decisions and their IBM sources are in
[the COBOL OPEN decision record](../../records/design/2026-10-11-jackal-cobol-open-record-format.md).
A dataset labelled V or VB is read and written through `catnip.variable_records`, which keeps
each record behind its 4-byte record descriptor word as z/OS does, and fails a `REWRITE` that
changes a record's length with file status 44
([decision record](../../records/design/2026-10-12-jackal-variable-records.md)). `PARM=` is passed in as an OS halfword-prefixed parameter region
(`jackal.parm`). Each program runs on red-dragon's resumable entry point with its own budget
of interpreter steps, `JobRunner`'s `program_step_budget` (the CLI gives 500,000). A program
that ends gives `Completed` with the return code read back from the VM. One still running
when its budget runs out abends `S322`, as z/OS ends a step that exceeds its CPU time.
A program that calls LE's `CEE3ABD` abends with that user code (`Unnnn`; a bare call gives
U0000). `CEE3ABD` is a COBOL stub jackal links from `jackal/le_stubs/`, last on the CALL search
path. It records the code in its WORKING-STORAGE and `STOP RUN`s, and `jackal.le_abend` reads the
code from the finished VM
([decision record](../../records/design/2026-10-12-jackal-user-abend.md)).

## Datasets and the catalog

Datasets live in a **system directory** that persists across runs, standing in for a
mainframe's disks and catalog. The catalog is [catnip](../catnip/README.md)'s
`SystemCatalog`, shared with cicada, so a CICS region pointed at the same directory sees what a
job wrote. `catalog.json` records every cataloged dataset with its label (RECFM and LRECL for a
sequential dataset, LRECL and key extent for a KSDS, or pending for a dataset a job created,
whose label is built at its first `OPEN OUTPUT`), alternate indexes, paths and GDG bases, and
`datasets/` holds the bytes. Data enters through `catnip install`, which loads a whole data
declaration, or `jackal catalog add`, which copies one sequential file in with its label; no
Forge runtime accepts an unlabelled dataset. Every open reads the label: it chooses the driver
and gives the record length. A DD naming a path opens its base cluster through the path's
alternate index: a COBOL program reads it in alternate-key order, gets file status `02` when
more records with the same alternate key follow, and its writes change the base cluster.
`OPEN OUTPUT` through a path fails with file status 37 and leaves the base cluster as it was. A
`LIKE=` naming a path labels the new dataset from the base cluster. IDCAMS cannot define an
AIX or path (red-dragon-forge-shdi); `DELETE` of a cluster removes its AIXs and paths.
`jackal.catalog.DatasetCatalog` is one job's view of the system catalog, adding
the job's temps, passed datasets and a scratch directory. Dispositions follow SMS: `CATLG` and
`KEEP` leave a dataset cataloged and `UNCATLG` does nothing. An omitted normal or abnormal
disposition is kept as omitted by the parser and defaulted at allocation, once the catalog
knows whether it found the dataset or created it (`DELETE` if created, `KEEP` if found), as
the JCL Reference's DISP defaults say. The decisions and their IBM sources are in
[the 2026-10-11 decision record](../../records/design/2026-10-11-jackal-dataset-decisions.md).

| DD form | Behaviour |
|---|---|
| `DISP=OLD` or `SHR` | Resolved from the system catalog. Missing is an allocation failure. |
| `DISP=MOD` | As above; created empty and cataloged if absent. |
| `DISP=NEW` | Created empty and cataloged. A name already cataloged fails allocation. It is labelled from its DD's `RECFM`/`LRECL` over its model's label (`DCB=dsname`, or the subparameters of `DCB=*.dd`/`*.step.dd`); `FBA` labels FB, `VBS` VB. With either still unknown, or `RECFM=U`, the label stays pending until the first `OPEN OUTPUT`. A model not in the catalog fails allocation (`DATASET_NOT_FOUND`). An existing dataset's label is never changed by its DD ([decision record](../../records/design/2026-10-12-jackal-dcb-attributes.md)). `LIKE=dsname` labels it from a cataloged model as `DCB=dsname` does, except that a KSDS model gives a KSDS (with a coded LRECL, unless RECFM is coded); `REFDD=*.dd` copies the RECFM and LRECL coded on that DD, as `DCB=*.dd` does ([decision record](../../records/design/2026-10-12-jackal-like-refdd.md)). |
| `DSN=&&NAME` | Job-scoped temporary dataset, kept apart from named datasets (its file is `&&NAME`), deleted at job end. |
| `DSN=*.STEP.DD` | Referback to an earlier step's DD. |
| `DSN=GDG(+n)`, `(0)`, `(-n)` | A relative generation, resolved against the GDG's active generations as the job first found them (GDGBIAS=JOB) to an absolute `GDG.GnnnnV00`. `(+n)` counts on from the newest; `(0)` and `(-n)` must name an active generation (else `DATASET_NOT_FOUND`); an undefined GDG fails with `GDG_BASE_NOT_FOUND`. A generation whose disposition at step end is `CATLG` rolls into the GDG; past `LIMIT` the oldest (`NOEMPTY`) or every active generation (`EMPTY`) rolls off, deleted under `SCRATCH`, left cataloged under `NOSCRATCH`. `KEEP` leaves it cataloged outside the GDG ([decision record](../../records/design/2026-10-12-jackal-gdg.md)). A generation whose disposition deletes it leaves the GDG. |
| `DSN=GDG` (a GDG base name) | Every active generation, as the job first found them, read as a concatenation in the GDG's order (`LIFO`, newest first, unless `DEFINE GDG` coded `FIFO`) or the DD's `GDGORDER`. Each generation is allocated and disposed with the DD's DISP, so `DISP=(OLD,DELETE)` empties the GDG. A GDG with no generations fails with `DATASET_NOT_FOUND` ([decision record](../../records/design/2026-10-12-jackal-gdg-all.md)). |
| `DISP=(…,DELETE)` | The dataset and its file are removed when the step ends. |
| `DISP=(…,PASS)` | Handed to later steps; a later DD naming it receives it, and its own disposition then applies. One the job created and never received is deleted at job end. |
| IDCAMS `DEFINE CLUSTER` | Catalogs a KSDS with the label its `RECORDSIZE` and `KEYS` give. |
| IDCAMS `DEFINE GENERATIONDATAGROUP` | Catalogs a GDG base: its `LIMIT`, `EMPTY`/`NOEMPTY` (default `NOEMPTY`), `SCRATCH`/`NOSCRATCH` (default `NOSCRATCH`), `FIFO`/`LIFO` (default `LIFO`) and its active generations, none yet. A name already cataloged, as a dataset or a GDG, ends the command with condition code 12 ([decision record](../../records/design/2026-10-12-jackal-gdg.md)). |

Supported organisations are sequential (PS) and VSAM KSDS, read directly or through a path.
DSN types are in `jackal.model`; the catalog's one in-place table is `catnip.catalog_stores`.

## Utilities

`jackal.utilities.UTILITIES` registers the emulated programs.

| Program | Behaviour |
|---|---|
| `IEFBR14` | Does nothing; the runner's allocation and disposition do its work. Return code 0. |
| `IKJEFT01`, `IKJEFT1A`, `IKJEFT1B` | The TSO monitor. Each `RUN PROGRAM(p)` in SYSTSIN's DSN session runs `p` as the step's program, with the step's DDs; its EXEC SQL is served by the runner's injected coprocessors (`PLAN` is not used). The step's code is the highest program code. A program abend ends the session: 12 under IKJEFT01, S04C under IKJEFT1A/1B. A monitor step with no RUN keeps the missing-program path ([decision record](../../records/design/2026-10-12-jackal-tso-run-program.md)). |
| `IDCAMS` | Parses the in-stream `SYSIN`, each record between columns 2 and 72, and executes it; `REPRO` reads and writes the datasets its DDs were allocated, each at its own label, a concatenated input member after member; an input (or member) whose label is still pending, or an output that is also an input, ends that `REPRO` with condition code 12 and the next command runs; a DUMMY input is an immediate end of file (the output is left empty) and a DUMMY output discards the records. Return code is the final MAXCC. |

The IDCAMS executor (`jackal.idcams.executor`) handles `DELETE`, `DEFINE CLUSTER`,
`DEFINE GENERATIONDATAGROUP` (`DEF GDG`), `REPRO`, `VERIFY` (`VFY`), and the modal commands:
`IF {LASTCC|MAXCC} op n THEN … ELSE …` with `DO … END` blocks, nesting and null clauses,
`SET {MAXCC|LASTCC}` and `CANCEL`. A line ends a command unless a `-` continues it, so a THEN or
ELSE ending its line is null; each ELSE takes the nearest unmatched THEN. SET caps at 16, and a
16 ends the stream. `VERIFY` of a KSDS (by DD or by name) gives 0, anything else 12
([decision record](../../records/design/2026-10-12-jackal-idcams-modal.md)). The parser
(`jackal.idcams.parser`) reads every IDCAMS command through one Lark grammar,
`jackal/jackal/idcams/grammar/ams.lark`. A record ends a command unless `-` or `+` continues it.
Blanks, commas and comments separate, and every keyword accepts its IBM abbreviation. The
transformer builds only what the executor runs, from the parameters execution reads. Storage
and performance parameters (space, VOLUMES, CISZ, FREESPACE, SHAREOPTIONS and the like) are
dropped. A command jackal does not run (LISTCAT, PRINT, ALTER, EXPORT, IMPORT, DEFINE NONVSAM,
the alternate-index toolchain, a non-KSDS DEFINE CLUSTER), or one coding a parameter that would
change what it does (REPRO `COUNT`, DEFINE CLUSTER `MODEL`, DELETE of a GDG base, and so on), is
`NotExecuted` and ends with condition code 12; the next command runs. A DELETE of several entries
ends with the highest of their codes
([decision record](../../records/design/2026-10-12-jackal-idcams-one-grammar.md)). The IDCAMS
command reference is [idcams-ref.pdf](idcams-ref.pdf).

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
| `jackal/jackal/file_definitions.py` | The files each program in an image declares, read from its file-definitions `Data` directives, each with its `program`. |
| `jackal/jackal/program_files_provider.py` | `ProgramFilesIOProvider`: hands each COBOL file call to the provider of the program that made it. |
| `jackal/jackal/cobol_step.py` | Runs a COBOL step on the red-dragon VM. |
| `jackal/jackal/cobol_files.py` | jackal's COBOL file handler: red-dragon's, with a `DISP=MOD` file opened to append and each `OPEN` checked against the dataset's label. |
| `jackal/jackal/record_format.py` | The record format a COBOL FD asks for, and its fit with a label. |
| `jackal/jackal/utilities.py` | The utility table: IEFBR14, IDCAMS. |
| `jackal/jackal/tso_step.py` | A TSO monitor step's DSN session: one RUN PROGRAM after another. |
| `jackal/jackal/catalog.py` | One job's dataset catalog: the system's datasets, temps, `PASS`, DISP lifecycle. |
| `jackal/jackal/dcb_label.py` | A new dataset's label from its DD's DCB, `LIKE` or `REFDD` and its model. |
| `jackal/jackal/concatenated_records.py` | A concatenation read member after member as one file. |
| `jackal/jackal/cond.py` | `COND=` evaluation, and the order of every gate. |
| `jackal/jackal/if_guard.py` | `IF/THEN/ELSE` condition evaluation. |
| `jackal/jackal/model.py`, `results.py` | Immutable job model, DSN types and step results. |
| `jackal/jackal/value_parts.py` | Literal and symbolic value parts. |
| `jackal/jackal/unresolved.py` | What the runner does with unresolved references (D7). |
| `jackal/jackal/missing_data.py` | What the runner does with a DD it cannot allocate. |
| `jackal/jackal/missing_program.py` | What the runner does with a program it cannot find. |
| `jackal/jackal/parm.py` | `PARM=` region for COBOL `LINKAGE`. |
| `jackal/jackal/tso.py` | Reads the programs a TSO batch step runs from its `SYSTSIN`. Used by cobble. |
| `jackal/jackal/jcl/` | JCL parsing through the bridge JAR; procedure expansion. |
| `jackal/jackal/idcams/` | The IDCAMS grammar (`grammar/ams.lark`), parser, command types and executor. |
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
