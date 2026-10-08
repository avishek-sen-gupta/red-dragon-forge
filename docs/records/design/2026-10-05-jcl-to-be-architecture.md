# jackal: To-Be JCL Execution Architecture

**Date:** 2026-10-05
**Status:** proposed. Not yet built; the migration is tracked in Beads under `jackal-1o2`.
**Companions:** the living roadmap [`jackal/docs/jcl-execution-roadmap.md`](../../jackal/docs/jcl-execution-roadmap.md)
(what to build, in census order) and this record (what shape it is built into).

---

## Why

jackal's control plane fits z/OS: step sequencing, `COND=` evaluation, referbacks, PROC expansion
as a pre-pass, and DD names bound to files inside the VM (`RealFileIOProvider.path_overrides`).
The data plane does not. z/OS keeps state at four levels — the **system** catalog, the **job**'s
datasets, the **step**'s allocations, the **dataset**'s own label — and jackal folds each level
into the one beneath it:

| As-is simplification | Where | What it blocks | Issue |
|---|---|---|---|
| A step's outcome is an `int` RC; a VM failure is a Python exception that escapes the job | `results.py`, `runner.py` | abend, `COND=EVEN/ONLY`, `IF (S.ABEND)`, abnormal DISP, "unsupported program" | `red-dragon-forge-5fu` |
| Each program kind runs its own allocate/dispose; in-stream and DUMMY DDs raise `TypeError` | `cobol_step.py`, `utilities.py`, `idcams/executor.py` | every new utility, DUMMY, concatenation, uniform DISP | `red-dragon-forge-lrk` |
| A dataset has no record format; the opener decides record boundaries | `catalog.Dataset`, red-dragon `SequentialDriver` | `RECFM=V/VB`, SORT/IEBGENER/REPRO, DCB inheritance | `red-dragon-forge-8in` |
| One job-scoped catalog stands in for system catalog, job context and step allocations | `catalog.py` | GDG, `CATLG`/`PASS`/`KEEP`, multi-job pipelines, temp name collisions | `red-dragon-forge-93f` |

