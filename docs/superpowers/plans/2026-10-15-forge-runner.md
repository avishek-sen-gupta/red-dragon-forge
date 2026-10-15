# Forge Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One build command turns `build.toml` into a `litter` package (`<name>.zip`) of linked
programs; one run command runs it as `env.toml` says — `[plain]`, `[jcl]` or `[cics]` — without
parsing, lowering or linking.

**Architecture:** squall and cicada split into a compile surface (a `CoprocessorSpec` that only
lowers) and a runtime surface (`install_*_runtime`, which registers builtins over live state).
A new workspace member, `litter`, compiles programs into a zip and reads it back. jackal runs
packages only; cicada assembles a region from a package; the forge root holds the two commands.

**Tech Stack:** Python 3.13, uv workspace, pytest, red-dragon (`compile_program`,
`LinkedCodec`), catnip, jackal, cicada, squall, `hlasm_export`.

**Spec:** `docs/superpowers/specs/2026-10-15-forge-runner-design.md`

## Global Constraints

- `vendor/red-dragon` is never edited in the forge: red-dragon changes are made in
  `~/code/red-dragon`, pushed, then the submodule is bumped (`git -C vendor/red-dragon fetch &&
  git -C vendor/red-dragon checkout <sha>`).
- cicada, squall and jackal never import each other; `litter` imports no runtime (`cics`,
  `squall`, `jackal`, `cobble`, `red_dragon_forge`); only `red_dragon_forge` imports more than
  one runtime. `.importlinter` enforces it.
- The forge never serialises a `LinkedProgram` itself; linked files are written and read only
  by red-dragon's `LinkedCodec`.
- The transaction table always comes from CSD files, never a hand-written table.
- Datasets are never described in `env.toml`: `[plain.files]` names catalog datasets only.
- `min_commarea_len` defaults to 32763 (IBM, "Maximum length for the COMMAREA").
- Scope is parity: no runtime behaviour that is not present today.
- Gate per commit: `make fmt`, `uv run pyright` (strict, 0 new errors), `uv run lint-imports`,
  python-fp-lint by the pre-commit hook, the touched packages' suites; `make test-all` (with
  `. ./bridge-env.sh` and `squall/db2/dsn-env.sh`, Db2 up) before every push. Never
  `--no-verify`.
- No comments beyond a one-line module or class header; frozen dataclasses; no `for` loops with
  mutation; no `None` defaults or checks; no `Any`/`object`; no mocks or monkeypatching (inject
  fakes); concrete assertions; assertions are never weakened.
- Talisman: incidental-wording flags (field-name wording, test prose, file names) get a new entry
  or an in-place checksum replacement inside `fileignoreconfig`, before `version:`, no comments,
  using Talisman's reported checksum. Anything secret-like stops the task.
- Never name an external codebase under analysis in a tracked artifact; CardDemo is fine.
- Living docs (`docs/reference/**`, package READMEs, root `README.md`) change in the same commit
  as the behaviour; specs and records are never edited.

## Review Focus

1. A package built with sql run under `[plain]` or `[jcl]` with no `[sql]` section — the run
   must stop naming `[sql]` before any program starts, not fail on the first EXEC SQL.
2. A `[jcl]` step naming a program the package does not hold — jackal's missing-program
   strategy must settle it exactly as a missing source does today (CLI default: stub, RC 0).
3. A program compiled in one process and run in another — every builtin the old constructors
   registered must be present after `install_*_runtime`, including the three CICS hooks squall
   supplies (`__cics_task_end_hook`, `__cics_syncpoint_hook`, `__cics_rollback_hook`).
4. A `[cics]` package built `cics-conversational` versus `cics` — the region must run the
   lowering the package was built with; the run never re-lowers.
5. A rebuild with an unchanged `out_dir/work/` — red-dragon's intermediate files are reused
   and the rebuilt package's linked programs equal the first build's.

Each line has a pinning test in the task that owns the code (Tasks 2, 3, 4, 5, 8).

---

### Task 1: red-dragon — `compile_program` takes a work directory

**Files (in `~/code/red-dragon`):**
- Modify: `interpreter/project/coprocessor_compile.py` (`compile_program`)
- Test: `tests/unit/project/test_coprocessor_compile.py` (create if absent; else extend)

**Interfaces:**
- Produces: `compile_program(source, parser, specs, *, source_search_dirs=(), linked_subprogram_sources={}, tolerant=False, work_dir: Path = _FRESH) -> LinkedProgram`. `_FRESH` is a module sentinel meaning "a new temporary directory", passed through to `compile_cobol`'s `work_dir`.

