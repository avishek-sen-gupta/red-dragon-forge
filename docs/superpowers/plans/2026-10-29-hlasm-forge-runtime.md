# HLASM at run time in forge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forge reports HLASM outcomes, runs HLASM JCL step programs with PARM, composes the FP builtins, and lets CICS COBOL call HLASM.

**Architecture:** red-dragon exposes outcome readers and the entry program's language; forge's shared `zos` package turns a finished VM into a step result for plain mode and jackal; run-input and FP builtins are composed per mode, PARM per JCL step.

**Tech Stack:** Python 3.13, uv, pytest, red-dragon VM, che4z HLASM bridge, ProLeap COBOL bridge.

**Spec:** `docs/superpowers/specs/2026-10-29-hlasm-forge-runtime-design.md`

## Global Constraints

- No import-linter relaxation in either repo; red-dragon's `run()` untouched.
- No GPL or unlicensed code; fixtures are our own or CardDemo's.
- One-line module/class headers only; frozen dataclasses; no `Any`; concrete assertions; mutation-check each new test.
- No attribution trailers in commits. Push to main after each green commit.
- red-dragon gate: `make test` via its pre-commit hook (~9 min). Forge gate: its pre-commit hook (~25 min); source `./bridge-env.sh` before running forge tests by hand.
- After a red-dragon commit that forge needs: bump `vendor/red-dragon` in the same forge commit as the code using it.

## Review Focus

1. A COBOL main whose HLASM callee abends: the HLASM abend is reported, not RC 0.
2. A pure-HLASM image (no COBOL unit): no `RUN_UNIT_VAR`, so `read_return_code` must not be called.
3. JCL step with no `PARM=`: the HLASM main sees an empty PARM, not an unresolved call.
4. Two JCL steps with different PARMs in one job: each step sees its own.
5. HLASM main that never sets R15: report what the register holds (check `enter_registers`) and pin it in a test.

---

### Task 1: red-dragon outcome readers and entry language

**Repo:** red-dragon.

**Files:**
- Create: `interpreter/hlasm/hlasm_outcome.py`, `tests/integration/hlasm/test_hlasm_outcome.py`
- Modify: wherever `program_language` fits best beside `LinkedProgram` (`interpreter/project/`), and `docs/frontend-design/hlasm.md`

**Interfaces:**
- Produces: `hlasm_return_code(vm: VMState) -> int`; `hlasm_abend(vm: VMState) -> tuple[SystemAbend | UserAbend, ...]`; `program_language(linked: LinkedProgram, name: str) -> Language`.

- [ ] Step 1: Write failing integration tests (compile real HLASM through `compile_hlasm`/`run_linked`, as `tests/integration/hlasm/hlasm_helpers.py` does): an HLASM main returning R15=8 → `hlasm_return_code == 8`, `hlasm_abend == ()`; `ABEND 42` → `(UserAbend(42),)`; a program check (e.g. `DC H'0'` executed) → `(SystemAbend(0x0C1),)`; a COBOL-only image → `hlasm_abend == ()`; `program_language` gives HLASM for the assembler program and COBOL for a COBOL one in one mixed image.
- [ ] Step 2: Run them; expect import failures.
- [ ] Step 3: Implement. Parse the abend text once at the reader (`S`+hex, `U`+decimal). Read `__hlasm_gprs`/`__hlasm_abend` from `vm.call_stack[0].local_vars` as the helpers do.
- [ ] Step 4: Run; pass. Mutation-check two ways (wrong offset; abend parse swapped).
- [ ] Step 5: Commit, push red-dragon main.

### Task 2: forge outcome reporting in plain and JCL

**Repo:** forge. Bump `vendor/red-dragon` to Task 1's commit. Commit this spec and plan with this task.

**Files:**
- Create: one function in `zos/zos/` (e.g. `zos/zos/program_outcome.py`) returning the step's abends and return code; fixtures under `tests/integration/fixtures/hlasm_outcome/`
- Modify: `red_dragon_forge/plain_mode.py`, `jackal/jackal/cobol_step.py`, docs `docs/reference/forge/architecture.md`

**Interfaces:**
- Consumes: Task 1's three functions.
- Produces: the shared outcome function used by plain mode and jackal.

- [ ] Step 1: Failing plain-mode tests (subprocess forge-run, like `tests/integration/test_mvswait_plain.py`): HLASM main returning R15=8 → stdout `RC 8`, exit 0; HLASM main `ABEND 42` → `U0042`, exit 1; COBOL driver calling an HLASM routine that abends → that abend.
- [ ] Step 2: Implement the shared function; switch plain mode and `cobol_step` to it.
- [ ] Step 3: Run forge tests touching plain mode and jackal; mutation-check.
- [ ] Step 4: Commit (spec, plan, bump, code, tests, docs), push forge main.

### Task 3: JCL HLASM step programs with PARM

**Repo:** forge.

**Files:**
- Modify: `red_dragon_forge/jcl_command.py`, `jackal/jackal/runner.py` and/or `jackal/jackal/cobol_step.py`
- Create: fixture JCL and HLASM main(s); a JCL integration test following forge's existing `[jcl]` tests

- [ ] Step 1: Failing test: a two-step job; step 1 `EXEC PGM=<asm>,PARM='ABC'`, step 2 same program with `PARM='WXYZ'` and no PARM in a third step; the program returns its PARM length in R15; assert the step condition codes are 3, 4, 0. Plus an HLASM step that abends reports its abend.
- [ ] Step 2: Compose clock and `dd_builtins(NO_DDS)` per run in `jcl_command`; `job_parm_builtins(resolve(step.parm))` or `NO_PARM` per step.
- [ ] Step 3: Pass; mutation-check (drop per-step PARM; reuse first step's PARM).
- [ ] Step 4: Commit, push forge main.

### Task 4: floating-point builtins in plain and JCL

**Repo:** forge.

**Files:**
- Modify: `red_dragon_forge/plain_command.py`, `red_dragon_forge/jcl_command.py`, `docs/reference/forge/architecture.md`
- Create: fixture COBOL driver + HLASM FP routine; plain-mode test

- [ ] Step 1: Failing test: the routine computes one BFP, one HFP and one DFP result (hand-derived in the test), converts each to a binary integer (e.g. ×100) and stores them into the caller's area; the driver DISPLAYs them. Assert exact stdout.
- [ ] Step 2: Compose the four FP builtin tables in both modes.
- [ ] Step 3: Pass; mutation-check (drop one table → that value goes wrong).
- [ ] Step 4: Commit, push forge main.

### Task 5: CICS COBOL calling HLASM

**Repo:** forge.

**Files:**
- Modify: `red_dragon_forge/cics_command.py` (one function composing `other_builtins`: coprocessing, `unsupplied_run_input_builtins()`, FP tables)
- Create: forge-root integration test building a package with an inline CICS COBOL program and CardDemo's MVSWAIT, driving one transaction (pattern: `cicada/tests/integration/cics/test_region_from_package.py`)

- [ ] Step 1: Failing test: the transaction calls MVSWAIT with 10 hundredths, times it with `FUNCTION CURRENT-DATE`, and `SEND TEXT`s `WAITED`; assert the screen text.
- [ ] Step 2: Implement the composition function; use it in `cics_command` and in the test.
- [ ] Step 3: Pass; mutation-check (omit run inputs → not `WAITED`).
- [ ] Step 4: Commit, push forge main. Update red-dragon-6lic notes and push red-dragon.
