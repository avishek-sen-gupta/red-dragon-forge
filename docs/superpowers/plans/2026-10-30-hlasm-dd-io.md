# HLASM DD file I/O in forge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HLASM programs in `[plain]` and `[jcl]` runs read and write the datasets their DDs name.

**Architecture:** One `zos` function turns a DDNAME-to-`Dataset` mapping into red-dragon `DdDefinition`s; a new DDNAME-keyed file provider serves HLASM's file calls (program `""`) beside the per-program COBOL providers. Plain mode feeds both from `[plain.files]`; jackal feeds both per step from the step's DD environment.

**Tech Stack:** Python 3.13, uv, pytest, red-dragon VM (vendored), catnip, jackal, zos.

**Spec:** `docs/superpowers/specs/2026-10-30-hlasm-dd-io-design.md`

## Global Constraints

- No import-linter relaxation in either repo. No red-dragon changes unless the wiring finds a defect there.
- No GPL or unlicensed code; fixtures are our own.
- Frozen dataclasses, no `Any`, one-line module/class headers only, few whole-behaviour tests with concrete assertions; mutation-check each new test two ways.
- Talisman rules; no attribution trailers in commits. Push forge main after each green commit.
- Forge gate: its pre-commit hook (~25 min). Source `./bridge-env.sh` before running forge tests by hand.

## Review Focus

1. A run mixing a COBOL program's files and an HLASM program's DDs: each program's calls reach its own provider (Task 1 test: COBOL driver with its own FD file calls an HLASM routine that copies `INDD` to `OUTDD`).
2. A V dataset written by HLASM then read by COBOL: label LRECL is frame length + 4, so COBOL's OPEN does not fail with status 39 (Task 2 test, VB variant of step 1).
3. `[plain.files]` naming a KSDS: the HLASM OPEN returns R15 8, not S013 (Task 1 unit test of `dd_definitions`).
4. A `DISP=MOD` DD opened OUTPUT by HLASM appends (Task 2: assert in the provider unit test).
5. An HLASM OPEN INPUT of a pending (never written) dataset: R15 8 (Task 1 plain test).

---

### Task 1: shared DD wiring and plain mode

**Files:**
- Create: `zos/zos/cobol/io/dd_definitions.py`, `zos/zos/cobol/io/dd_files.py`; unit tests beside the existing `zos` tests; fixtures under `tests/integration/fixtures/hlasm_dd/`; `tests/integration/test_hlasm_dd_plain.py`
- Modify: `zos/zos/cobol/io/program_files.py`, `red_dragon_forge/plain_mode.py`, `red_dragon_forge/plain_command.py`, `jackal/jackal/cobol_step.py` (new constructor argument only), `jackal/tests/unit/test_program_files_provider.py`, `docs/reference/forge/run.md`, `docs/reference/forge/architecture.md`

**Interfaces:**
- Produces:
  - `dd_definitions(datasets: Mapping[str, Dataset]) -> Mapping[str, DdDefinition]` — only `SequentialLabel` and `LabelPending` datasets; catnip `RecordFormat` F/FB/V/VB → red-dragon `RecordFormat` of the same name with the label's LRECL; pending → `UNSPECIFIED`, 0; BLKSIZE 0.
  - `class DdFileIOProvider(DatasetFileIOProvider)`: `__init__(self, base_dir: Path, bindings: FileBindings, relabeller: Relabeller)`. Keyed by DDNAME: path overrides and datasets from `bindings`, `bindings.appended` makes OUTPUT open as EXTEND. Admits an open from the declared `FileFrame` (`variable`, `record_length`): a pending label with OUTPUT/EXTEND is labelled `SequentialLabel(F, record_length)` or `SequentialLabel(V, record_length + 4)` through the relabeller; otherwise the existing `conflicting` check against `FixedFormat(record_length)` / `VariableFormat(record_length + 4)`.
  - `ProgramFilesIOProvider(programs, provider_for, files, hlasm: CobolIOProvider)` — calls whose program is `""` (`interpreter.hlasm_run_inputs.declare_file_builtins.NO_PROGRAM`) go to `hlasm`.