- [ ] **Step 1: Write the failing test.** Compile a two-program fixture (a main that CALLs a
  subprogram, with no coprocessors) twice with the same `work_dir=tmp_path / "work"`. Assert:
  the work directory holds the `.ast.json` files of both programs after the first compile (sorted
  list of `(stem, program_id)` pairs, as the existing `test_cobol_compile.py` work-dir tests do);
  the second compile returns a `LinkedProgram` equal to the first; and the AST files' mtimes are
  unchanged by the second compile (reuse). Run: `uv run pytest -q tests/unit/project/test_coprocessor_compile.py` → FAIL (`unexpected keyword argument 'work_dir'`).
- [ ] **Step 2: Implement.** Add the parameter and forward it to `compile_cobol(..., work_dir=...)`.
  Use the same sentinel `compile_cobol` already uses for "fresh" (read `_cache_dir` at
  `cobol_compile.py:98`); do not introduce `None`. If reuse does not hold (AST files rewritten),
  report — do not change `compile_cobol`'s caching in this task.
- [ ] **Step 3: Mutation-check.** Drop the pass-through (the work dir stays empty → FAIL).
  Restore. `uv run pytest -q` → green.
- [ ] **Step 4: Commit and push** (red-dragon): `feat(project): compile_program takes a work
  directory`. Docs: `docs/linker-design.md` mentions the parameter where it describes
  `compile_program`. In the forge: bump `vendor/red-dragon`; `make test-all`; commit
  `chore(vendor): bump red-dragon — compile_program takes a work directory`; push.

### Task 2: squall — compile surface and runtime surface

**Files:**
- Modify: `squall/squall/coprocessor.py` (`build_sql_spec`), `squall/squall/strategy.py`
  (`SqlLoweringStrategy.__init__`, `_register_builtins`)
- Create: `squall/squall/runtime.py` (`install_sql_runtime`)
- Modify every caller (`rg -l "build_sql_spec\(|SqlLoweringStrategy\(" -g '*.py' --glob '!vendor'`):
  `red_dragon_forge/carddemo_db2_region.py`, `squall/tests/integration/squall_cobol_helpers.py`,
  `squall/tests/integration/cross_process_runner.py`, `squall/tests/unit/test_strategy.py`,
  `tests/integration/{test_sql_adapter,test_carddemo_db2_compile,test_jackal_sql_step,test_carddemo_db2_abend_rollback,test_cics_sql_composition,test_inqcust_e2e}.py`,
  `tests/unit/test_carddemo_db2_region_wiring.py`, `docs/presentation/capture/db2_inqcust_capture.py`
- Test: `squall/tests/unit/test_runtime.py` (create)

**Interfaces:**
- Produces:
  - `build_sql_spec(*, tolerant: bool = False) -> CoprocessorSpec` — name `"sql"`; its
    strategy registers nothing.
  - `install_sql_runtime(connections: Mapping[str, SqlBackend], initial_connector: DbConnector = _NO_CONNECTOR, *, tolerant: bool = False) -> None` — registers `__exec_sql`, `__cics_task_end_hook`, `__cics_syncpoint_hook`, `__cics_rollback_hook`, exactly as `_register_builtins` does today.
  - `SqlLoweringStrategy(*, tolerant: bool)` — lowering state only.

- [ ] **Step 1: Write the failing tests** in `squall/tests/unit/test_runtime.py`:
  1. `test_compile_spec_registers_nothing`: snapshot `dict(Builtins.TABLE)`, call
     `build_sql_spec(tolerant=False).make_strategy()`, assert the table equals the snapshot.
  2. `test_install_registers_the_four_builtins`: after `install_sql_runtime({"DB": SqliteBackend(sqlite3.connect(":memory:"))})`,
     assert `{n for n in Builtins.TABLE if n in _NAMES}` equals the four names above, and that
     `Builtins.TABLE["__exec_sql"]` is not the value it held before the call (it was replaced).
  3. `test_compiled_elsewhere_runs_after_install` (Review Focus 3): compile a fixture program
     with one `EXEC SQL SELECT ... INTO` using `build_sql_spec()`; write it with
     `LinkedCodec(IrCodec()).write` to `tmp_path`; in a subprocess (reuse the pattern in
     `squall/tests/integration/cross_process_runner.py`) read it back, call
     `install_sql_runtime` over a seeded SQLite backend, run it, and assert the host variable's
     value and `SQLCODE == 0`.
  Run: `cd squall && uv run --no-sync python -m pytest -q tests/unit/test_runtime.py` → FAIL.
