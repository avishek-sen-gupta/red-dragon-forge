# Assembler in litter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `forge-build` builds assembler programs into a litter package beside COBOL ones, and `forge-run [plain]` runs CardDemo's CBACT01C calling the assembler COBDATFT.

**Architecture:** `build.toml` gets a section per language: `[cobol]` takes today's `[paths]` and `[build].programs`, and `[hlasm]` is new. `litter.build` lowers each language with red-dragon's own lowering (`lower_program` for COBOL, `lower_hlasm_program` for HLASM) and links all units with `link_units`. Plain mode runs the image unchanged unless the proof shows otherwise (spec D2, D3).

**Tech Stack:** Python 3.13, Pydantic, pytest, import-linter; red-dragon vendored at `vendor/red-dragon`; the che4z HLASM bridge (`HLASM_AST_BRIDGE`).

**Spec:** `docs/superpowers/specs/2026-10-26-assembler-in-litter-design.md`

## Global Constraints

- Commits are allowed, but none extraneous: Task 1 is one forge commit (it also carries this plan and its spec), Task 2 is one forge commit, and a D3 fix is one red-dragon commit plus its bump folded into Task 2. forge commits carry no trailers, and forge's pre-commit gate (~25 min) runs once per commit, so dependent changes fold into one commit. red-dragon commits end with the session's attribution lines.
- No backward compatibility for `build.toml`. Every `build.toml`, fixture and doc moves to the new shape in the same change.
- A program's language comes only from the section that lists it. Never from its extension or its directory.
- Plain mode imports no jackal and no cics (contracts `plain-mode-without-runtimes`, `forge-run-shared-without-runtimes`).
- No comments beyond a one-line module or class header. Frozen dataclasses and frozen Pydantic models. Fully typed, with no `Any` or `object`. Imports fully qualified and sorted.
- No lint exclusions of any kind without the user's approval. If Talisman flags a line, reword it. A `.talismanrc` checksum change needs the user's approval.
- No local filesystem paths in tracked files. Never reference an external codebase under analysis. CardDemo is a vendored public sample and is already referenced throughout forge.
- A gap the proof exposes in red-dragon is fixed in red-dragon, with its own tests and bead, then vendored (spec D3). The user is told when each one is found.

## Review Focus

1. A `build.toml` still in the old shape (`[paths]`, or `programs` in `[build]`). It must fail with a message naming the unknown setting rather than build silently. Task 1 tests it.
2. An `[hlasm]` program whose `COPY` member is missing from `maclib_dirs`. forge-build must stop with exit 1 and a message naming the member, with no traceback. Task 1 tests it.
3. The HLASM bridge executable not being found. forge-build must say so on stderr, exit 1, and write no package. Task 1 tests it.
4. A `link` naming an HLASM program before a COBOL one, or the reverse. The image must not depend on the order. Task 2's build lists COBDATFT between the COBOL programs.
5. COBDATFT's error path (`GOTOERR`) on a record with a bad date. The account data may hold none. Task 2 asserts on whatever the data contains and does not invent records.

---

### Task 1: `build.toml` per language, and HLASM lowering in `litter.build`

**Files:**
- Create: `red_dragon_forge/build_cobol.py`, `red_dragon_forge/build_hlasm.py`
- Delete: `red_dragon_forge/build_paths.py`
- Modify: `red_dragon_forge/build_config.py`, `red_dragon_forge/build_section.py`, `red_dragon_forge/build_command.py`, `litter/litter/build.py`
- Migrate: `config/carddemo/build.toml`, `config/carddemo/build-db2.toml`, and every `build.toml` text in `tests/` (`tests/integration/test_build_command.py`, `test_run_command.py`, `test_plain_mode.py`, `tests/unit/test_build_config.py`, plus any others `rg -l "\[paths\]" tests` finds). Also check cicada, cobble and litter tests.
- Docs: `docs/reference/forge/build.md` (the `build.toml` block, the rules and the fault table), `docs/how-to/run-your-application.md`, and any other doc that shows `[paths]` for `build.toml`. `env.toml`'s own `[paths]` is a different section and stays.
- Test: `tests/unit/test_build_config.py`, `tests/integration/test_build_command.py`