The to-be architecture restores the four levels and makes the runner own the step lifecycle.
Nothing here aims at full z/OS fidelity; see [Non-goals](#non-goals).

## Principles

1. **Mirror z/OS's levels, no more.** System catalog, job dataset context, step allocations,
   dataset attributes, each its own component with its own lifetime. A JCL feature then lands
   on exactly the level z/OS puts it on.
2. **The executor owns the step lifecycle.** Allocate every DD, dispatch the program, apply
   dispositions by outcome. A program sees a DD environment and returns an outcome; it never
   allocates or disposes.
3. **Functional core, imperative shell.** The converter, the step gate, allocation planning and
   every control-language interpreter are pure functions over immutable values. Only the
   system catalog, the dataset store, the spool and the VM hold state.
4. **One plan for static and runtime.** cobble and the executor consume the same converter
   output, so the graph and the run agree on PROC expansion, temps and GDG generations.
5. **Outcomes are data.** Abend, bypass, flush and "unsupported" are values, not exceptions.

## Diagram

```
  JCL text
     │
     ▼
┌──────────────────────────┐
│ [1] Front end            │           ┌───────────────────────────┐
│   jcl-bridge → Job       │─JobPlan──►│ cobble jcl_graph (static) │
│ [2] Converter (pure)     │           └───────────────────────────┘
│   PROC/INCLUDE/symbols   │
│   IF guards, referbacks  │
└────────────┬─────────────┘
             │ JobPlan | JclError (no step runs)
             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ [3] Job executor                                                         │
│                                                                          │
│  [4] Step gate ──run──► [5] Step lifecycle ──outcome──► [13] Outcomes    │
│  COND / IF / EVEN /       a. allocate every DD              │            │
│  ONLY / flush             b. dispatch program               │            │
│       ▲                   c. dispose by outcome             │            │
│       └──────────────────────── history ────────────────────┘            │
└─────────┬───────────────────────────┬───────────────────────────┬────────┘
          │ a. DD → Allocation        │ b. DD env + PARM          │ c. DISP
          ▼                           ▼                           ▼ to [7] [8]
┌──────────────────────────┐  ┌──────────────────────────────────┐
│ [6] Allocator            │  │ [10] Program registry            │
│  Dataset | Concat |      │  │  COBOL load module + CALLs       │
│  InStream | Dummy |      │  │  IEFBR14                         │
│  Sysout ──► [12] Spool   │  │  IDCAMS, SORT, IEBGENER          │
└─────────┬────────────────┘  │     └──► [11] control languages  │
          │                   │  TSO monitor ──► port            │
          │                   │     (adapter: forge + squall)    │
          │                   │  stub | unsupported              │
          │                   └────────────────┬─────────────────┘
          │                                    │ records
          ▼                                    ▼
┌──────────────────────────┐  ┌──────────────────────────────────┐
│ [7] Job dataset context  │  │ [9] Dataset store + codec        │
│  unique temp names       │  │  attrs: DSORG RECFM LRECL        │
│  passed-dataset queue    │  │  F | FB | V | VB (RDW)           │
│  referback table         │  │  KSDS (key extent)               │
│  GDG relative bindings   │  │  seeds declare their attrs       │
└─────────┬────────────────┘  └──────────────────────────────────┘
          │                                    ▲
          ▼                                    │ storage + attrs
┌──────────────────────────┐                   │
│ [8] System catalog       │                   │
│  persists across jobs    │───────────────────┘
│  DSN → entry             │
│  GDG bases + generations │
│  VSAM clusters           │
└──────────────────────────┘
```

## Components

Each component lists what it owns, the JCL features it enables, and where it comes from.

### [1] Front end

**Owns:** text → typed `Job` (immutable `Job`/`Step`/`DD`, typed DSN variants). The jcl-bridge
JAR plus the deserializer in `jackal/jcl/bridge_parser.py`. Unchanged in shape.

**Enables:** every statement form reaching the model. Its open parse defects (`DCB=(dsn,…)`,
concatenation, `IF/THEN`) are tracked under `red-dragon-forge-2cy`.

### [2] Converter

**Owns:** the z/OS converter/interpreter phase, as a pure function `Job → JobPlan | JclError`.
PROC expansion (today `proc_expand.py`), `SET`/symbolic substitution, `INCLUDE`/`JCLLIB`, the
`IF/THEN/ELSE` structure as typed step guards, referback validation, duplicate step names, and
GDG references typed as relative generations.

**Enables:**
- **JCL errors before execution.** z/OS rejects the whole job before step one. Today a bad
  referback fails mid-job, after earlier steps have run.
- **`TYPRUN=SCAN`.** Run the converter, stop.
- **Static/runtime agreement.** cobble reads `JobPlan`, so the graph and the run share one
  expansion.

**From:** `jackal/jcl/proc_expand.py` plus the referback checks now inside `runner._resolve_step`.

### [3] Job executor

**Owns:** the step loop over a `JobPlan`; nothing else. It asks the gate whether a step runs,
hands it to the lifecycle, and appends the outcome to the history.

**Enables:** step sequencing; `RESTART=` later, as a start index into the plan.

**From:** `runner.JobRunner`, minus `_resolve_step`, `_record_dds` and `_run_step`.

### [4] Step gate

**Owns:** a pure function `(guards, outcome history) → Run | Bypass(reason) | Flush`.

**Enables:**
- `COND=` on JOB and EXEC, simple and compound.
- `IF (S.RC …)`, `S.ABEND`, `S.RUN`, `ABENDCC=`.
- `COND=EVEN`/`ONLY`.
- Flushing every later step after an abend.

**From:** `cond.py`, extended. It reads `Completed` outcomes for RC tests and `Abended` for abend
tests.

### [5] Step lifecycle

**Owns:** the z/OS initiator's sequence for one step:
1. Allocate every DD through [6].
2. Dispatch the program through [10] with the DD environment and PARM.
3. Dispose every allocation by outcome: the normal disposition after `Completed`, the abnormal
   one after `Abended`.

**Enables:**
- The full DISP matrix, uniformly for every program, including `(NEW,PASS,DELETE)`.
- `IEFBR14` as a genuine no-op program, since its effect is the lifecycle itself.
- "Allocation failed" (dataset not found, duplicate name) as a step outcome, not a crash.

**From:** the allocate/dispose code now in `cobol_step.py`, `utilities.iefbr14` and
`idcams/executor._handle_repro`. Issue `red-dragon-forge-lrk`.

### [6] Allocator

**Owns:** DD → typed `Allocation`:

| Allocation | From | Read | Write |
|---|---|---|---|
| `DatasetAllocation` | `DSN=` | records via [9] | records via [9]; `DISP=MOD` positions at end |
| `Concatenation` | named DD + unnamed `DD`s | each member in order | first member |
| `InStream` | `DD *` / `DD DATA` | the card images, as a dataset | — |
| `Dummy` | `DD DUMMY`, `DSN=NULLFILE` | immediate EOF | discarded |
| `Sysout` | `SYSOUT=c` | — | to [12] |

Planning is pure. Materialising goes through [7] and [8], which are shell.

**Enables:** `DD DUMMY` (the census's ≥47%), in-stream input for any program, concatenation, the
`DISP=MOD` append, DCB merge (program, then DD, then dataset label), and `DCB=*.dd` /
`DCB=(model,…)` inheritance.

### [7] Job dataset context

**Owns:** state that lives exactly as long as one job:
- Temp datasets under system-unique names, so `&&EXTR` never collides with a real `EXTR`.
- The passed-dataset queue (`PASS` and the receiving step).
- The referback table (`*.STEP.DD`, `DCB=*.STEP.DD`).
- GDG relative-to-absolute bindings, fixed at first use. In z/OS, `(+1)` names the same
  generation in every step of one job, and `(0)` keeps meaning the generation that was current
  when the job started.

**Enables:** `&&temp` chaining (the dominant step-to-step idiom), `PASS` semantics (unreceived
passed datasets deleted at job end), referbacks, and GDG within a job.

**From:** `catalog._temp_registry`, `catalog.cleanup_temps`, `runner.resolved_dds`. Issue
`red-dragon-forge-93f`.

### [8] System catalog

**Owns:** state that outlives a job, injected and shared across the jobs of one run:
- DSN → entry (storage location + attributes from [9]).
- GDG bases (`LIMIT`, `SCRATCH`/`NOSCRATCH`, `EMPTY`) with ordered generations.
- VSAM clusters. PDS members later.

**Enables:**
- `CATLG`, `UNCATLG`, `KEEP`, and `DELETE` of cataloged datasets.
- Duplicate-name failure on `DISP=NEW`.
- GDG rolling at step end against `LIMIT`.
- IDCAMS `DEFINE`/`DELETE`/`LISTCAT`/`ALTER` as catalog operations.
- Multi-job pipelines: job A catalogs, job B reads.

**From:** the persistent half of `catalog.DatasetCatalog`; seeds become pre-cataloged entries
with declared attributes. Issue `red-dragon-forge-93f`.

### [9] Dataset store + record codec

**Owns:** a dataset's attributes (DSORG, RECFM, LRECL, BLKSIZE; key extent for KSDS), set once
at creation and read by every later opener. The codec frames records on disk per RECFM:
- Fixed: raw concatenation, as today.
- Variable: RDW-prefixed.
- KSDS: red-dragon's `IndexedDriver`.

**Enables:**
- `RECFM=V/VB`.
- Utilities that have no FD (SORT, IEBGENER, REPRO) learning record length from the dataset.
- DCB inheritance.
- Retiring the `record_size` override (jackal-ifq).
- EBCDIC seed files read with their true layout.

**From:** `catalog.Dataset` and `catalog.open_dataset`, plus red-dragon's file drivers. Issue
`red-dragon-forge-8in`.

### [10] Program registry

**Owns:** `PGM=` → a `Program` with one contract, `(DD environment, PARM) → StepOutcome`.
Implementations:

| Program | Adapter | Enables |
|---|---|---|
| COBOL load module | compiles the main program **and** its `CALL` closure (`compile_cobol(..., source_search_dirs=…)`); maps the DD environment onto `path_overrides`; maps VM failure to `Abended` | batch COBOL with subprograms, `PARM=`, `RETURN-CODE` |
| `IEFBR14` | nothing; the lifecycle does the work | GDG pre-create, emptying a dataset |
| `IDCAMS`, `SORT`, `IEBGENER`, `IEBCOPY` | read the control statements from the SYSIN allocation, run [11] | the utility layer |
| TSO monitor (`IKJEFT01/1A/1B`) | parses SYSTSIN (`jackal/tso.py`), calls an injected **port** for `RUN PROGRAM`; forge supplies the adapter composing squall | DB2 batch steps (26% of census jobs), without jackal importing squall |
| Stub | a declared outcome, per the stub policy (an open decision) | file transfer, operator messaging, stats packages |
| Unsupported | `Unsupported(pgm)` | an honest result where today's code raises a file-not-found error |

**From:** `runner._run_step`, `utilities.UTILITIES`, `cobol_step.py`. Issue `red-dragon-forge-xkk`.

### [11] Control-language interpreters

**Owns:** one parser + pure interpreter per embedded language: AMS (IDCAMS), DFSORT control
statements, IEBGENER control, TSO commands. Each takes control statements and a typed view of
its DD environment, and returns operations for its program adapter to apply.

**Enables:**
- IDCAMS `VERIFY`/`REPRO`/`DEFINE`/`DELETE` and `IF LASTCC … THEN DO … END`.
- SORT `FIELDS`/`INCLUDE`/`OMIT`/`OUTREC`/`SUM`/`OPTION COPY`.
- IEBGENER copy. `$DJDE$` lines stay record data, never parsed.

**From:** `jackal/idcams/` (the comprehensive parser, wired in); new siblings for SORT and
IEBGENER.

### [12] Spool

**Owns:** `SYSOUT` output, captured per (step, ddname, class), with `OUTPUT` statement
descriptors attached.

**Enables:** report capture and assertions on it, utility message output (`SYSPRINT`), and the
`OUTPUT` statement and `OUTPUT=(*.x)` references. Dump DDs come later.

**From:** nothing; today SYSOUT DDs are skipped.

### [13] Outcome model

**Owns:** `StepOutcome = Completed(rc) | Abended(code) | Bypassed(reason) | Flushed |
Unsupported(pgm) | AllocationFailed(dd, reason)`, plus a `JobResult` with the job-level outcome
(max RC, abending step) and the spool.

**Enables:** everything [4] and [5] read; honest results for partial runs.

**From:** `results.py`. Issue `red-dragon-forge-5fu`.

## Feature → component map

| JCL feature | Components | Issue |
|---|---|---|
| Step sequencing | 3 | ✅ |
| `COND=` (JOB, EXEC, compound) | 4, 13 | ✅ evaluation; outcome typing in `5fu` |
| `IF/THEN/ELSE`, `EVEN`/`ONLY`, abend flush | 2, 4, 13 | `1o2.8`, `2cy.7`, `5fu` |
| PROC, symbolics, `INCLUDE`/`JCLLIB` | 2 | `1o2.2`, `1o2.15` (P4) |
| JCL error before execution, `TYPRUN=SCAN` | 2, 13 | `1o2.26` |
| Referbacks (`DSN=`, `DCB=`) | 2, 7 | ✅ DSN; DCB in `8in` |
| `&&temp` + `PASS` | 6, 7 | ✅ temps; PASS in `93f` |
| DISP matrix (normal + abnormal) | 5, 7, 8, 13 | `lrk`, `93f` |
| `DD DUMMY`, in-stream for any program | 5, 6 | `1o2.14`, `lrk` |
| Concatenation | 1, 6 | `2cy.3`, `1o2.5` |
| DCB / RECFM / LRECL, `DCB=(model,…)` | 6, 9 | `1o2.12`, `8in` |
| GDG `(+n)`/`(0)`/`(-n)`, IEFBR14 pre-create | 2, 7, 8, 10 | `2cy.4`, `1o2.4`, `93f` |
| VSAM KSDS | 8, 9 | ✅ |
| IDCAMS verbs incl. `VERIFY` | 10, 11, 8 | `vqa`, `1o2.6` |
| SORT, IEBGENER | 9, 10, 11 | `1o2.3` |
| COBOL `CALL` subprograms | 10 | `red-dragon-forge-355` |
| DB2 via `IKJEFT01` | 10 (+ forge adapter) | `46d` |
| Stubs / unsupported programs | 10, 13 | `xkk` |
| SYSOUT, `OUTPUT`, dump DDs | 6, 12 | `1o2.7`, `1o2.27`, `1o2.20` |
| Multi-job pipelines | 8 | `93f` |

## Worked example

A job shape typical of the census corpus, traced through the components:

```
//VERIFY  EXEC PGM=IDCAMS                         VFY FILE(MASTER)
//EXTRACT EXEC PGM=SORT,COND=(0,NE)               SORTIN=PROD.TRANS  SORTOUT=&&EXTR
//PRECRT  EXEC PGM=IEFBR14,COND=(0,NE)            NEWGEN DD DSN=PROD.HIST(+1),DISP=(NEW,CATLG)
//REPORT  EXEC PGM=RPTPGM,COND=(0,NE)             IN=&&EXTR  OUT=PROD.HIST(+1),DISP=OLD
//DB2UPD  EXEC PGM=IKJEFT01,COND=(0,NE)           RUN PROGRAM(UPDPGM) PLAN(UPDPLN)
```

1. **[2]** binds `PROD.HIST(+1)` to one absolute generation for the whole job via **[7]**, and
   types the guards. The plan goes to cobble unchanged.
2. **VERIFY:**
   - **[4]** runs it: there is no history yet.
   - **[5]/[6]** allocate `MASTER` from **[8]**. A missing dataset gives `AllocationFailed`;
     there is no crash.
   - **[10]/[11]** run AMS `VERIFY` and return `Completed(0)`.
3. **EXTRACT:**
   - **[4]** evaluates `COND=(0,NE)` against `Completed(0)` and runs the step.
   - **[6]** allocates `&&EXTR` under a unique name in **[7]**.
   - SORT reads LRECL from `PROD.TRANS`'s attributes in **[9]**; it has no FD to ask.
   - **[5]** applies `PASS` in **[7]**.
4. **PRECRT:** **[10]** does nothing. **[5]** allocates the new generation and catalogs it at
   step end in **[8]**, rolling the base against `LIMIT`.
5. **REPORT:**
   - COBOL, linked with any `CALL`ed subprograms.
   - `&&EXTR` is received from **[7]**.
   - `DISP=OLD` on `(+1)` resolves to the same generation PRECRT created.
   - If the program abends, **[13]** records `Abended(U4038)` and **[5]** applies the abnormal
     dispositions.
6. **DB2UPD:**
   - After that abend, **[4]** flushes it: its COND has no `EVEN`.
   - On a normal run, **[10]** passes `UPDPGM`/`UPDPLN` to the injected port, which forge
     implements with squall.

## As-is → to-be module map

| Today | Becomes |
|---|---|
| `jackal/jcl/bridge_parser.py`, `parser.py` | [1], unchanged |
| `jackal/jcl/proc_expand.py` | part of [2] |
| `runner.py` | [3]; `_resolve_step`/`_record_dds` move to [2]/[7], `_run_step` to [10] |
| `cond.py` | [4] |
| `catalog.py` | split into [7], [8], [9] |
| `cobol_step.py` | the COBOL adapter in [10]; its allocate/dispose moves to [5] |
| `utilities.py`, `idcams/executor.py` | adapters in [10] + [11]; allocation removed |
| `tso.py` | shared by cobble and the TSO adapter in [10] |
| `results.py` | [13] |
| — | new: [5], [6], [12], the TSO port |

The `.importlinter` layered contract changes with it. Proposed order, top to bottom:
executor → lifecycle → programs → allocator → job context → system catalog → dataset store →
model. Programs never import the lifecycle or the executor.

## Migration order

Each step is an independently committable unit that keeps the suite green:

1. **[13] outcomes** (`5fu`). Small, and every later step writes outcomes.
2. **[5] + [6] lifecycle and allocator** (`lrk`). Fixes in-stream and DUMMY for COBOL steps,
   and moves allocation out of the programs.
3. **[10] dispatch** (`xkk`, `355`). The registry contract, unsupported programs, stubs; the COBOL
   `CALL` closure.
4. **[9] dataset attributes + codec** (`8in`), then DCB (`1o2.12`), then SORT/IEBGENER
   (`1o2.3`).
5. **[7] + [8] catalog split** (`93f`), then GDG (`1o2.4`).
6. **[2] converter** as its own phase, absorbing `proc_expand` and referback checks. It can land
   any time after step 1; cobble switches to `JobPlan` in the same commit.
7. **[12] spool** (`1o2.7`) when report capture is needed.

## Open decisions

These belong to the user, not to the implementer:

- **Variable-record storage.** RDW bytes inline (z/OS-faithful, binary-compatible with real
  extracts) or a sidecar record index (simpler drivers, not byte-faithful).
- **Where the codec lives.** jackal wrapping red-dragon's drivers, or upstream in red-dragon's
  `file_drivers.py`. `vendor/red-dragon` is never modified here, so upstream means a red-dragon
  change first.
- **System catalog persistence.** In memory for one run of several jobs, or on disk so separate
  invocations share it.
- **Stub policy** (`xkk`). RC 0 and continue, a configurable RC, or stop the job.
- **Mapping VM failures to abends.** Which red-dragon failures become which `Sxxx`/`Uxxx`
  codes, and whether `STOP RUN` with a nonzero `RETURN-CODE` stays `Completed`.
- **`JobPlan` as a new type or the existing `Job`.** A new type keeps "converted" visible to the
  checker; reusing `Job` touches fewer call sites.

## Non-goals

JES2 scheduling and concurrent jobs; `SHR`/`OLD` enqueue contention; `SPACE`/`UNIT`/`VOL`
beyond no-ops; security (RACF); tape; checkpoint/restart beyond `RESTART=` at step granularity.