- [ ] **Step 2: Implement.** Move the builtin construction and the four `register` calls out of
  `SqlLoweringStrategy.__init__` into `install_sql_runtime` in `squall/squall/runtime.py`
  (keep `register` from `squall.strategy_stores`). `SqlLoweringStrategy.__init__` keeps only
  `tolerant` (if lowering reads it), the WHENEVER table and `ProgramScope`. `build_sql_spec`
  drops `connections` and `initial_connector`. Update `build_sql_spec`'s docstring to the
  one-line header rule only if it is rewritten; otherwise leave it.
- [ ] **Step 3: Migrate every caller.** Each caller that compiled with
  `build_sql_spec(conns, conn, tolerant=t)` now calls `build_sql_spec(tolerant=t)` for the
  compile and `install_sql_runtime(conns, conn, tolerant=t)` before it runs. Assertions do not
  change. `red_dragon_forge/carddemo_db2_region.py` calls `install_sql_runtime` before
  `build_region`.
- [ ] **Step 4: Mutation-check.** Leave one `register` call in the strategy (test 1 fails);
  drop `__cics_rollback_hook` from `install_sql_runtime` (test 2 fails). Restore.
- [ ] **Step 5: Verify and commit.** `make test-all` → green. Docs:
  `docs/reference/squall/architecture.md` describes the two surfaces. Commit
  `refactor(squall): the SQL coprocessor splits into a compile spec and an installable runtime (red-dragon-forge-jr5)`; push.

### Task 3: cicada — compile surface and runtime surface

**Files:**
- Modify: `cicada/cics/coprocessor.py` (`build_cics_spec`), `cicada/cics/strategy.py`
  (`CicsLoweringStrategy.__init__` and the `_register_*_builtins` functions it calls),
  `cicada/cics/conversational.py`
- Create: `cicada/cics/runtime.py` (`install_cics_runtime`)
- Modify every caller (`rg -l "build_cics_spec\(|CicsLoweringStrategy\(" -g '*.py' --glob '!vendor'`
  lists 48 files today: `cobol_harness/region.py`, `cicada/cics/tn3270/region.py`,
  `docs/presentation/capture/*.py`, root `tests/integration/*`, `cicada/tests/integration/cics/*`)
- Test: `cicada/tests/unit/cics/test_runtime.py` (create)

**Interfaces:**
- Produces:
  - `build_cics_spec(*, conversational: bool = False) -> CoprocessorSpec` — name `"cics"`,
    `owns_execution=True`, same prepass, dialect parser and search dirs as today; its strategy
    registers nothing and its `.name` is `"cics-conversational"` when `conversational`.
  - `install_cics_runtime(context_holder: Holder[CicsContext], *, program_cache: MutableMapping[str, LinkedProgram], transid_to_program: Mapping[str, str], result_holder=NOT_SUPPLIED, td_queue=NOT_SUPPLIED, applid="CARDDEMO", sysid="SYS1", userid=DEFAULT_USERID, screen_queue=NOT_SUPPLIED, input_queue=NOT_SUPPLIED, vsam_engine=NOT_SUPPLIED, receive_timeout=30.0, start_queue=OWN_START_QUEUE, region_termid=DEFAULT_TERMID, on_abend=_noop) -> StartQueue` — calls `_register_core_builtins`, `_register_io_builtins`, `_register_interval_builtins` exactly as the constructor does today, and returns the start queue it used (the region needs it).
  - `CicsLoweringStrategy(*, conversational: bool, handler_source, unsupported_verbs)` — lowering state only.

- [ ] **Step 1: Write the failing tests** in `cicada/tests/unit/cics/test_runtime.py`:
  1. `test_compile_spec_registers_nothing`: as Task 2, for `build_cics_spec()` and
     `build_cics_spec(conversational=True)`.
  2. `test_install_registers_today_s_builtins`: record the set of `Builtins.TABLE` names a
     constructor registered at the base commit (write the expected set as a literal in the test,
     taken from `rg -o 'register(_default)?\("__cics_[a-z_]+"' cicada/cics/strategy.py`), call
     `install_cics_runtime` with a fresh `Holder`, `program_cache={}`, `transid_to_program={}`,
     and assert those names are present.
  3. `test_conversational_lowering_survives_the_split` (Review Focus 4): compile a fixture with
     `EXEC CICS RECEIVE MAP` under `build_cics_spec(conversational=True)` and assert the lowered
     IR holds the `SUSPEND` the conversational lowering emits; under `build_cics_spec()` it
     does not.
  Run: `cd cicada && uv run --no-sync python -m pytest -q tests/unit/cics/test_runtime.py` → FAIL.
- [ ] **Step 2: Implement.** Move the three `_register_*` calls and `_wiring` out of the
  constructor into `install_cics_runtime`. If any lowerer reads a value that moved (check
  `self._start_queue` in `_lower_start`), keep that lowerer's input on the strategy and report it.