- [ ] **Step 1: Failing tests.**
  - Unit, `dd_definitions`: one mapping holding an FB 80 dataset, a VB 104 dataset, a pending one and a KSDS → `{"A": DdDefinition(pa, FB, 80), "B": DdDefinition(pb, VB, 104), "P": DdDefinition(pp)}`.
  - Unit, `ProgramFilesIOProvider`: a declare and open with program `""` reach the `hlasm` provider (extend the existing test file).
  - Integration, plain (subprocess forge-run, as `tests/integration/test_mvswait_plain.py`): HLASM main `DDCOPY` copies `INDD` to `OUTDD` until EODAD, then returns R15 0. `INDD` is a cataloged FB 80 dataset of three records; `OUTDD` a cataloged, still-pending dataset. Assert stdout `RC 0`, the output bytes equal the input bytes, and the catalog now labels `OUTDD`'s dataset `SequentialLabel(F, 80)`. Repeat with VB (RDW-prefixed records of different lengths, LRECL 104): output equals input; label `SequentialLabel(V, 104)`.
  - Integration, plain: a COBOL driver with its own FD file writes one record, then calls the copy routine as a subprogram; both outputs are right (Review Focus 1).
  - Integration, plain: `DDCOPY` with `INDD` absent from `[plain.files]`, and separately with `INDD` pending: the program sees R15 8 from OPEN and returns it; stdout `RC 8`.
- [ ] **Step 2: Run; expect import failures and `KeyError: ''`.**
- [ ] **Step 3: Implement** the three interfaces. Plain mode: `run_plain` builds `DdFileIOProvider(Path(scratch), bindings, CatalogRelabeller(catalog))` as `hlasm`, and composes `dd_builtins(dd_definitions(bindings.datasets))` onto `builtins`; `plain_command` replaces `unsupplied_run_input_builtins()` with `run_input_builtins(SystemMachineClock(wall_ns=time.time_ns, cpu_ns=time.process_time_ns, sleep=time.sleep), NO_PARM)` so the DD builtin is not composed twice. `cobol_step` passes a `DdFileIOProvider` built from the step's bindings (Task 2 tests it).
- [ ] **Step 4: Run** `uv run pytest tests/integration/test_hlasm_dd_plain.py zos jackal/tests/unit -q` → pass. Mutation-check: drop the `+ 4`; route `""` to the first COBOL provider.
- [ ] **Step 5: Commit** spec, plan, code, tests, docs. Push forge main.

### Task 2: JCL step DDs

**Files:**
- Modify: `jackal/jackal/cobol_files.py` (make `_bindings(env)` public as `bindings_of(env: DdEnvironment) -> FileBindings`), `jackal/jackal/cobol_step.py`, `jackal/jackal/runner.py`, `red_dragon_forge/jcl_command.py`, `docs/reference/forge/architecture.md`
- Create: `tests/integration/test_hlasm_dd_jackal.py`, a COBOL reader fixture under `tests/integration/fixtures/hlasm_dd/`

**Interfaces:**
- Consumes: Task 1's `dd_definitions`, `DdFileIOProvider`, `ProgramFilesIOProvider(..., hlasm)`.

- [ ] **Step 1: Failing test** (pattern: `tests/integration/test_hlasm_outcome_jackal.py`): a two-step job. Step 1 `EXEC PGM=DDWRITE` with `//OUTDD DD DSN=APP.OUT,DISP=(NEW,CATLG),RECFM=FB,LRECL=80` writes three fixed records. Step 2 `EXEC PGM=DDREAD` (COBOL) with `//INDD DD DSN=APP.OUT,DISP=SHR` reads and `DISPLAY`s each. Assert step outcomes `[Completed(0), Completed(0)]` and the displayed lines. Second test: the same with VB, LRECL 104, records of different lengths (Review Focus 2). Third: a step 1 DD `DISP=MOD` on an existing dataset appends (Review Focus 4).
- [ ] **Step 2: Run; expect OPEN failing (R15 8) because no DDs are supplied.**
- [ ] **Step 3: Implement.** `runner._ran` composes `dd_builtins(dd_definitions(bindings_of(env).datasets))` beside `job_parm_builtins`; `jcl_command._run_inputs` drops `dd_builtins(NO_DDS)`; `run_cobol_step` builds `DdFileIOProvider(workdir, bindings_of(env), relabeller)` as `hlasm`.
- [ ] **Step 4: Run** the new tests, `tests/integration/test_hlasm_outcome_jackal.py` and `jackal/tests` → pass. Mutation-check: keep `NO_DDS` per run; build the DDs from the first step's env.
- [ ] **Step 5: Commit, push forge main.** Update red-dragon-6lic's notes; file a bead for the JCL non-dataset DDs (in-stream, SYSOUT, DUMMY, concatenations); push red-dragon.
