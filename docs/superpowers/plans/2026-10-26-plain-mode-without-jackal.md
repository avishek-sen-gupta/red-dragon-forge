# Plain Mode Without jackal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `forge-run` in `[plain]` mode runs the package's image directly, importing nothing from jackal, after the non-JCL parts of jackal and the record-access drivers move to homes that do not load the VM.

**Architecture:** Three red-dragon commits create the root package `infrastructure` (abend types; record-access drivers) and move the CEE3ABD stub and its reader into `interpreter.cobol`. One forge commit bumps red-dragon, points catnip at `infrastructure`, creates `zos.cobol.io` from jackal's COBOL file handling, and re-points jackal. A last forge commit replaces plain mode's synthesized job with a direct `run_linked_resumable`.

**Tech Stack:** Python 3.13, uv workspaces, hatchling, pytest, import-linter, pyright, Black, python-fp-lint.

**Spec:** `docs/superpowers/specs/2026-10-26-plain-mode-without-jackal-design.md` (forge).

## Global Constraints

- Two repos, checked out side by side: red-dragon, and forge, which vendors red-dragon at `vendor/red-dragon` (a submodule; never edit it in place — change red-dragon, push, then bump).
- Push to `main` in both repos.
- No comments beyond a one-line module or class header. Frozen dataclasses. Fully typed; no `Any`, no `object`.
- No lint exclusions of any kind (`fp.json` entries, `# noqa`, per-file ignores) without the user's approval.
- No new builtins.
- Imports fully qualified and sorted.
- No local filesystem paths in tracked files or commit messages.
- Never reference an external codebase under analysis.
- If Talisman blocks a commit, reword the flagged line. Never touch `.talismanrc`.
- red-dragon commits end with the session's attribution lines. forge commits carry none: forge's terminology guard rejects them.
- forge's pre-commit gate runs every suite (~25 minutes), and the root suite and squall need Db2. Run `make db2-up` once and `make db2-restart` before each commit. Fold changes that depend on each other into one forge commit; never gate two back to back when one would do.
- In red-dragon, `bd export` before staging `issues/issues.jsonl`. Use `bd update --append-notes`, never `--notes`.
- A moved module keeps its behaviour and its tests: tests move with their module and keep their assertions.
- The red-dragon verification gate: `uv run python -m black .`, `uv run pyright`, `uv run python -m python_fp_lint check --config fp.json interpreter/ cobol_asg/`, `uv run lint-imports`, `make test PYTEST_ARGS="-q"`.

## Review Focus

1. A COBOL program that calls CEE3ABD with code `0` must report abend `U0000`, not "no abend". The reader's "not called" sentinel is `-1`, not `0`. Test in Task 3.
2. A plain run whose program opens a catalogued dataset with a pending label for OUTPUT labels it. A second run reads it back with that label. Test in Task 5.
3. Two programs in one image that SELECT the same ASSIGN name keep separate files state. The per-program dispatch must survive the split. Test in Task 4: jackal's `test_per_program_files.py` still passes. Plain mode gets its own two-program test in Task 5.
4. A program that calls CEE3ABD and leaves RETURN-CODE symbolic reports the abend, not `RC 0`. Test in Task 5.
5. A plain run that exhausts `max_steps` prints the budget-exhausted line with exit status 1, never `S322`. Test in Task 5.

---

### Task 1: `infrastructure.zos.abend` (red-dragon)

**Files:**
- Create: `infrastructure/__init__.py`, `infrastructure/zos/__init__.py`, `infrastructure/zos/abend/__init__.py`, `infrastructure/zos/abend/system_abend.py`, `infrastructure/zos/abend/user_abend.py`
- Modify: `pyproject.toml:43` (wheel `packages` gains `"infrastructure"`), `.importlinter` (root package and contract), `README.md` and `guidelines/project-context.md` (root-package list)
- Test: `tests/unit/infrastructure/test_abend.py`

**Interfaces:**
- Produces: `infrastructure.zos.abend.system_abend.SystemAbend(code: int)`, `.rendered() -> str` giving `S` plus three uppercase hex digits. `infrastructure.zos.abend.user_abend.UserAbend(code: int)`, `.rendered() -> str` giving `U` plus four decimal digits. Both are frozen dataclasses, with bodies copied from forge's `jackal/jackal/model.py:669-682`.