- [ ] **Step 3: Migrate every caller.** Each caller passes the runtime arguments to
  `install_cics_runtime` and builds the spec with `build_cics_spec(conversational=...)`. Where
  a test file repeats the same pair more than twice, add one helper in the nearest existing
  test-helper module (`cicada/tests/integration/cics/` has helper modules; `cobol_harness` for
  the root) rather than a new one. Assertions do not change. `build_region` keeps its signature
  in this task and calls `install_cics_runtime` itself.
- [ ] **Step 4: Mutation-check.** Leave `_register_interval_builtins` in the constructor (test 1
  fails); drop it from `install_cics_runtime` (test 2 fails). Restore.
- [ ] **Step 5: Verify and commit.** `make test-all` → green (CardDemo e2e included). Docs:
  `docs/reference/cicada/*` where it describes `build_cics_spec`. Commit
  `refactor(cicada): the CICS coprocessor splits into a compile spec and an installable runtime (red-dragon-forge-jr5)`; push.

### Task 4: litter — the package member

**Files:**
- Create: `litter/pyproject.toml`, `litter/litter/__init__.py` (one-line header),
  `litter/litter/transaction.py`, `litter/litter/cics_file.py`, `litter/litter/manifest.py`, `litter/litter/package.py`,
  `litter/litter/package_error.py`, `litter/litter/build.py`, `litter/litter/open.py`,
  `litter/tests/__init__.py`, `litter/tests/unit/test_manifest.py`,
  `litter/tests/integration/test_build_and_open.py`, `litter/tests/conftest.py`,
  `litter/tests/fixtures/cbl/{MAINPGM,SUBPGM}.cbl`, `docs/reference/litter/README.md`
- Modify (mirror every catnip entry): root `pyproject.toml` (`members`), `uv.lock` (`uv lock`),
  `Makefile` (`BLACK_PATHS`, `test-all` runs `cd litter && . ../bridge-env.sh && $(PYTEST)`
  under `$(BRIDGE_ENV)`), `.pre-commit-config.yaml` (black, pyright `files:`; a `tests-litter`
  hook like `tests-catnip` but sourcing `bridge-env.sh`; add `litter/` to the `files:` of
  tests-cicada, tests-jackal, tests-forge), `pyrightconfig.json` (`litter/litter`),
  `.importlinter` (`root_packages` gains `litter`; new contract `litter-imports-no-runtime`
  forbidding `cics`, `squall`, `jackal`, `cobble`, `catnip`, `red_dragon_forge`; `litter` joins
  the `source_modules` of `nothing-imports-cobble`), `bridge-env.sh` (exports
  `HLASM_EXPORT="$FORGE_ROOT/cicada/third-party/che-che4z-lsp-for-hlasm-fork/build/bin/hlasm_export"`,
  warning like the JARs when missing), `README.md` package table,
  `docs/reference/forge/architecture.md`.

**Interfaces:**
- Consumes: Task 1's `compile_program(..., work_dir=...)`.
- Produces:
  - `litter.transaction.Transaction(transid: str, program: str)` (frozen).
  - `litter.cics_file.CicsFile(name: str, dsname: str)` (frozen) — one CSD `DEFINE FILE`.
  - `litter.manifest.Manifest(programs: tuple[str, ...], coprocessors: tuple[str, ...], transactions: tuple[Transaction, ...], files: tuple[CicsFile, ...], mapsets: tuple[str, ...])` — a Pydantic model (frozen), the only thing serialised to `manifest.json`.
  - `litter.package.Package(manifest: Manifest, programs: Mapping[str, LinkedProgram], mapsets: Mapping[str, str])` (frozen dataclass; `mapsets` maps a mapset name to its `hlasm_export` JSON text — the one-hop boundary cicada parses on arrival).
  - `litter.build.build(*, name: str, programs: Sequence[str], sources: Mapping[str, Path], parser: ProLeapCobolParser, specs: Sequence[CoprocessorSpec], search_dirs: Sequence[Path], work_dir: Path, out_dir: Path, transactions: Sequence[Transaction], files: Sequence[CicsFile], mapsets: Mapping[str, Path], tolerant: bool) -> Path` — returns `out_dir / f"{name}.zip"`; `coprocessors` in the manifest are the specs' strategy names (`spec.make_strategy().name`), so `cics-conversational` is recorded as such.
  - `litter.open.open_package(path: Path) -> Package` — raises `litter.package_error.PackageError` naming the path and entry for a missing entry, a manifest that fails validation, or a linked file that fails `LinkedCodec.read`.