**Interfaces:**
- Produces:
  - `BuildCobol(BaseModel)`, frozen, `extra="forbid"`, in `red_dragon_forge/build_cobol.py`. Fields:
    - `source_dirs: tuple[Path, ...] = ()`
    - `source_exts: tuple[str, ...] = ()`, defaulting to `(".cbl",)` when empty, as today
    - `copybook_dirs: tuple[Path, ...] = ()`
    - `copybook_exts: tuple[str, ...] = ()`
    - `programs: tuple[MemberName, ...] = ()`
  - `BuildHlasm(BaseModel)`, frozen, `extra="forbid"`, in `red_dragon_forge/build_hlasm.py`. Fields:
    - `source_dirs: tuple[Path, ...] = ()`
    - `source_exts: tuple[str, ...] = ()`, defaulting to `(".asm",)` when empty
    - `maclib_dirs: tuple[Path, ...] = ()`
    - `programs: tuple[MemberName, ...] = ()`
  - `BuildSection`: loses `programs`.
  - `BuildConfig`: fields `cobol: BuildCobol` and `hlasm: BuildHlasm`, each defaulting to an empty section, plus `build: BuildSection` and `cics: BuildCics`. Add `BuildConfig.programs() -> tuple[MemberName, ...]`, the COBOL programs followed by the HLASM ones.
  - `litter.build.build(...)`: gains `hlasm_sources: Mapping[str, Path]` (the HLASM program name to its source) and `hlasm_parser: HlasmAstParser`. `sources` keeps only COBOL programs; `programs` is every program of both languages.
- Consumes:
  - red-dragon's `lower_hlasm_program(program: SourceFile, *, parser: HlasmAstParser, work_dir: Path) -> tuple[Path, ...]`
  - `make_hlasm_parser(syslib: Sequence[Path]) -> HlasmBridgeParser` (from `hlasm_asg.hlasm_bridge_parser`)
  - `link_units`, which already links COBOL and HLASM units together