- [ ] **Step 1: Write the failing test** `test_abends_render_as_zos_prints_them`: `SystemAbend(0x0C7).rendered() == "S0C7"`, `SystemAbend(0x806).rendered() == "S806"`, `UserAbend(1).rendered() == "U0001"`, `UserAbend(4038).rendered() == "U4038"`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/infrastructure/test_abend.py -q`. Expected: FAIL, no module `infrastructure`.
- [ ] **Step 3: Implement** the two classes. Add `infrastructure` to `root_packages`. Add contract `[importlinter:contract:infrastructure-is-below-interpreter]`, type `forbidden`, source `infrastructure`, forbidden `interpreter`, with the name "infrastructure never imports interpreter, so importing it never loads the VM". Package headers are one line each.
- [ ] **Step 4: Run** the test (green), then `uv run lint-imports`. Mutation-check: make `infrastructure/zos/abend/user_abend.py` import `interpreter.func_name` and confirm `lint-imports` fails, then revert.
- [ ] **Step 5: Full gate; commit** `feat(infrastructure): a root package below interpreter, holding z/OS abend types`. Push.

### Task 2: `infrastructure.zos.access_methods` (red-dragon)

**Files:**
- Move (`git mv`, contents unchanged except imports) from `interpreter/record_io/` to `infrastructure/zos/access_methods/` these modules
  - `access_result.py`
  - `alternate_index.py`
  - `alternate_index_driver.py`
  - `alternate_key.py`
  - `described_slot.py`
  - `file_drivers.py`
  - `flagged_slot.py`
  - `prime_key.py`
  - `record_shape.py`
  - `relative_slot.py`
  - `variable_sequential_driver.py`
- Stay in `interpreter/record_io/`: `io_provider.py`, `real_file_provider.py`, `file_frame.py`, `run_inputs.py`, `__init__.py` (header updated to say the drivers live in `infrastructure.zos.access_methods`)
- Modify: every importer of a moved module (59 files outside `interpreter/record_io`, and the moved files themselves). Find them by searching for each moved module's old dotted path. Also update `.importlinter`'s `record-io-is-neutral` contract, which adds `infrastructure.zos.access_methods` as a source, and the docs that name the moved paths (`rg -n "record_io" README.md docs/`).
- Test: no new behaviour, so the existing record-I/O, COBOL file and HLASM QSAM tests are the test. Add `tests/unit/infrastructure/test_access_methods_load_no_vm.py`.

**Interfaces:**
- Produces: `infrastructure.zos.access_methods.<module>` for each moved module, with the same names inside.

- [ ] **Step 1: Write the failing test** `test_importing_the_drivers_leaves_the_vm_unloaded`. Run `[sys.executable, "-I", "-c", "import sys, infrastructure.zos.access_methods.file_drivers, infrastructure.zos.access_methods.alternate_index_driver, infrastructure.zos.access_methods.variable_sequential_driver; print(sorted(m for m in sys.modules if m.startswith('interpreter')))"]` with `subprocess.run`, from the repo root, and assert stdout is `"[]\n"`.
- [ ] **Step 2: Run it.** Expected: FAIL, modules missing.
- [ ] **Step 3: Move the modules** and rewrite every import. Verify no old path survives, as text: `rg -n "interpreter\.record_io\.(access_result|…)"` returns nothing, including strings and docs.
- [ ] **Step 4: Run** the new test and the full gate. Mutation-check: add `import interpreter.data_value` to `access_result.py`, confirm the test and `lint-imports` both fail, then revert.
- [ ] **Step 5: Commit** `refactor(infrastructure): the record-access drivers move below interpreter`, with a bead filed first (`bd create`, type task) and closed in the same commit, `issues/issues.jsonl` staged. Push.

### Task 3: the CEE3ABD stub and its reader in `interpreter.cobol` (red-dragon)

**Files:**
- Create: `interpreter/cobol/le_stubs/CEE3ABD.cbl` (copied verbatim from forge `jackal/jackal/le_stubs/CEE3ABD.cbl`), `interpreter/cobol/cee3abd_abend.py`
- Test: `tests/integration/test_cobol_cee3abd.py`

**Interfaces:**
- Produces: `interpreter.cobol.cee3abd_abend.LE_STUBS: Path` (the `le_stubs` directory). `interpreter.cobol.cee3abd_abend.user_abend(vm: VMState) -> tuple[UserAbend, ...]` returns `()` when CEE3ABD was never called and `(UserAbend(code),)` when it was. The body is ported from forge's `jackal/jackal/le_abend.py`, and `UserAbend` comes from `infrastructure.zos.abend.user_abend`.

- [ ] **Step 1: Write the failing test** `test_a_program_that_calls_cee3abd_ends_with_that_user_abend`. Compile and link a caller plus the stub from `LE_STUBS`, using the same project-compile helper the existing multi-program COBOL integration tests use, and run it. Three cases, each asserted with `==`:
  - the caller does `CALL 'CEE3ABD' USING WS-CODE WS-CLEANUP` with code 1234: `(UserAbend(1234),)`;
  - the same call with code 0: `(UserAbend(0),)` (Review Focus 1);
  - a caller that never calls it, with the stub still linked: `()`.
- [ ] **Step 2: Run it.** Expected: FAIL, module missing.
- [ ] **Step 3: Implement** by porting `le_abend.py`.
- [ ] **Step 4: Run** the test. Mutation-check: change the not-called sentinel to `0` and confirm the code-0 case fails; make `_code` return `()` always and confirm the first case fails. Revert both.
- [ ] **Step 5: Full gate; commit** `feat(cobol): the CEE3ABD stub and the reader of the abend it records`, with a bead closed in the same commit. Push. Record the pushed SHA for Task 4.

### Task 4: forge step 1 — bump, catnip below the VM, `zos.cobol.io`, jackal re-pointed (one forge commit)

**Files:**
- Bump: `vendor/red-dragon` to Task 3's SHA. Run `git -C vendor/red-dragon submodule update --init --recursive`, `uv sync --all-packages`, `make jar-force`, and rebuild `hlasm_export` (`cd vendor/red-dragon/hlasm-bridge/che4z && BUILD_TYPE=Release ./build.sh --target hlasm_export`).
- Modify catnip: `catnip/catnip/dataset.py` and `catnip/catnip/variable_records.py` import from `infrastructure.zos.access_methods`. In `.importlinter`, `catnip-imports-no-runtime` gains `interpreter` as a forbidden module, and `infrastructure` and `zos` join `root_packages`.
- Create the workspace member `zos/`: `zos/pyproject.toml` (modelled on `catnip/pyproject.toml`; name `zos`, depends on `catnip` and `red-dragon`, wheel package `zos`). Inside it, the package `zos/zos/__init__.py`, `zos/zos/cobol/__init__.py` and `zos/zos/cobol/io/__init__.py`. Add `zos` to the root `pyproject.toml` `[tool.uv.workspace] members` and `[tool.uv.sources]`, and to jackal's dependencies.
- Move into `zos/zos/cobol/io/` (`git mv`) these jackal modules
  - `jackal/jackal/file_definitions.py`
  - `jackal/jackal/record_format.py`
  - `jackal/jackal/record_key.py`
  - `jackal/jackal/label_conflict.py`
  - `jackal/jackal/label_field.py`

  with their tests `jackal/tests/unit/{test_file_definitions,test_record_format}.py` moving to `zos/tests/unit/`.
- Split: `jackal/jackal/cobol_files.py` and `program_files_provider.py` (see Interfaces).
- Re-point jackal: every `jackal.model.SystemAbend`/`UserAbend` import goes to `infrastructure.zos.abend.*`, and `model.py` no longer defines them. That's 16 files (`rg -l "\b(SystemAbend|UserAbend)\b" jackal`). `jackal/jackal/le_abend.py` and `jackal/jackal/le_stubs/` are deleted: `cobol_step.py` imports `user_abend` from `interpreter.cobol.cee3abd_abend`, and `jackal/tests/package_build.py` imports `LE_STUBS` from there.
- Add contract `zos-imports-no-runtime`, forbidding `zos` to import `cics`, `squall`, `jackal`, `cobble`, `litter` and `red_dragon_forge`.
- Docs: `docs/reference/forge/build.md` (the stub's new location), `docs/reference/jackal/architecture.md` (what moved), and a `zos` line in the root README's package list.
- Test: `zos/tests/unit/test_dataset_files.py`, plus every existing suite.

**Interfaces:**
- Produces in `zos.cobol.io`:
  - `zos.cobol.io.program_file.ProgramFile` (moved from `cobol_files`, unchanged).
  - `zos.cobol.io.dataset_files.DatasetFileIOProvider(RealFileIOProvider)`, whose constructor takes `base_dir` (`Path`), `files` (`Sequence[ProgramFile]`), `bindings` (`FileBindings`) and `relabeller` (`Relabeller`). It holds everything in today's `AllocatedFileIOProvider` except the concatenation branches: `_opened_as`, the dataset branch of `_supports`, `_admits_dataset`, `_admits_sequential`, `_labelled`, the dataset branch of `_driver_for`, and `_open_file`.
  - `zos.cobol.io.file_bindings.FileBindings`, a frozen dataclass with three fields, each indexed by ASSIGN name
    - `paths` of type `Mapping[str, Path]`
    - `appended` of type `frozenset[str]`
    - `datasets` of type `Mapping[str, Dataset]`
    They replace what the provider read from `DdEnvironment` (`paths()`, `appended()`, `_datasets`).
  - `zos.cobol.io.program_files.ProgramFilesIOProvider(CobolIOProvider)`, with `__init__(self, programs: Collection[str], provider_for: Callable[[Sequence[ProgramFile]], CobolIOProvider], files: Sequence[ProgramFile])`. This is today's per-program dispatch, with the per-program provider built by `provider_for`.
- jackal keeps `AllocatedFileIOProvider(DatasetFileIOProvider)`, which adds the concatenation branches by overriding and calling `super()`, and builds a `FileBindings` from its `DdEnvironment`.

- [ ] **Step 1: Write the failing test** `test_a_catalogued_dataset_opens_by_its_assign_name_and_a_contradicting_fd_fails_39` in `zos/tests/unit/test_dataset_files.py`. It builds a `DatasetFileIOProvider` over a `FileBindings` with one fixed-length dataset in a `tmp_path`, then asserts that OPEN INPUT with a matching FD gives status `"00"` and a 1-byte-shorter FD gives `"39"`. Follow `jackal/tests/unit/test_program_files_provider.py` for how a provider and its `ProgramFile`s are built.
- [ ] **Step 2: Run it.** Expected: FAIL, no module `zos`.
- [ ] **Step 3: Bump, move, split and re-point**, as listed in Files.
- [ ] **Step 4: Run** the new test, the moved tests, `uv run lint-imports`, and every suite through the gate. Mutation-check: make `catnip/catnip/dataset.py` import `interpreter.data_value` and confirm `lint-imports` fails; drop the status-39 branch in `_admits_sequential` and confirm the new test fails. Revert both.
- [ ] **Step 5: Commit** in one go: `refactor(zos): COBOL file handling moves out of jackal; catnip stops loading the VM; bump red-dragon`. No trailers. Push.

### Task 5: plain mode runs the image directly (one forge commit)

**Files:**
- Create: `red_dragon_forge/plain_mode.py`, holding `run_plain`, the outcome rendering and the catalog relabeller.
- Modify: `red_dragon_forge/run_command.py` (`_plain` calls `run_plain`; delete `plain_job` and `_PLAIN_STEP`). `red_dragon_forge/plain_run.py` gets its own `DEFAULT_PLAIN_STEP_BUDGET = 500_000` in place of the jackal import. In `.importlinter`, add contract `plain-mode-without-jackal`: `red_dragon_forge.plain_mode` and `red_dragon_forge.plain_run` may not import `jackal`. Update `docs/reference/forge/run.md` (the `[plain]` section: no jackal, refusals, output lines).
- Test: `tests/integration/test_plain_mode.py` (forge root suite).

**Interfaces:**
- Consumes `zos.cobol.io` (Task 4), `interpreter.cobol.cee3abd_abend.user_abend` (Task 3), `interpreter.cobol.return_code_readback.read_return_code` (raises `SymbolicReturnCodeError` when the code is symbolic), `interpreter.run.run_linked_resumable` / `initial_vm_state`, `catnip.system_catalog.SystemCatalog.lookup(dsn) -> Dataset | NotCataloged` and `.relabel(dsn, label) -> Dataset`.
- Produces `red_dragon_forge.plain_mode.run_plain(package: Package, catalog: SystemCatalog, plain: PlainRun, builtins: Mapping[FuncName, Builtin], permit_unresolved_call_targets: bool) -> int`, which writes one line to stdout and returns the exit status. Relabelling goes through a `catnip.dataset.Relabeller` implementation over `SystemCatalog.relabel`.

- [ ] **Step 1: Write the failing tests.** Each builds a package with litter, from the `tmp_path` fixtures `tests/integration/` already uses for `forge-run`, runs `forge-run` (or `run_plain`), and asserts the exact stdout line, `==` on the exit status, and the stderr message where there is one:
  - `test_a_plain_program_ends_with_its_return_code`: `RETURN-CODE` 4 gives `"RC 4\n"`, exit 0.
  - `test_a_plain_program_that_calls_cee3abd_reports_the_user_abend`: code 1234 gives `"U1234\n"`, exit 1.
  - `test_an_abend_wins_over_a_symbolic_return_code`: a tolerated CALL to a missing program, then CEE3ABD with 7, gives `"U0007\n"`, exit 1 (Review Focus 4).
  - `test_a_symbolic_return_code_reports_rc_0_with_a_warning`: a tolerated missing CALL with no abend gives `"RC 0\n"`, exit 0, and a warning on stderr that the return code is unknown.
  - `test_a_plain_program_that_runs_out_of_budget_says_so`: `max_steps = 50` on a loop gives the budget-exhausted line (not containing `S322`), exit 1 (Review Focus 5).
  - `test_a_plain_file_not_in_the_catalog_is_refused_before_the_run`: exit 1, the message names the ASSIGN name and the DSN, and the program never runs (it would write a marker file).
  - `test_a_plain_output_dataset_is_labelled_on_first_open_and_read_back`: a catalogued dataset with a pending label, a writer run and then a reader run; the reader's records equal the writer's (Review Focus 2).
  - `test_two_plain_programs_select_the_same_name_apart`: Review Focus 3.
  - `test_an_unresolved_call_stops_the_run_unless_tolerated`: without `[tolerant]` permitting it, a CALL to a missing program exits 1 with the message naming the program (`interpreter.handlers.calls.UnresolvedProgramError`, as `run_command` handles it today).
- [ ] **Step 2: Run them.** Expected: FAIL, `run_plain` missing.
- [ ] **Step 3: Implement `run_plain`.** Resolve each `[plain.files]` DSN with `catalog.lookup`, and refuse on `NotCataloged` before running. Build `FileBindings` from those datasets (paths from each `Dataset.path`, `appended` empty) and a `ProgramFilesIOProvider` whose `provider_for` builds a `DatasetFileIOProvider`. Then call `run_linked_resumable(package.image, ProgramEntry(plain.program), max_steps=plain.max_steps, builtins=builtins, initial_vm=initial_vm_state(io_provider=provider), permit_unresolved_call_targets=permit_unresolved_call_targets)`. Map the outcome:
  - `Suspended` is an error, exit 1;
  - `BudgetExhausted` prints the budget line;
  - `Completed` checks `user_abend` first, then `read_return_code`, catching `SymbolicReturnCodeError` for the `RC 0` warning.
- [ ] **Step 4: Run** the tests and `uv run lint-imports`. Mutation-check: swap the abend and return-code checks and confirm the precedence test fails; make the refusal a warning and confirm the catalog test fails. Revert both.
- [ ] **Step 5: Gate and commit** `feat(forge): plain mode runs the image directly, without jackal`. No trailers. Push.