- [ ] **Step 1: Scaffold the member** from catnip's files (same `requires-python = ">=3.13"`,
  dependencies `["pydantic>=2.0", "red-dragon"]`, hatch packages `["litter"]`, dev group).
  `uv lock && uv sync --all-packages`. `uv run lint-imports` → contracts kept.
- [ ] **Step 2: Write the failing tests.**
  - `test_manifest.py`: a `Manifest` round-trips through `model_dump_json`/`model_validate_json`
    with two transactions, one file and one mapset, equal to itself.
  - `test_build_and_open.py` (needs `PROLEAP_BRIDGE_JAR`; the `bridge_jar` fixture skips
    nothing — it fails loudly if unset, as jackal's conftest does):
    1. `test_built_package_opens_to_the_compiled_programs`: build `MAINPGM` (which CALLs
       `SUBPGM`) with no specs; `open_package` returns a `Package` whose
       `programs["MAINPGM"]` equals `compile_program(...)` of the same source, whose manifest is
       `Manifest(programs=("MAINPGM",), coprocessors=(), transactions=(), files=(), mapsets=())`, and the
       zip's names are exactly `["manifest.json", "programs/MAINPGM.linked.json"]`.
    2. `test_rebuild_reuses_the_work_directory` (Review Focus 5): build twice with the same
       `work_dir`; the AST files' mtimes are unchanged and the two packages' programs are equal.
    3. `test_open_names_a_missing_entry`: delete `programs/MAINPGM.linked.json` from the zip
       (rewrite it without that entry); `open_package` raises `PackageError` whose message is
       `f"{path}: programs/MAINPGM.linked.json: missing"`.
    4. `test_open_names_an_unreadable_linked_file`: replace the entry with
       `{"format": 1, "linked": {}}`; the message starts `f"{path}: programs/MAINPGM.linked.json: "`.
    5. `test_mapsets_ship_unchanged`: build with `mapsets={"COSGN00": tmp/"COSGN00.json"}`
       (a JSON text written by the test); `open_package(...).mapsets["COSGN00"]` equals that text.
  Run: `cd litter && uv run --no-sync python -m pytest -q` → FAIL.
- [ ] **Step 3: Implement** `build`: for each program, `compile_program(sources[p].read_bytes(), parser, specs, source_search_dirs=search_dirs, tolerant=tolerant, work_dir=work_dir / p)`;
  write each with `LinkedCodec(IrCodec()).write(linked, staging / "programs" / f"{p}.linked.json")`;
  write `manifest.json` with `Manifest.model_dump_json(indent=2)`; copy each mapset file to
  `maps/<NAME>.json`; zip the staging directory (`zipfile.ZipFile`, `ZIP_DEFLATED`) to
  `out_dir/<name>.zip`. `open_package`: read the manifest with `model_validate_json`; extract
  each linked file to a temporary directory and read it with `LinkedCodec.read`; read each
  mapset entry as text. Log each program built and each entry read (`logging`).
- [ ] **Step 4: Mutation-check.** Skip `work_dir` (test 2 fails); drop the entry-name prefix
  from the error (tests 3–4 fail). Restore.
- [ ] **Step 5: Verify and commit.** `make test-all` → green. Docs:
  `docs/reference/litter/README.md` (what the package holds, `build`, `open_package`),
  `docs/README.md` index, root `README.md` table. Commit
  `feat(litter): a package of linked programs — build once, open to run (red-dragon-forge-jr5)`; push.

### Task 5: jackal — runs packages only

**Files:**
- Modify: `jackal/jackal/runner.py` (`JobRunner`), `jackal/jackal/cli.py` (`run`),
  `jackal/pyproject.toml` (depends on `litter`, `{ workspace = true }`)
- Delete: `jackal/jackal/program_compiler.py`, `jackal/jackal/program_sources.py`
- Create: `jackal/tests/package_build.py` (test helper: `package(tmp_path, programs, source_dir=FIXTURE_CBL, copybook_dir=FIXTURE_CPY) -> Package`, building with `litter.build.build` and `LE_STUBS` on the search path, then `open_package`)
- Modify: every `JobRunner(` / `ProgramCompiler` site (`rg -l "JobRunner\(|ProgramCompiler" -g '*.py' --glob '!vendor'`: 16 in `jackal/tests`, 6 `ProgramCompiler` test files, `tests/integration/test_carddemo_data_install.py`, `tests/integration/test_jackal_sql_step.py`, `docs/presentation/capture/jcl_capture.py`)
- Test: `jackal/tests/unit/test_runner.py`, `jackal/tests/integration/test_called_programs.py`

**Interfaces:**
- Consumes: Task 4's `Package`, `build`, `open_package`; Task 2's `install_sql_runtime` (root test only).
- Produces: `JobRunner(package: Package, system: SystemCatalog, unresolved, missing_data, missing_program, program_step_budget: int, proclib_dirs: Sequence[Path] = ())`. A step's program is `CompiledProgram(package.programs[name], program_files_of(package.programs[name]))`; a name the package lacks goes to `missing_program.settle`. `jackal.cli run JCL --system DIR --package ZIP [--proclib DIR]...`.

- [ ] **Step 1: Write the failing tests.**
  - `test_runner.py::test_a_program_the_package_lacks_is_a_missing_program` (Review Focus 2):
    a package holding `PGMA` only; a two-step job running `PGMA` then `PGMB` under
    `StubMissingProgram()` → step results `[Completed(0), Completed(0)]` and the stub's warning
    logged once naming `PGMB` (`caplog`); under `AbendMissingProgram()` →
    `[Completed(0), Abended(SystemAbend(0x806))]`.
  - `test_called_programs.py`: its existing assertions, with the runner built from
    `package(tmp_path, ("MAIN",))`.
  Run → FAIL (`JobRunner` has no `package`).
- [ ] **Step 2: Implement.** `JobRunner.__init__` takes the package; `_found` looks the
  program up in `package.programs`; `CompiledProgram` moves into `jackal/jackal/cobol_step.py`
  (its only consumer). Delete `ProgramCompiler`, `ProgramSources`, `DirectoryProgramSources`,
  `LinkedProgramNotFound`, `_linked_source`. CLI: `--package` replaces `--source-dir`,
  `--copybook-dir` and `--link`; defaults (`RaiseErrorStrategy`, `LenientAllocation`,
  `StubMissingProgram`, `DEFAULT_PROGRAM_STEP_BUDGET`) unchanged.
- [ ] **Step 3: Migrate every site** to `package(...)`. Tests that exercised `ProgramCompiler`
  directly assert the same things through `package(...)` + `JobRunner` or through
  `run_cobol_step` with `CompiledProgram`. `tests/integration/test_jackal_sql_step.py` builds
  with `build_sql_spec()` and calls `install_sql_runtime({"SAMPLE": SqliteBackend(conn)})`
  before `runner.run`. Assertions do not change; list any test whose setup changed form in the
  report.
- [ ] **Step 4: Mutation-check.** Make `_found` raise on a missing name (the missing-program
  test fails). Restore.
- [ ] **Step 5: Verify and commit.** `rg -n "source_dir|ProgramCompiler|ProgramSources" jackal`
  → nothing. `make test-all` → green. Docs: `docs/reference/jackal/*` (CLI usage, how a step
  finds its program). Commit `feat(jackal): a job runs against a litter package; jackal no longer compiles (red-dragon-forge-jr5)`; push.

### Task 6: cicada — mapsets from JSON, and a region assembled from a package

**Files:**
- Modify: `cicada/cics/bms/catalog.py` (split `load_catalog` into `mapset_json(bms_file, hlasm_export_bin, syslib_dirs) -> str` and `catalog_from_json(texts: Sequence[str]) -> MapCatalog`; `load_catalog` composes them), `cicada/cics/tn3270/region.py` (`build_region` → `assemble_region`), `cicada/cics/tn3270/cli.py`, `cicada/cics/tn3270/config.py`, `cicada/pyproject.toml` (depends on `litter`)
- Test: `cicada/tests/unit/cics/test_map_catalog.py` (extend or create), `cicada/tests/integration/cics/test_region_from_package.py` (create)

**Interfaces:**
- Consumes: Task 3's `install_cics_runtime`, `build_cics_spec`; Task 4's `Package`, `build`.
- Produces:
  - `assemble_region(package: Package, system: SystemCatalog, *, min_commarea_len: int = MAX_COMMAREA, on_abend: Callable[[], None] = _region_noop) -> ServedRegion` — installs the CICS runtime over `program_cache = dict(package.programs)`, `transid_to_program` from `package.manifest.transactions`, the VSAM engine from `cics_files(system, {f.name: f.dsname for f in package.manifest.files})`; map catalog from `catalog_from_json(package.mapsets.values())`.
  - `MAX_COMMAREA = 32763` in `cicada/cics/dispatcher.py`.
  - `compile_region_package(config: RegionConfig, bridge_jar: str, hlasm_export: str, work_dir: Path, out_dir: Path) -> Path` — what `build_region`'s compile half did, through `litter.build` (used by `cicada-tn3270` so it keeps working until the follow-up retires it).

- [ ] **Step 1: Write the failing tests.**
  - `test_map_catalog.py::test_catalog_from_json_equals_load_catalog`: for CardDemo's
    `COSGN00.bms`, `catalog_from_json([mapset_json(f, hlasm, syslib)])` equals
    `load_catalog(dir_with_only_that_file, hlasm)`.
  - `test_region_from_package.py::test_sign_on_screen_from_a_package`: build a package of
    CardDemo's `COSGN00C` with `build_cics_spec()`, the sign-on mapset JSON and the CardDemo CSD
    transactions; `assemble_region(open_package(zip), system)`; drive one turn of
    transaction `CC00`; assert the first screen's rendered rows equal those the existing
    sign-on e2e test asserts (copy its expected rows).
  - `test_region_from_package.py::test_min_commarea_len_defaults_to_the_cics_maximum`: a region
    assembled without the argument pads a follow-on COMMAREA to 32763 bytes (assert the
    length the dispatcher hands the program, through the same seam
    `test_commarea_roundtrip.py` uses).
  Run → FAIL.
- [ ] **Step 2: Implement.** Split the catalog loader. Split `build_region`: the compile half
  becomes `compile_region_package`; the assemble half becomes `assemble_region`, which no
  longer compiles and no longer takes `extra_specs` (the caller installs other runtimes). The
  region TOML loses `min_commarea_len` (the default replaces it; the two configs that set 2000
  drop the line) and gains nothing else. `cicada-tn3270` compiles with
  `compile_region_package` then assembles.
- [ ] **Step 3: Migrate callers** of `build_region` (`rg -l "build_region\(" -g '*.py' --glob '!vendor'`, including `red_dragon_forge/carddemo_db2_region.py`, which installs the SQL runtime and assembles). Assertions unchanged.
- [ ] **Step 4: File a bead** (`bd create ... --type task`): "CICS COMMAREA: pad to the caller's
  real storage instead of a 32763-byte default". `bd export -o issues/issues.jsonl`.
- [ ] **Step 5: Mutation-check** (catalog: drop one mapset → test fails; default: 0 → test
  fails). `make test-all` → green. Docs: `docs/reference/cicada/*` (region assembly, the
  dropped TOML setting). Commit `feat(cicada): a region assembles from a litter package; mapsets load from hlasm_export JSON (red-dragon-forge-jr5)`; push.

### Task 7: forge root — the build command

**Files:**
- Create: `red_dragon_forge/build_config.py` (`BuildConfig` Pydantic model of `build.toml`),
  `red_dragon_forge/build_command.py` (`main`), `tests/unit/test_build_config.py`,
  `tests/integration/test_build_command.py`, `tests/integration/fixtures/build/build.toml`
- Modify: root `pyproject.toml` (`[project.scripts] forge-build = "red_dragon_forge.build_command:main"`; dependency on `litter`), `docs/reference/forge/*` (a "Build" page)

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces: `forge-build BUILD_TOML` → writes `out_dir/<name>.zip`, prints its path, exit 0.
  `load_build_config(path: Path) -> BuildConfig`.

- [ ] **Step 1: Write the failing tests.**
  - `test_build_config.py`: the fixture TOML parses to the expected `BuildConfig` (literal);
    `coprocessors = ["cics"]` with no `[cics]` → `ConfigError("build.toml: [cics] is required when coprocessors include cics")`; an unknown coprocessor name → `ConfigError` naming it.
  - `test_build_command.py::test_builds_a_cics_and_a_batch_program`: fixture `build.toml` with
    `COSGN00C` and a batch program, `coprocessors = ["cics"]`, CardDemo's sign-on BMS and CSD;
    the package's manifest equals
    `Manifest(programs=("CBACT01C","COSGN00C"), coprocessors=("cics",), transactions=<the CSD's>, files=<the CSD's>, mapsets=("COSGN00",))`, both tables written as literals from the fixture CSD.
  - `test_build_command.py::test_an_unset_tool_variable_stops_the_build`: with `HLASM_EXPORT`
    removed from the child's environment (run `forge-build` as a subprocess with an explicit
    `env`), exit code 1 and stderr `forge-build: HLASM_EXPORT is not set`; the same for
    `PROLEAP_BRIDGE_JAR`.
  Run → FAIL.
