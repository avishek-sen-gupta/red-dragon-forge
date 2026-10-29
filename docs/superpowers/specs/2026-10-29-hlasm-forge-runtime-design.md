# HLASM at run time in forge: outcomes, JCL steps, floating point, CICS calls

Part of red-dragon-6lic. Forge builds HLASM into every package, but at run time it only treats
assembler as a COBOL callee in plain mode. This design covers the next four slices, run
unattended, so each decision is made here.

## Goals

1. **Outcomes.** Plain and JCL runs report an HLASM program's return code (R15's low word) and
   its abend (SVC 13 or a program check), for an HLASM main and for HLASM called from COBOL.
2. **JCL step programs.** `EXEC PGM=<asm>,PARM='...'` runs an HLASM main, its PARM reaching it
   through red-dragon's job-step PARM list. JCL runs get the HLASM run inputs (clock with
   STIMER's wait, no DDs) that plain runs already have.
3. **Floating point.** Plain and JCL runs compose red-dragon's BFP, HFP, DFP and PFPO builtins.
4. **CICS.** A CICS COBOL transaction `CALL`s an HLASM subprogram from a forge package, and
   `[cics]` regions get the HLASM run inputs.

## Non-goals

- DD-based QSAM (`OPEN`/`GET`/`PUT` on DCBs). When it comes, plain mode takes DD names from
  `[plain.files]` (user decision, 2026-10-29); JCL from the step's DDs.
- SYSIN (red-dragon-f8pe), EXEC CICS from assembler, HLASM abend reporting under CICS.
- A `parm` key for `[plain]`: plain HLASM mains keep the empty PARM.

## Constraints

- No import-linter relaxation in either repo. Forge may import `interpreter.hlasm*` (no
  contract forbids it); red-dragon's `run()` stays untouched.
- No vendoring of GPL or unlicensed code. Test programs are our own, in forge fixtures, or
  CardDemo's (Apache-2.0, our fork).
- red-dragon and forge guidelines apply: frozen dataclasses, no `Any`, one-line module
  headers only, few whole-behaviour tests with concrete assertions, Talisman rules.
- Commits carry no attribution trailers.

## Decisions

### Outcomes (red-dragon, then forge)

- red-dragon exposes readers in a new module `interpreter/hlasm/hlasm_outcome.py`:
  - `hlasm_return_code(vm: VMState) -> int` — R15's low word, unsigned, from `__hlasm_gprs`
    (offset 124, 4 bytes, big-endian).
  - `hlasm_abend(vm: VMState) -> tuple[SystemAbend | UserAbend, ...]` — empty when
    `__hlasm_abend` is absent (no HLASM in the image) or `""`; `S` + hex parses to
    `SystemAbend`, `U` + decimal to `UserAbend` (`infrastructure.zos.abend`). Same tuple
    shape as COBOL's `user_abend`.
- The entry program's language is passed as data, never deduced from a label string:
  red-dragon adds `program_language(linked: LinkedProgram, name: str) -> Language`, reading
  `LinkedProgram.modules[...]`'s `language` and `program` fields.
- Forge's `zos` package (shared by plain mode and jackal) gets one function that turns a
  finished VM into the step result: abends are COBOL's `user_abend` plus `hlasm_abend`; the
  return code is `hlasm_return_code` when the entry program is HLASM, else `read_return_code`.
  Plain mode and jackal's `cobol_step` both use it.
- A COBOL program calling HLASM that abends reports the HLASM abend.

### JCL step programs (forge)

- `jcl_command` composes `clock_builtins(SystemMachineClock(...))` and `dd_builtins(NO_DDS)`
  per run. PARM is per step: jackal composes `job_parm_builtins(resolve(step.parm))` (or
  `NO_PARM`) into the step's builtins in `runner._ran`/`run_cobol_step`, since
  `compose_builtins` refuses duplicate names and the table is otherwise per run.
- jackal's COBOL-linkage PARM frame (`_parm_vm`) stays for COBOL mains. An HLASM main gets
  its PARM only through `__hlasm_job_parm`.

### Floating point (forge)

- Plain and JCL compose `bfp_builtins()`, `hfp_builtins()`, `dfp_builtins()` and
  `pfpo_builtins()` from `interpreter.hlasm`.

### CICS (forge)

- `[cics]` regions get `unsupplied_run_input_builtins()` and the four FP builtin tables in
  `other_builtins`, composed by one function in `cics_command` that the test also uses.
- The test builds a package with an inline CICS COBOL program that `CALL`s CardDemo's
  MVSWAIT and `SEND TEXT`s whether it waited, then drives one transaction through the
  region built from that package (pattern: `cicada/tests/integration/cics/test_region_from_package.py`).

## Targets

No open corpus exercises these (searched 2026-10-27; the one Apache-2.0 candidate carries
IBM "restricted materials" headers). Each slice uses small fixture programs written for it:
an HLASM main that sets R15 from its PARM, one that abends, a COBOL driver calling an HLASM
routine that abends, an HLASM FP routine returning BFP, HFP and DFP results to a COBOL
driver, and the CICS COBOL caller above.

## Left to the builder

File names of fixtures and tests, how the JCL test drives forge-run `[jcl]` (follow forge's
existing JCL integration tests), and the exact FP values (any whose expected result is
derived by hand in the test).