- [ ] **Step 1: Write the failing config tests** in `tests/unit/test_build_config.py`. One test per behaviour, each with equality assertions:
  - `test_each_language_lists_its_own_programs`: a `build.toml` with `[cobol]` (programs `["A"]`) and `[hlasm]` (programs `["B"]`, `maclib_dirs = ["mac"]`) loads, and `config.programs() == ("A", "B")`, `config.hlasm.maclib_dirs == (Path("mac"),)`, `config.cobol.source_exts == ()`.
  - `test_a_program_in_both_languages_is_refused`: `[cobol].programs = ["A"]` and `[hlasm].programs = ["A"]`, with `link` not naming A, raises `ConfigError` with exactly `"build.toml: A is listed in both [cobol] and [hlasm] programs"`.
  - `test_the_old_shape_is_refused`: a file with `[paths]` raises `ConfigError` naming `paths` (the exact text is whatever `toml_config` reports for an extra key; copy it from a run). A `[build]` with `programs` raises one naming `build.programs`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_build_config.py -q`. Expected: these tests FAIL (`BuildCobol` does not exist).
- [ ] **Step 3: Implement** `BuildCobol` and `BuildHlasm`, change `BuildConfig` and `BuildSection`, delete `build_paths.py`, and add the both-languages check to `build_config._checked`.
- [ ] **Step 4: Run** the unit tests. Expected: PASS.
- [ ] **Step 5: Write the failing build tests** in `tests/integration/test_build_command.py`, using that file's existing fixtures and `tmp_path` style.
  - `test_an_hlasm_program_builds_into_the_image`: COBOL `CALLER` does `CALL 'ASMSUB' USING WS-X` and DISPLAYs WS-X. `ASMSUB.asm` is a standard-linkage CSECT that MVCs `C'OK'` into the first argument and does `COPY` of a one-line maclib member `ASMEQU.mac` holding an `EQU`. forge-build exits 0, and the package's manifest `programs == ("CALLER", "ASMSUB")` in link order. Then `forge-run` on a `[plain]` env.toml entered at CALLER prints `OK` and `RC 0`. Assert the whole `(exit, stdout, stderr)` tuple.
  - `test_a_missing_macro_member_stops_the_build`: the same build without `ASMEQU.mac` gives exit 1, and stderr is `forge-build: <message>` naming `ASMEQU`. Take the exact text from a run, and check that it is one line with no traceback.
  - `test_an_unfound_hlasm_bridge_stops_the_build`: with `HLASM_AST_BRIDGE` naming a missing file, forge-build exits 1 with `forge-build: <the bridge-not-found message>`, and no zip is written.
  - Migrate the existing fault-table test: `"program UPPER is in no [paths] source_dirs as .cbl"` becomes `"... in no [cobol] source_dirs as .cbl"`. Only the section name changes. Add the HLASM row: `"program X is in no [hlasm] source_dirs as .asm"`.
- [ ] **Step 6: Run** `uv run pytest tests/integration/test_build_command.py -q` (with `. ./bridge-env.sh`). Expected: the new tests FAIL.
- [ ] **Step 7: Implement.**
  - `build_command._source` takes the section and its label (`[cobol]`, `[hlasm]`).
  - `_built` builds the HLASM parser with `make_hlasm_parser(tuple(base / d for d in config.hlasm.maclib_dirs))` and passes `hlasm_sources` and `hlasm_parser` to `build`.
  - `litter.build._image` lowers COBOL programs as today and HLASM programs with `lower_hlasm_program(SourceFile(path, path.read_bytes()), parser=hlasm_parser, work_dir=work_dir)`, then links `link` in order.
  - Map the bridge's exceptions (`HlasmBridgeNotFound`, `HlasmBridgeFailure`, `HlasmParseError`, `MissingSyslibDirectory`) to `forge-build: <message>`, exit 1, in `build_command.run`.
- [ ] **Step 8: Mutation-check.** First swap the order of the COBOL and HLASM lowering. The manifest-order assertion should not care, so confirm the test stays green; then drop the HLASM units from the link: the CALL test must fail. Then point the parser at no syslib: the macro test must change. Revert each break.
- [ ] **Step 9: Migrate** every `build.toml` file and text fixture to the new shape, along with the docs. Run `rg -n "\[paths\]" config tests docs/reference/forge docs/how-to` and check that only `env.toml` hits remain.
- [ ] **Step 10: Verify.** Run the root suite (`make test` or the root pytest with bridge-env and Db2 env), `uv run lint-imports`, Black, and pyright on the touched files. Also run the cicada and cobble suites if any of their files changed. Expected: all green, with no existing assertion changed except the section-name text in Step 5.
- [ ] **Step 11: Commit and push.** `make db2-restart`, then one forge commit with the spec and plan staged too; wait for the gate; push.

### Task 2: CBACT01C + COBDATFT in plain mode (the proof), and any gap it exposes

**Files:**
- Modify: `config/carddemo/data.toml`. Declare `AWS.M2.CARDDEMO.ACCTDATA.PSCOMP` (sequential, FB, LRECL 107), `AWS.M2.CARDDEMO.ACCTDATA.ARRYPS` (FB 110) and `AWS.M2.CARDDEMO.ACCTDATA.VBPS` (VB 84), as `READACCT.jcl` gives them, catalogued empty with their labels, in the file's existing style.
- Create: `tests/integration/test_readacct_plain.py`
- Modify, only if the run needs it (D2): `red_dragon_forge/plain_mode.py` / `plain_command.py`, to compose exactly the builtins a mixed image needs.
- Possibly red-dragon, under D3: the module the gap lives in, with its own test and bead.

**Interfaces:**
- Consumes: Task 1's `[cobol]`/`[hlasm]` `build.toml` and `forge-build`; `catnip.install.install(declaration, system)` and `load_declaration` as `tests/integration/test_carddemo_data_install.py` uses them; `forge-run` `[plain]` with `[plain.files]`.

- [ ] **Step 1: Extend** `tests/integration/test_carddemo_data_install.py`'s existing expectations so the three new datasets are part of what it checks. Add them to its expected dataset set or labels; read the test to see which. Run it and see it FAIL. Then declare the three datasets in `data.toml` and see it PASS.
- [ ] **Step 2: Write the proof test** `test_readacct_formats_dates_through_cobdatft` in `tests/integration/test_readacct_plain.py`:
  1. Install the declaration into a `tmp_path` catnip system.
  2. Write a `build.toml` in the new shape to `tmp_path`:
     - `[cobol]`: `source_dirs` is CardDemo's `app/cbl` plus red-dragon's `interpreter/cobol/le_stubs`, `source_exts = [".cbl", ".CBL"]`, `copybook_dirs` is CardDemo's `app/cpy`, and `programs = ["CBACT01C", "CEE3ABD"]`.
     - `[hlasm]`: `source_dirs` is CardDemo's `app/asm`, `maclib_dirs` is CardDemo's `app/maclib`, and `programs = ["COBDATFT"]`.
     - `[build]`: `link = ["CBACT01C", "COBDATFT", "CEE3ABD"]`.
  3. Run `forge-build`.
  4. Write an `env.toml` with `[plain] program = "CBACT01C"` and `[plain.files]` mapping ACCTFILE, OUTFILE, ARRYFILE and VBRCFILE to the four DSNs.
  5. Run `forge-run` in a subprocess, as `test_plain_mode.py` does.
  6. Assert `(exit, stdout lines, stderr)` with equality, and the three output datasets' labels and records with equality.
- [ ] **Step 3: Run it.**
  - If the first run succeeds before any expected values are written in, go to Step 5.
  - If it fails because the image needs builtins plain mode does not compose (D2), add exactly those to plain mode. Example: an unresolved-call or a missing-builtin error naming an HLASM run-input builtin.
  - If it fails on a red-dragon gap (D3), stop forge work, write the gap to the report, and notify the controller at once. The controller tells the user. Then: file a red-dragon bead; write a failing red-dragon test that reproduces the gap without forge, as a minimal COBOL plus HLASM pair in `tests/integration/hlasm/`; fix it; run red-dragon's gate; commit and push it to red-dragon main as one commit; then point forge's `vendor/red-dragon` at it in the Task 2 change.
- [ ] **Step 4: Repeat** Step 3 until the run completes.
- [ ] **Step 5: Fill in the expected values** (the controller's ruling in the spec).
  1. Capture the stdout lines and the three outputs' records from a run.
  2. Read them against CBACT01C's moves and the input records, and write them into the test as literals.
  3. Add a separate assertion on COBDATFT's date fields: for the first two input records, work out the date by hand from `acctdata.txt` and COBDATFT's conversion (`COINTYPE`/`COOUTYPE` rules in `COBDATFT.asm`), and assert it equals the field in the output record. Write the arithmetic in the report, not in the test.
- [ ] **Step 6: Mutation-check.** Break COBDATFT's effect without touching CardDemo's vendored source: build with `[hlasm].programs` and `link` omitting COBDATFT, under `[tolerant]` permitting the unresolved call. The date assertion must fail. Then map OUTFILE to an uncatalogued DSN: the run must be refused (D6 of the plain-mode spec).
- [ ] **Step 7: Verify.**
  - Run the root suite, `lint-imports` (the plain-mode contracts still hold), Black and pyright.
  - Under D3, also run red-dragon's full gate.
- [ ] **Step 8: Commit and push.** One forge commit (with any D3 vendor bump folded in); push. Report, every D2 or D3 change with the reason it was needed, and the bead ids filed.