- [ ] **Step 2: Implement.** Read the TOML (`tomllib`) into `BuildConfig` immediately. Build
  compile specs: `sql` → `build_sql_spec()`; `cics` / `cics-conversational` →
  `build_cics_spec(conversational=...)`. For cics: `mapset_json` per `*.bms` under `bms_dirs`,
  `generate_symbolic_copybooks` into `out_dir/work/sym` (on the copybook path), transactions
  from `parse_csd` and files from `parse_csd_files` over `csd_files`, mapped to `Transaction`
  and `CicsFile`. Sources resolve first-hit-wins over
  `source_dirs` (`<dir>/<NAME>.cbl`); an unfound program stops the build naming it. Search dirs:
  `source_dirs` + `LE_STUBS`. Call `litter.build.build`.
- [ ] **Step 3: Mutation-check** (drop the CSD → manifest test fails; drop the env check → the
  tool-variable test fails). `make test-all` → green. Commit `feat(forge): forge-build turns build.toml into a litter package (red-dragon-forge-jr5)`; push.

### Task 8: forge root — the run command

**Files:**
- Create: `red_dragon_forge/env_config.py` (`EnvConfig` with exactly one of `PlainRun`,
  `JclRun`, `CicsRun`, plus `SqlSection | NoSql`), `red_dragon_forge/run_command.py` (`main`),
  `tests/unit/test_env_config.py`, `tests/integration/test_run_command.py`,
  `tests/integration/fixtures/run/{plain,jcl,cics,bad_*}.toml`
