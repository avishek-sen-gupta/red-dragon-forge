# Program Declarations as IR Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A linked program carries each COBOL program's file definitions and data layout as IR `Data` directives; jackal, squall and cicada read them from there, and `ast_paths` and every `data_layout` field leave red-dragon.

**Architecture:** red-dragon's IR gains `Data(name, value)`, a no-op directive holding a generic nested literal (`DataScalar | DataRecord | DataList`). COBOL lowering emits two per program (`__cobol_file_definitions`, `__cobol_data_layout`). The loader hands the main module's `Data` to `VMState.declarations` uninterpreted; red-dragon's COBOL package provides typed readers. jackal builds its `ProgramFile`s from `Data`; squall and cicada find fields through `field_positions(vm.declarations)`; then the external structures are removed.

**Tech Stack:** Python 3.13, red-dragon (`~/code/red-dragon`, vendored at `vendor/red-dragon`), jackal, pytest, pyright strict, python-fp-lint.

**Spec:** `docs/superpowers/specs/2026-10-15-file-definitions-as-ir-data-design.md`

## Global Constraints

- `vendor/red-dragon` is never edited in the forge. Change `~/code/red-dragon`, run its tests, commit, push, then `git -C vendor/red-dragon fetch && git -C vendor/red-dragon checkout <sha>` and commit the bump.
- The IR knows no frontend or VM type: `DataValue` holds only `bool | int | str` scalars typed by `TypeExpr`, records of named fields, and lists. A record has no type name.
- Scope is parity: `Data` carries exactly what jackal's `program_files` reads from the ASTs today. No ALTERNATE RECORD KEY, no BLOCK CONTAINS, no new checks.
- The core runtime never interprets `Data`: the VM steps over it and the loader copies the main module's `Data` into `VMState.declarations` without looking inside. Only red-dragon's COBOL readers and their callers interpret it. `RealFileIOProvider` keeps taking `FileControlEntry`s from its caller.
- Scope is parity for the layout too: `__cobol_data_layout` holds exactly the entries `Frontend.data_layout` returns today, in the same order.
- Code style: frozen dataclasses; no `Any` or `object` in new code; no `None` defaults; no comments beyond a one-line module or class header; logging, never print.
- Tests: one test per behaviour, concrete equality assertions, no mocking or monkeypatching, temp files under `tmp_path`. red-dragon tests carry `@covers(...)` like their neighbours. Mutation-check every new test (break the covered code two obvious ways; the test fails both times).
- Gate before every commit: red-dragon — `uv run black .`, `uv run pyright`, its pre-commit hooks; forge — `make fmt`, `uv run pyright`, `uv run lint-imports`, `pre-commit run python-fp-lint-check --hook-stage manual --all-files` (judge only files you touched; the repo has known unrelated violations, bead red-dragon-forge-k48o), then `make test-all` with `. ./bridge-env.sh` sourced and Db2 up before each forge commit. `--no-verify` is never used.
- Talisman: a flag on record-key wording (`record_key`, `RECORD KEY`, `key_length`) in a file this plan touches → stop and report the file and checksum; the controller asks the user. Never edit `.talismanrc` unasked.
- Run `bd export -o issues/issues.jsonl` before any forge commit that changes beads.
- Never name an external codebase under analysis in a tracked artifact. CardDemo is fine.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Y8tAV2ducgCCVspgN11inx
  ```

## Notes

- cobble imports no IR instruction types (`rg "interpreter.instructions|merged_ir" cobble/cobble` prints nothing), so it needs no change; `make test-all` confirms it.

## Review Focus

1. **Parity of record lengths.** jackal computed `record_length(f)` over each FD 01 field; lowering must use the same `interpreter.cobol.data_layout.record_length` on the same fields. Task 3's parity test compares `ProgramFile`s from `Data` with those from the ASTs for every jackal COBOL fixture.
2. **A SELECT with no FD** (CardDemo has some through copybook-less stubs). Must yield `FormatFromDataset`, as today. Task 2 and Task 3 cover it.
3. **A CALLed subprogram's files.** jackal flattens every program's files today; the linked program must still expose the subprogram's `Data`. Task 2's linked-program test covers a main program that CALLs one with its own SELECT.
4. **A program with no FILE-CONTROL.** It still gets a `Data` whose `files` is an empty list, so readers never special-case absence. Task 2 covers it.
5. **Old `.linked.json` files.** After Task 4 the format number rises; reading a format-1 file must fail with `UnitFormatError` naming the file, not a `KeyError`. Task 4 covers it.
6. **CICS LINK/XCTL.** The inner VM must get the callee's declarations, not the caller's, or screen and field writes in a LINKed program resolve against the wrong layout. Task 3's cicada step keeps the existing LINK/XCTL end-to-end tests green and adds an assertion that a LINKed program's field write lands in its own WORKING-STORAGE.
7. **Layout parity.** `field_positions(vm.declarations)` must equal today's dictionary entry for entry. Task 2 asserts this over red-dragon's COBOL test programs.

---

### Task 1: red-dragon — the `Data` instruction

**Files (in `~/code/red-dragon`):**
- Create: `interpreter/data_value.py` (`DataScalar`, `DataField`, `DataRecord`, `DataList`, `DataValue`)
- Modify: `interpreter/ir.py` (`Opcode.DATA`), `interpreter/instructions.py` (class `Data`, add to `Instruction` union), `interpreter/project/ir_codec.py` (`_DATACLASSES` gains the four value classes), `interpreter/run.py:386` and `:768` (skip `Data` like `Label_`), `interpreter/types/type_inference.py:985` (`Data` → a no-op entry in `_DISPATCH`)
- Test: `tests/unit/project/test_ir_codec.py` (add a `Data` sample), `tests/unit/test_data_directive.py` (new)

**Interfaces:**
- Produces:
  ```python
  # interpreter/data_value.py
  @dataclass(frozen=True)
  class DataScalar:
      value: bool | int | str
      type_expr: TypeExpr
  @dataclass(frozen=True)
  class DataField:
      name: FieldName
      value: "DataValue"
  @dataclass(frozen=True)
  class DataRecord:
      fields: tuple[DataField, ...]
  @dataclass(frozen=True)
  class DataList:
      items: tuple["DataValue", ...]
  type DataValue = DataScalar | DataRecord | DataList

  # interpreter/instructions.py
  @dataclass(frozen=True)
  class Data(InstructionBase):
      name: VarName = NO_VAR_NAME
      value: DataValue = DataList(())
  ```
  `Data.opcode == Opcode.DATA`, `writes()` returns `None`, `reads()` returns `[]`, `operands` returns `[str(self.name)]`.

- [ ] **Step 1: Write the failing tests.**
  In `tests/unit/project/test_ir_codec.py`, add to `_SAMPLES`:
  ```python
  Data(
      name=VarName("PROG"),
      value=DataRecord((
          DataField(FieldName("files"), DataList((
              DataRecord((
                  DataField(FieldName("assign_to"), DataScalar("IN1", scalar(FoundationTypeName.STRING))),
                  DataField(FieldName("depending"), DataScalar(False, scalar(FoundationTypeName.BOOL))),
                  DataField(FieldName("record_lengths"), DataList((DataScalar(80, scalar(FoundationTypeName.INT)),))),
              )),
          ))),
      )),
  ),
  ```
  `test_the_samples_cover_every_instruction_class` and `test_every_instruction_round_trips_with_its_field_types` then cover `Data`.
  Create `tests/unit/test_data_directive.py`:
  ```python
  from interpreter.data_value import DataList, DataScalar
  from interpreter.instructions import Data
  from interpreter.run import execute_cfg, initial_vm_state
  from tests.unit.cfg_helpers import build_simple_cfg, make_instructions

  @covers(NotLanguageFeature.INFRASTRUCTURE)
  def test_a_data_directive_changes_nothing_when_the_program_runs():
      label, *rest = make_instructions(
          (Opcode.LABEL, {"label": CodeLabel("entry")}),
          (Opcode.CONST, {"result_reg": Register("%0"), "operands": [42]}),
          (Opcode.STORE_VAR, {"operands": ["x", "%0"]}),
          (Opcode.RETURN, {"operands": ["%0"]}),
      )
      directive = Data(
          name=VarName("PROG"),
          value=DataList((DataScalar(1, scalar(FoundationTypeName.INT)),)),
      )
      cfg, registry = build_simple_cfg([label, directive, *rest])
      vm, stats = execute_cfg(cfg, "entry", registry, vm=initial_vm_state())
      assert unwrap(vm.current_frame.local_vars[VarName("x")]) == 42
      assert stats.llm_calls == 0
  ```
  (Imports for `Opcode`, `CodeLabel`, `Register`, `VarName`, `unwrap`, `scalar`, `FoundationTypeName` and `covers` follow `tests/unit/test_execute_cfg.py` and `tests/unit/project/test_ir_codec.py`. `llm_calls == 0` is the assertion that fails if the VM does not step over `Data`: an unhandled opcode falls to the LLM fallback.)
- [ ] **Step 2: Run them; they fail.** `uv run pytest tests/unit/project/test_ir_codec.py tests/unit/test_data_directive.py -q` → FAIL: `Data` is not defined.
- [ ] **Step 3: Implement.** Create `interpreter/data_value.py` as in Interfaces with a one-line module header. Add `DATA = "DATA"` to `Opcode`. Add `Data` to `instructions.py` and to the `Instruction` union. Add `DataScalar, DataField, DataRecord, DataList` to `_DATACLASSES` in `ir_codec.py`. In both `run.py` loops change `if isinstance(instruction, Label_):` to `if isinstance(instruction, (Label_, Data)):`. In `type_inference.py` add `Data: _infer_data` with `def _infer_data(inst: Data, ctx: _InferenceContext, type_resolver: TypeResolver) -> None: pass` beside `_infer_store_indirect`.
- [ ] **Step 4: Run them; they succeed.** Same command → green. Then `uv run pytest -q -x` → all green.
- [ ] **Step 5: Mutation-check.** Remove `Data` from the `run.py` skip (the run test must fail on `llm_calls` or by raising); drop `DataList` from `_DATACLASSES` (the codec test must fail). Restore.
- [ ] **Step 6: Commit** (red-dragon): `feat(ir): a Data directive — a named nested literal the VM steps over`. Do not push yet; Task 2 pushes both.

---

### Task 2: red-dragon — COBOL lowering declares file definitions and the data layout

**Files (in `~/code/red-dragon`):**
- Create: `interpreter/cobol/file_definitions_data.py` (`FILE_DEFINITIONS`, `file_definitions_data(asg) -> Data`), `interpreter/cobol/layout_data.py` (`DATA_LAYOUT`, `layout_data(fields) -> Data`, `FieldPosition`, `field_positions(declarations) -> Mapping[str, FieldPosition]`)
- Modify: `interpreter/cobol/cobol_frontend.py:~244` (emit both right after `Label_(label=CodeLabel("entry"))`), `interpreter/vm/vm_types.py` (`VMState.declarations: tuple[Data, ...] = ()`), `interpreter/run.py:928,967,973,1004,1172` (beside each `data_layout` assignment, set `declarations` to the main module's `Data`)
- Test: `tests/unit/cobol/test_file_definitions_data.py`, `tests/unit/cobol/test_layout_data.py` (new), `tests/unit/project/test_cobol_compile.py` (linked-program cases)

**Interfaces:**
- Consumes: Task 1's `Data`, `DataScalar`, `DataField`, `DataRecord`, `DataList`.
- Produces:
  - `FILE_DEFINITIONS = VarName("__cobol_file_definitions")`; `file_definitions_data(asg: CobolASG) -> Data` with value `DataRecord((DataField(FieldName("files"), DataList(<one record per asg.file_control entry, in order>)),))`. Each file record's fields, in order: `file_name`, `assign_to`, `organization` (enum `.value`), `access_mode` (enum `.value`), `record_key`, `relative_key`, `file_status` (all `str`), `fd` (a `DataList` of zero or one FD record). An FD record's fields, in order: `recording_mode` (`RecordingMode.value`, `""` when not coded), `record_clause` (a record: `kind` str, then `size` int for `contains`; `minimum`, `maximum` int for `range`; `minimum`, `maximum` int and `depending_on` str for `varying`; nothing more for `none`), `record_lengths` (list of int, one per 01 record of that FD in `asg.file_fields` order, each `interpreter.cobol.data_layout.record_length(field)`), `depending` (bool: any 01 record or descendant has `occurs_depending_on`). An FD matches its SELECT when `fd_name.upper() == file_name.upper()`; an 01 record belongs to it when `asg.file_record_to_select.get(field.name.upper()) == file_name.upper()`.
  - `DATA_LAYOUT = VarName("__cobol_data_layout")`; `layout_data(fields: Iterable[FieldLayout]) -> Data` with value `DataRecord((DataField(FieldName("fields"), DataList(<one record per field>)),))`, each record `name` str, `offset` int, `length` int, `category` str (`type_descriptor.category.value`), `total_digits` int, `decimal_digits` int, `signed` bool — the same entries, in the same order, that `CobolFrontend.data_layout` builds today from `self._layout.all_fields()`.
  - `@dataclass(frozen=True) class FieldPosition: offset: int; length: int; category: str; total_digits: int; decimal_digits: int; signed: bool`.
  - `field_positions(declarations: Sequence[Data]) -> Mapping[str, FieldPosition]`: from the `Data` named `DATA_LAYOUT` (an empty mapping when there is none).
  - `VMState.declarations: tuple[Data, ...] = ()`. In `run.py`, `_main_declarations(linked) -> tuple[Data, ...]`: the `Data` instructions of the `ModuleUnit` in `linked.modules` whose `entry_label.namespace(module_prefix(path, <the linker's project root>))` equals `linked.entry_func_label`; `()` when none matches. Read how `cobol_compile.py:220-225` builds `entry_func_label` and use the same prefix call.

- [ ] **Step 1: Write the failing tests.**
  - `test_file_definitions_data.py` parses (with the parser fixture `test_io_statements.py` uses) a program with: `SELECT IN-FILE ASSIGN TO INDD FILE STATUS IS WS-ST.` and `FD IN-FILE RECORDING MODE V RECORD VARYING 10 TO 80 DEPENDING ON WS-LEN.` with two 01 records of 80 and 40 bytes, one containing `OCCURS 1 TO 8 DEPENDING ON WS-N`; `SELECT KS-FILE ASSIGN TO KSDD ORGANIZATION INDEXED ACCESS DYNAMIC RECORD KEY KS-ID.` with `FD KS-FILE.` and one 01 record of 50 bytes; `SELECT NOFD-FILE ASSIGN TO NFDD.` with no FD. It asserts `file_definitions_data(asg) == Data(name=FILE_DEFINITIONS, value=<the exact expected DataRecord, spelled out in full>)`. A second case: no FILE-CONTROL gives `files` = `DataList(())`.
  - `test_layout_data.py`: for each COBOL program under `tests/unit/cobol/fixtures/` (or the directory the existing COBOL lowering tests read sources from), lower it and assert `field_positions((layout_data(...),))` equals the frontend's `data_layout` dictionary converted entry by entry (`{name: FieldPosition(**entry)}`). This is the parity test; it is deleted in Task 4 with the dictionary.
  - In `test_cobol_compile.py`: compile a main program that CALLs a subprogram with its own SELECT; assert `merged_ir` holds exactly two `Data` named `FILE_DEFINITIONS` (main's and the subprogram's files) and two named `DATA_LAYOUT`. Then run the linked program with `run_linked` and assert `vm.declarations` is exactly the main module's two `Data`.
- [ ] **Step 2: Run; they fail.** `uv run pytest tests/unit/cobol/test_file_definitions_data.py tests/unit/cobol/test_layout_data.py tests/unit/project/test_cobol_compile.py -q` → FAIL: modules not found.
- [ ] **Step 3: Implement.** Small functions only: `_text`, `_int`, `_bool` make `DataScalar`s with `scalar(FoundationTypeName.STRING/INT/BOOL)`; `_clause(RecordClause) -> DataRecord` via `match`; `_fd`, `_file`, `file_definitions_data`; `_position(record) -> FieldPosition`, `field_positions`. In `cobol_frontend._lower_asg`, after the entry label: `self._ctx.emit_inst(file_definitions_data(asg))` and `self._ctx.emit_inst(layout_data(sectioned.working_storage.all_fields()))`. Add `declarations` to `VMState` and `_main_declarations` to `run.py`; set it beside every `data_layout` assignment.
- [ ] **Step 4: Run; green.** Same command → green; `uv run pytest -q -x` → all green. Existing tests that assert the exact instruction list after the entry label gain the two `Data`; list every changed test in the commit body.
- [ ] **Step 5: Mutation-check.** Drop the `fd` list for SELECTs with an FD; compute `depending` from the 01 level only; pick the first module's `Data` instead of the entry module's. Each fails a test. Restore.
- [ ] **Step 6: Commit and push** (red-dragon): `feat(cobol): lowering declares each program's file definitions and data layout as IR Data`. Push Tasks 1–2. In the forge: bump `vendor/red-dragon`, run `make test-all` (all green — nothing reads `Data` yet), commit `chore(vendor): bump red-dragon — COBOL declarations as IR Data`, push.

---

### Task 3: forge — jackal, squall and cicada read declarations from `Data`

**Files:**
- Create: `jackal/jackal/file_definitions.py` (`program_files_in(ir: Sequence[InstructionBase]) -> tuple[ProgramFile, ...]`, `program_files_of(linked: LinkedProgram) -> tuple[ProgramFile, ...]`)
- Modify: `jackal/jackal/program_compiler.py` (use it; delete `_parsed`, the `ast_paths` read and imports left unused), `jackal/jackal/cobol_files.py` (delete `program_files` and its helpers `_records`, `_format`, `_depends` once unused); `squall/squall/binding.py` (every `vm.data_layout` / `data_layout: Mapping` lookup → `field_positions(vm.declarations)` and `FieldPosition` attributes); `cicada/cics/builtins/cells.py:32`, `system.py:63`, `screen.py:73` (same), `cicada/cics/builtins/flow.py:149` (`inner_vm.declarations = <callee's main declarations>` instead of `inner_vm.data_layout = linked.data_layout`)
- Test: `jackal/tests/unit/test_file_definitions.py` (new), `jackal/tests/integration/test_file_definitions_parity.py` (new, deleted in Step 8); squall and cicada tests that build a `VMState` with a hand-written `data_layout` dict switch to `declarations=(layout_data(...),)` built from the same fields
- Docs: `docs/reference/jackal/architecture.md` (file formats now come from the linked program), squall and cicada reference pages wherever they say host variables or fields are found through `data_layout`

**Interfaces:**
- Consumes: Task 2's `FILE_DEFINITIONS`, `DATA_LAYOUT`, `field_positions`, `FieldPosition`, `layout_data`, `VMState.declarations`, and the file-record shape above. For cicada's LINK: red-dragon's `run.py` exposes `_main_declarations` privately — Task 3 needs it public; if it is still private, add a one-line public alias `main_declarations` in red-dragon (a Task-2 follow-up commit, pushed and bumped first) rather than reimplementing it in cicada.
- Produces: `program_files_of(linked)`: for every `Data` in `linked.merged_ir` with `name == FILE_DEFINITIONS`, in IR order, for each file record, `ProgramFile(FileControlEntry(...), fmt)` where `fmt = program_format(FileDescription(fd_name=file_name, recording_mode=RecordingMode(rm), record_clause=<clause>), FdRecords(lengths, depending))` if `fd` has one record, else `FormatFromDataset()`.

- [ ] **Step 1: Write the parity test first.** `test_file_definitions_parity.py`: for every COBOL program under `jackal/tests/integration/fixtures/cbl/`, compile it with `ProgramCompiler` as the integration tests do and assert `program_files_of(compiled.linked) == compiled.files` (the AST-derived files). Run → FAIL: not defined.
- [ ] **Step 2: Write the unit test.** `test_file_definitions.py`: an IR list with one hand-built `Data` named `FILE_DEFINITIONS` (a sequential FD with RECORDING MODE V / RECORD VARYING; an indexed SELECT with RECORD KEY; a SELECT with no FD) plus one `Data` under another name, which must be ignored; assert the exact `ProgramFile` tuple from `program_files_in`. Run → FAIL.
- [ ] **Step 3: Implement** `file_definitions.py` — the one boundary for this data: `_field(record, name) -> DataValue`, `_text`, `_int`, `_bool`, `_ints`, `_entry(record) -> FileControlEntry`, `_clause(record) -> RecordClause` (`match` on `kind`), `_format(record) -> ProgramFormat`, `program_files_in`, `program_files_of`. A value of the wrong shape raises `ValueError` naming the field.
- [ ] **Step 4: Run both; green.** `cd jackal && uv run --no-sync python -m pytest tests/unit/test_file_definitions.py tests/integration/test_file_definitions_parity.py -q` → green for every fixture. A parity mismatch is a finding about Task 2 — fix it upstream, never in the comparison.
- [ ] **Step 5: Switch jackal over.** `ProgramCompiler.compiled` returns `CompiledProgram(linked, program_files_of(linked))`; delete the AST reading. Extend the jackal integration test that runs a COBOL step with a FILE STATUS check: delete the compile's work directory after compiling and assert `program_files_of(LinkedCodec(IrCodec()).read(<linked file>))` returns the same `ProgramFile`s.
- [ ] **Step 6: Switch squall and cicada over.** Replace every `vm.data_layout` read with `field_positions(vm.declarations)` and dictionary indexing (`f["offset"]`) with `FieldPosition` attributes; LINK/XCTL sets the inner VM's `declarations` from the callee. Add to the existing cicada LINK end-to-end test an assertion that a field written by the LINKed program lands at the callee's own offset. Run `make test-all` (with Db2 up) → all green; the CardDemo and Db2 end-to-end suites are the regression gate.
- [ ] **Step 7: Mutation-check.** Make jackal's `_format` always return `FormatFromDataset()` (status-39 and DCB tests fail); swap `record_key` and `relative_key` (unit test fails); give the LINKed inner VM the caller's declarations (the cicada LINK test fails). Restore.
- [ ] **Step 8: Finish.** Delete the parity test and `program_files` with its helpers; update the docs; run the gate and `make test-all`; `bd close red-dragon-forge-96h --reason "file definitions and data layout are IR Data; jackal, squall and cicada read them from the linked program"`; `bd export -o issues/issues.jsonl`. Commit `feat(jackal,squall,cicada): program declarations come from the linked program's Data directives (red-dragon-forge-96h)` and push.

---

### Task 4: red-dragon — the external structures leave

**Files (in `~/code/red-dragon`):**
- Modify: `interpreter/project/types.py` (remove `ModuleUnit.data_layout`, `LinkedProgram.data_layout`, `LinkedProgram.ast_paths`), `interpreter/project/linked_codec.py` (stop reading them; `_FORMAT = 2`; the pattern `{"format": 1, ...}` becomes `{"format": 2, ...}`), `interpreter/project/linker.py:482,558` (the `data_layout` parameter goes), `interpreter/project/cobol_compile.py:94,220,227,257`, `interpreter/frontend.py:38` and `interpreter/ast_repair/repairing_frontend_decorator.py:41` (the `data_layout` property goes), `interpreter/cobol/cobol_frontend.py:141` (its `data_layout` property goes), `interpreter/vm/vm_types.py:177,372` (`VMState.data_layout` and its dump entry go; the dump lists `declarations` instead), `interpreter/run.py` (the `data_layout` assignments go; `:1302` passes no `data_layout`)
- Test: the `LinkedCodec` test file (`rg -l LinkedCodec tests`), `tests/unit/project/test_cobol_compile.py`, `tests/unit/cobol/test_layout_data.py` (its parity test is deleted with the dictionary)

**Interfaces:**
- Consumes: after Task 3 nothing in the forge reads `data_layout` or `ast_paths` outside `vendor/` (`rg -n "data_layout|ast_paths" -g '*.py' cicada squall jackal cobble red_dragon_forge tests` prints only `interpreter.cobol.data_layout` module imports such as `record_length` and `build_data_layout` — verify before starting).

- [ ] **Step 1: Write the failing test.** In the `LinkedCodec` test file: a file written as `{"format": 1, "linked": {...}}` read with `LinkedCodec.read` raises `UnitFormatError` whose message names the path and says `not a linked-program file of format 2`. Run → FAIL.
- [ ] **Step 2: Implement** the removals. `uv run pytest -q -x` → all green after removing assertions on the deleted fields (list each in the commit body: they assert fields that no longer exist, not behaviour).
- [ ] **Step 3: Mutation-check.** Accept format 1 again (the test fails); leave `_FORMAT = 1` while matching 2 (round-trip tests fail). Restore.
- [ ] **Step 4: Commit and push** (red-dragon): `refactor(project): data_layout and ast_paths leave the project types; linked-file format 2`. In the forge: bump `vendor/red-dragon`; regenerate any `.linked.json` fixtures (`rg -l '"format": 1' --glob '*.linked.json'`), never hand-edit them; `make test-all`; commit `chore(vendor): bump red-dragon — no data_layout or ast_paths outside the IR`; push.