- Modify: root `pyproject.toml` (`forge-run = "red_dragon_forge.run_command:main"`),
  `docs/reference/forge/*` (a "Run" page)

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces: `forge-run ENV_TOML`. `[plain]` prints `RC=<n>` and exits 0 (1 on abend);
  `[jcl]` prints jackal's per-step report and its exit code; `[cics]` serves until interrupted.

- [ ] **Step 1: Write the failing tests.**
  - `test_env_config.py` — each D6 error, exact messages:
    - no mode section → `env.toml: exactly one of [plain], [jcl], [cics] is required; found none`;
    - two → `...; found [plain], [jcl]`;
    - `[plain]` program not in the manifest → `env.toml: program CBXXXX is not in out/app.zip`;
    - manifest names sql, no `[sql]` (Review Focus 1) → `env.toml: [sql] is required: out/app.zip was built with sql`, raised before any runtime is installed;
    - `[cics]` without `initial_transid` → `env.toml: [cics] initial_transid is required`.
  - `test_run_command.py::test_plain_matches_a_one_step_job`: a package with a batch program
    that copies one cataloged dataset to another; `[plain]` with `[plain.files]` naming both;
    the output dataset's records and the RC equal those of the equivalent one-step `[jcl]` run
    on a fresh catalog.
  - `test_run_command.py::test_jcl_runs_a_multi_step_job_from_a_package`: the step results equal
    what `jackal run` prints today for the same job (literal).
  - `test_run_command.py::test_cics_serves_sign_on_from_a_package`: start `forge-run` on a free
    port in a subprocess, connect with the TN3270 test client the cicada e2e tests use, assert
    the sign-on screen's rows; terminate.
  - `test_run_command.py::test_plain_sql_from_a_package` (Db2-marked like the other Db2 tests):
    a package built with sql, `[sql]` present, `SQUALL_DB2_DSN` set → the program's SELECT
    result is in its output.
  Run → FAIL.
- [ ] **Step 2: Implement.** Parse `env.toml` into `EnvConfig` on arrival; open the package;
  check the manifest against the config (the errors above) before anything runs. Install
  runtimes for the manifest's coprocessors (`sql` → `install_sql_runtime` over a `Db2Backend`
  from `SQUALL_DB2_DSN`, with the top-level `tolerant`; `cics` → done inside `assemble_region`). `[plain]`: a one-step
  `Job` built in code — `ProgramStep(StepName("PLAIN"), ProgramRef(program), dds)` with one
  `DD(DdName(assign), DirectDSN(literal(dsn)), disp_from_words(("SHR",)))` per
  `[plain.files]` entry — run by `JobRunner` with jackal CLI's defaults and
  `program_step_budget=max_steps`. `[jcl]`: `parse_jcl` the job, `JobRunner(package, ...)`
  with `proclib_dirs`. `[cics]`: `assemble_region`, then bind and serve as `cicada-tn3270` does.
- [ ] **Step 3: Mutation-check** (skip the sql check → its test fails at the first EXEC SQL
  instead; build the plain DD with `DISP=NEW` → the plain test fails). `make test-all` →
  green. Commit `feat(forge): forge-run runs a package as env.toml says — plain, JCL or CICS (red-dragon-forge-jr5)`; push.
- [ ] **Step 4: File the follow-up bead**: "Migrate CardDemo onto build.toml + env.toml; retire
  cicada-tn3270, carddemo-db2-cli and the aggregate region TOMLs" (depends on jr5). Close jr5.
  `bd export -o issues/issues.jsonl`; commit `chore(beads): jr5 done; CardDemo migration filed`; push.
