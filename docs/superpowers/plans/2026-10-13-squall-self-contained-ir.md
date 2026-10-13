# squall Self-Contained EXEC SQL IR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `__exec_sql` call site carries what the builtin needs (statement text, an OPEN's cursor declaration, VARCHAR shapes), so a SQL program lowered in one process runs in another; DCLGEN sidecars are removed.

**Architecture:** Three commits in the forge. (1) Delete the DCLGEN JSON sidecar and everything that reads it. (2) Change the builtin's arguments and the lowering together: statement text replaces the plan index, OPEN carries its declaration, VARCHAR shapes travel as `str` triples; `SharedSqlStores` and the plan/cursor/metadata stores go. (3) A cross-process test, docs, gate, push.

**Tech Stack:** Python 3.13, uv workspace, pytest, Lark (`squall.parser`), red-dragon IR (`vendor/red-dragon`, read-only).

**Spec:** `docs/superpowers/specs/2026-10-13-squall-self-contained-ir-design.md`

## Global Constraints

- Ruling (user, 2026-10-13): as much information as possible travels in the IR, unless that makes no logical sense.
- `vendor/red-dragon` is not modified. No red-dragon change is needed.
- Verification gate (forge): `make fmt`, `uv run pyright`, `uv run lint-imports`, `pre-commit run python-fp-lint-check --hook-stage manual --all-files`, then `. ./bridge-env.sh && make test-all` (Db2 healthy: `docker inspect -f '{{.State.Health.Status}}' squall-db2`).
- `squall/squall/strategy.py`, `squall/squall/strategy_stores.py`, `squall/squall/builtins/exec_sql.py` are fp-lint exclusions with written reasons in `fp.json`; a change that alters what a file does updates its reason in the same commit, and a file that no longer needs exclusion leaves the list.
- Talisman flags some ordinary words in prose; reword the prose and keep identifier names (see the Talisman memory).
- No comments beyond one-line module/class headers in new code; frozen dataclasses; no `Any`/`object` in new signatures.

## Review Focus

1. A FETCH INTO a VARCHAR host variable — its shape must travel on the FETCH call (out vars), not only on the OPEN.
2. An OPEN ... USING with host variables, where the cursor's own SELECT has different host variables — shapes come from the USING list.
3. A program with two cursors and a PERFORM loop issuing the same OPEN/FETCH/CLOSE repeatedly — each statement parsed once per process (memo by text).
4. A CICS+SQL composed program (CardDemo DB2 variant, COTRTLIC): task end / SYNCPOINT ROLLBACK must still close every open cursor now that the DECLARE registry is gone.
5. Two SQL programs in one spec with the same host-variable name, one a VARCHAR group and one not — each binds by its own shape.

Each line is pinned by a test in Task 2 (items 1, 2, 3, 5) or Task 3 (item 4 via the composition suites).

---

### Task 1: Remove DCLGEN sidecars

The sidecar repeats its copybook (spec §1). Behaviour is unchanged except that no JSON/copybook drift check runs.

**Files:**
- Modify: `squall/squall/dclgen.py` (drop `GeneratedRecord.metadata`, the JSON write, `import json`; fix the stale "VARCHAR raises" docstring line)
- Modify: `squall/squall/preprocess.py` (`apply_sql_prepass(source) -> str`; delete `PrepassResult`, `_load_field_meta`)
- Modify: `squall/squall/binding.py` (delete `FieldMetaMismatch`, `validate_field_meta` and its private helpers `_require_category`, `_Category`, `_NoCategory`, `_category_of`, `_check_varchar_category`, `_check_present_category`, `_check_field_meta_category`, `_validate_one_field_meta`)
- Modify: `squall/squall/builtins/exec_sql.py` (drop the `validate_field_meta` call and import)
- Modify: `squall/squall/strategy.py` (constructor drops `field_meta`)
- Modify: `squall/squall/strategy_stores.py` (delete `absorb_field_meta`, `SharedSqlStores.sidecar_field_names`; `merge_field_meta(store, derived)` loses its third parameter)
- Modify: `squall/squall/coprocessor.py` (`build_sql_spec` drops `copybook_dirs`; `_prepass` returns `apply_sql_prepass(source)`)
- Modify callers of `build_sql_spec(..., copybook_dirs=...)`: `red_dragon_forge/carddemo_db2_region.py`, `tests/integration/test_carddemo_db2_compile.py`, `tests/integration/test_inqcust_e2e.py`, `tests/integration/test_carddemo_db2_abend_rollback.py`, `docs/presentation/capture/db2_inqcust_capture.py`, `squall/tests/integration/squall_cobol_helpers.py`, `tests/unit/test_carddemo_db2_region_wiring.py`
- Delete: `squall/tests/unit/test_field_meta_validation.py`
- Modify tests: `squall/tests/unit/test_preprocess.py`, `squall/tests/unit/test_dclgen.py`, `squall/tests/unit/test_strategy.py`, `squall/tests/unit/test_strategy_stores.py`, `squall/tests/integration/test_crud_e2e.py`, `squall/tests/integration/test_include_dclgen_e2e.py`

**Interfaces:**
- Produces: `apply_sql_prepass(source: str) -> str`; `dclgen.write(record, out_dir) -> Path` (the copybook path); `GeneratedRecord(record_name: str, copybook: str)`; `SqlLoweringStrategy(connections, initial_connector=..., *, tolerant=..., stores=...)`; `build_sql_spec(connections, *, initial_connector=..., tolerant=...)` (its other named parameters unchanged).

- [ ] **Step 1: Rewrite the tests to the new interfaces (they fail)**

`squall/tests/unit/test_preprocess.py`: delete the sidecar tests (`test_include_loads_dclgen_json_into_field_meta`, `test_include_without_json_sidecar_yields_empty_meta`, and any other test whose assertion reads `.field_meta`); every remaining `apply_sql_prepass(source, <dirs>)` / `apply_sql_prepass(source, copybook_dirs=<dirs>)` becomes `apply_sql_prepass(source)` and `.source` is dropped — e.g.

```python
    assert apply_sql_prepass(source) == source
```

`squall/tests/unit/test_dclgen.py`: delete `test_generate_metadata` and `test_generate_varchar_metadata` (the copybook tests above them already pin the same categories and the VARCHAR 49-group); `test_prefix_applied_to_host_vars` becomes

```python
def test_prefix_applied_to_host_vars() -> None:
    rec = generate(_seed(), "ACCOUNT", record_name="ACCT-REC", prefix="WS-")
    assert "05  WS-ACCT-ID" in rec.copybook
```

`squall/tests/integration/test_crud_e2e.py`: `write(rec, tmp_path)` returns the copybook path; replace the `(tmp_path / "ACCTREC.json").is_file()` assertion with

```python
    assert write(rec, tmp_path) == tmp_path / "ACCTREC.cpy"
    assert not (tmp_path / "ACCTREC.json").exists()
```

and the second `write(rec, tmp_path)` call (the VARCHAR test, ~line 160) stays; reword its comment to say the VARCHAR shape is inferred from the copybook's 49-level group. Its assertions stay — they now prove inference replaces the sidecar.

`squall/tests/unit/test_strategy.py`: `SqlLoweringStrategy(backend, {})` → `SqlLoweringStrategy(backend)` everywhere; delete `test_sidecar_field_meta_wins_over_derived_on_conflict`.

`squall/tests/unit/test_strategy_stores.py`: delete every test that uses `absorb_field_meta` or `sidecar_field_names`; `merge_field_meta(store, derived, names)` calls lose the third argument.

`squall/tests/integration/test_include_dclgen_e2e.py`: if a test writes a `.json` sidecar, delete that write; its assertions stay.

Delete `squall/tests/unit/test_field_meta_validation.py`.

- [ ] **Step 2: Run and see them fail**

Run: `cd squall && uv run --no-sync python -m pytest tests/unit/test_preprocess.py tests/unit/test_dclgen.py tests/unit/test_strategy.py tests/unit/test_strategy_stores.py -q`
Expected: FAIL — `TypeError` on `apply_sql_prepass()` arity / `SqlLoweringStrategy` arity, `AttributeError: 'str' object` comparisons, `write` return shape.

- [ ] **Step 3: Implement**

`squall/squall/preprocess.py`:

```python
def apply_sql_prepass(source: str) -> str:
    """Rewrite ``EXEC SQL INCLUDE <name> END-EXEC`` → ``COPY <name>.``.

    All other EXEC SQL blocks and all ordinary COBOL text are returned
    byte-for-byte unchanged, including line endings. Every rewrite goes through
    ``squall.fixed_format.replace_span`` / ``with_code``, which write only the
    code area (columns 8-72).
    """
    bodies, terminators = _split_source(source)
    lines = tuple(parse_line(body) for body in bodies)
    includes = list(_includes(find_exec_sql_spans(lines)))
    if not includes:
        return source
    # ... the existing rewrite body, unchanged, ending in:
    return _join_source(rewritten_bodies, terminators)
```

Delete `PrepassResult`, `_load_field_meta`, and imports that become unused (`json`, `MappingProxyType`, `FieldMeta`, `Path` if unused).

`squall/squall/dclgen.py`: `GeneratedRecord` keeps `record_name` and `copybook`; `generate` stops building `metadata`; `_field_meta` keeps returning the per-field dict `_render_copybook` reads (rename it `_field` — it is no longer metadata); `write`:

```python
def write(record: GeneratedRecord, out_dir) -> Path:
    """Write ``<RECORD>.cpy`` into *out_dir*; return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cpy = out / f"{record.record_name}.cpy"
    cpy.write_text(record.copybook, encoding="utf-8")
    return cpy
```

Module docstring: replace "plus a JSON sidecar of per-field metadata" and the paragraph about the JSON with one sentence: the copybook alone carries each host variable's type; VARCHAR columns render as the DCLGEN 49-level LEN/TEXT group. Replace the stale "VARCHAR ... raise NotImplementedError" bullet with "VARCHAR renders as a 49-level LEN/TEXT group".

`squall/squall/binding.py`: delete the validation block listed under Files. `_read_one` / `_plan_assignment` still read `field_meta` for the VARCHAR shape — unchanged.

`squall/squall/builtins/exec_sql.py`: delete the `validate_field_meta(...)` line and its comment, and the import.

`squall/squall/strategy.py`: delete the `field_meta` parameter and the `_absorb_field_meta(...)` call; the store starts empty and `preprocess_program_dict` calls `merge_field_meta(self._field_meta_store, derive_field_meta(data))`. Update the docstring/comments that describe the sidecar.

`squall/squall/strategy_stores.py`: delete `absorb_field_meta` and `sidecar_field_names`; `merge_field_meta(store, derived)` keeps the in-place replace semantics minus the sidecar exemption.

`squall/squall/coprocessor.py`: `build_sql_spec` drops `copybook_dirs`; `_prepass` is `return apply_sql_prepass(source)`; `_make_strategy` calls `SqlLoweringStrategy(connections, initial_connector=initial_connector, tolerant=tolerant, stores=stores)`; docstring: delete the sidecar sentence and "``FieldMetaMismatch``" from the tolerant paragraph (tolerant skips host variables missing from the layout).

Each listed caller drops its `copybook_dirs=` argument to `build_sql_spec` (the parser keeps its own `copybook_dirs`). `tests/unit/test_carddemo_db2_region_wiring.py`'s fake keeps `**kwargs` and stops asserting on `copybook_dirs` if it does.

- [ ] **Step 4: Grep for the old shape**

Run: `rg -n "sidecar|FieldMetaMismatch|validate_field_meta|absorb_field_meta|PrepassResult|\.json\b" squall/squall red_dragon_forge tests squall/tests docs/reference -g '*.py' -g '*.md'`
Expected: no hits that refer to DCLGEN sidecars (CICS/JCL `.json` hits are unrelated).

- [ ] **Step 5: Run the squall suite and the root SQL tests**

Run: `. ./bridge-env.sh && cd squall && uv run --no-sync python -m pytest -q 2>&1 | tail -2; cd .. && uv run --no-sync python -m pytest tests/integration/test_sql_adapter.py tests/integration/test_cics_sql_composition.py tests/unit/test_carddemo_db2_region_wiring.py -q 2>&1 | tail -2`
Expected: all succeed.

- [ ] **Step 6: Mutation check**

In `squall/squall/strategy.py`, skip the `merge_field_meta(...)` call in `preprocess_program_dict` → `test_crud_e2e`'s VARCHAR test fails (the inference is now the only source). Restore.

- [ ] **Step 7: Commit**

Update `docs/reference/squall/architecture.md` row for `dclgen.py` ("Generates a host-variable copybook from a table schema.") and `preprocess.py` ("Source rewrite before ProLeap: `EXEC SQL INCLUDE x` → `COPY x`."). Then:

```bash
git add -A squall red_dragon_forge tests docs/reference/squall/architecture.md docs/presentation/capture/db2_inqcust_capture.py
git commit -m "refactor(squall): drop DCLGEN JSON sidecars

The sidecar repeated its copybook: each category is what data_layout derives
from the PIC, and the VARCHAR LEN/TEXT group is inferred from the DATA
DIVISION. Its only remaining use was a per-call check that the two agreed.
squall's DCLGEN writes the copybook only; the source rewrite returns only
source; build_sql_spec no longer takes copybook_dirs."
```

---

### Task 2: Self-contained call sites

The builtin's arguments and the lowering change together (one commit): neither works with the other's old shape.

**Files:**
- Modify: `squall/squall/builtins/exec_sql.py`
- Modify: `squall/squall/strategy.py`
- Modify: `squall/squall/strategy_stores.py` (keep `register` only; delete `Absent`, `ABSENT`, `SharedSqlStores`, `append`, `merge_cursors`, `merge_field_meta` unless another module imports them — `rg` first)
- Modify: `squall/squall/coprocessor.py` (no shared stores)
- Modify: `squall/squall/data_division_exec_sql.py` (`derive_cursors` returns declaration texts)
- Modify: `fp.json` (reasons for the three squall exclusions)
- Modify tests: `squall/tests/unit/test_builtin.py`, `test_cursor.py`, `test_session_reset.py`, `test_connection.py`, `test_strategy.py`, `test_strategy_stores.py`, `test_data_division_exec_sql.py`, `test_varchar.py` (if it calls the builtin), `tests/integration/test_carddemo_db2_compile.py`

**Interfaces:**
- Consumes: Task 1's `SqlLoweringStrategy(connections, initial_connector=..., *, tolerant=...)`.
- Produces: `make_exec_sql_builtin(connections, initial_connector=..., *, tolerant=...) -> tuple[Callable, Callable, Callable, Callable]`; `__exec_sql(args)` with `args = [text, *rest]` per spec §5; `derive_cursors(data) -> Mapping[str, str]` (cursor name → DECLARE text).

- [ ] **Step 1: Builtin tests to the new argument shape**

In each builtin test file, the per-run helper stops keeping a plan list. `test_builtin.py`'s `_session` becomes:

```python
def _session(backend, vm):
    """A per-run session over ``{'SAMPLE': backend}``; ``issue(sql, *rest)``
    runs one EXEC SQL with its text and any further call-site arguments."""
    builtin, *_ = make_exec_sql_builtin({"SAMPLE": backend})

    def issue(sql_text: str, *rest: str):
        return builtin([_TypedValue(sql_text), *(_TypedValue(r) for r in rest)], vm)

    return issue
```

Apply the same rewrite to the helpers in `test_cursor.py`, `test_session_reset.py` (`_declare_cursor`), `test_connection.py` (`_session`). A test that issues `DECLARE C1 ...` and later `OPEN C1` now issues `OPEN C1` with the DECLARE text as its second argument (the DECLARE call, if kept, is a no-op returning SQLCODE 0):

```python
    issue(_DECLARE_C1)                     # no-op, SQLCODE 0
    issue("EXEC SQL OPEN C1 END-EXEC", _DECLARE_C1)
```

`test_cursor.py`'s WORKING-STORAGE test (`recovered_cursors`, ~line 188) drops `cursors=` and gives OPEN the recovered text: `issue(open_text, derive_cursors(bridge_data)["C-TR-TYPE-FORWARD"])`.

New tests in `test_builtin.py`:

```python
def test_a_repeated_statement_is_parsed_once():
    from squall.builtins import exec_sql

    exec_sql._parsed.cache_clear()
    vm, _ = _make_vm()
    issue = _session(_backend_with_account(), vm)
    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC"
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    issue(text)
    issue(text)
    info = exec_sql._parsed.cache_info()
    assert (info.misses, info.hits) == (2, 1)


def test_an_open_without_a_declaration_reports_an_unknown_cursor():
    vm, region = _make_vm()
    issue = _session(_backend_with_account(), vm)
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")
    issue("EXEC SQL OPEN NOSUCH END-EXEC")
    assert _sqlcode(region) == -1
```

(Use the file's existing backend helper and SQLCODE reader under their real names.)

In `test_varchar.py`, add a FETCH test (Review Focus 1): declare a cursor selecting a VARCHAR column, OPEN with the declaration, FETCH INTO the VARCHAR group with its shape triple, assert the TEXT/LEN children hold the value:

```python
    issue(open_text, declare_text)
    issue(fetch_text, "DCL-TR-DESCRIPTION", "DCL-TR-DESCRIPTION-LEN", "DCL-TR-DESCRIPTION-TEXT")
    assert _decoded_varchar(region) == "SH ADVANCE"
```

(Reuse the file's `_DCLTRTYP_BRIDGE_GROUP` layout and its decode helper.)

- [ ] **Step 2: Lowering tests**

`squall/tests/unit/test_strategy.py` — replace `test_lower_parses_once_into_pool`, `test_derived_field_meta_reaches_the_already_registered_builtin`, `test_derived_cursors_reach_the_already_registered_builtin`, `test_one_spec_keeps_every_programs_plans_reachable` and `test_preprocess_program_dict_derives_cursors` / `..._derives_varchar_field_meta` (they assert on deleted stores) with:

```python
def _call_args(ctx) -> list:
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    (call,) = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    return [consts[a] for a in call.args]


def test_a_statement_carries_its_text(strategy):
    text = "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT END-EXEC"
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=text), materialised=None)
    assert _call_args(ctx) == [text]


def test_an_open_carries_its_working_storage_declaration(strategy):
    strategy.preprocess_program_dict(_BRIDGE_WORKING_STORAGE_DECLARE)
    ctx = _FakeEmitContext()
    open_text = "EXEC SQL OPEN C-TR-TYPE-FORWARD END-EXEC"
    strategy.lower(ctx, ExecSqlStatement(text=open_text), materialised=None)
    declaration = _BRIDGE_WORKING_STORAGE_DECLARE["data_division_exec_sql"][0]["exec_sql_text"]
    assert _call_args(ctx) == [open_text, declaration]


def test_a_procedure_declare_emits_nothing_and_reaches_its_open(strategy):
    declare = "EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T END-EXEC"
    strategy.preprocess_program_dict({})
    declare_ctx, open_ctx = _FakeEmitContext(), _FakeEmitContext()
    strategy.lower(declare_ctx, ExecSqlStatement(text=declare), materialised=None)
    strategy.lower(open_ctx, ExecSqlStatement(text="EXEC SQL OPEN C1 END-EXEC"), materialised=None)
    assert (declare_ctx.emitted, _call_args(open_ctx)) == (
        [],
        ["EXEC SQL OPEN C1 END-EXEC", declare],
    )


def test_a_varchar_host_variable_carries_its_shape(strategy):
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    text = "EXEC SQL SELECT D INTO :DCL-TR-DESCRIPTION FROM T END-EXEC"
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=text), materialised=None)
    assert _call_args(ctx) == [
        text,
        "DCL-TR-DESCRIPTION",
        "DCL-TR-DESCRIPTION-LEN",
        "DCL-TR-DESCRIPTION-TEXT",
    ]


def test_an_open_using_carries_the_shapes_of_its_own_host_variables(strategy):
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    declare = "EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T WHERE Y = :WS-Y END-EXEC"
    open_text = "EXEC SQL OPEN C1 USING :DCL-TR-DESCRIPTION END-EXEC"
    strategy.lower(_FakeEmitContext(), ExecSqlStatement(text=declare), materialised=None)
    ctx = _FakeEmitContext()
    strategy.lower(ctx, ExecSqlStatement(text=open_text), materialised=None)
    assert _call_args(ctx) == [
        open_text,
        declare,
        "DCL-TR-DESCRIPTION",
        "DCL-TR-DESCRIPTION-LEN",
        "DCL-TR-DESCRIPTION-TEXT",
    ]


def test_programs_lowered_by_one_strategy_keep_their_own_shapes(strategy):
    text = "EXEC SQL SELECT D INTO :DCL-TR-DESCRIPTION FROM T END-EXEC"
    strategy.preprocess_program_dict(_BRIDGE_VARCHAR_GROUP)
    first = _FakeEmitContext()
    strategy.lower(first, ExecSqlStatement(text=text), materialised=None)
    strategy.preprocess_program_dict({})
    second = _FakeEmitContext()
    strategy.lower(second, ExecSqlStatement(text=text), materialised=None)
    assert (len(_call_args(first)), _call_args(second)) == (4, [text])
```

If the grammar does not accept `OPEN ... USING`, drop that test and note it in the ledger (Review Focus 2 is then unreachable input).

`squall/tests/unit/test_data_division_exec_sql.py`: `derive_cursors` returns texts — the first test's last assertion becomes `assert cursors["C-TR-TYPE-FORWARD"] == data["data_division_exec_sql"][0]["exec_sql_text"]`; the others are unchanged (`set(cursors)`, `== {}`).

`tests/integration/test_carddemo_db2_compile.py::test_cotrtlic_working_storage_cursors_reach_the_sql_strategy`: instead of `_cursors_store`, assert on the linked IR that both OPENs carry their WORKING-STORAGE declaration:

```python
    _frontend, linked = _compile(bridge_jar, "COTRTLIC")
    texts = {
        i.value for i in linked.merged_ir if isinstance(i, Const) and isinstance(i.value, str)
    }
    declared = {
        name
        for name in ("C-TR-TYPE-FORWARD", "C-TR-TYPE-BACKWARD")
        if any(f"DECLARE {name} CURSOR" in t for t in texts)
    }
    assert declared == {"C-TR-TYPE-FORWARD", "C-TR-TYPE-BACKWARD"}
```

`squall/tests/unit/test_strategy_stores.py`: delete tests of deleted functions; keep `register` tests.

- [ ] **Step 3: Run and see them fail**

Run: `cd squall && uv run --no-sync python -m pytest tests/unit -q 2>&1 | tail -3`
Expected: FAIL — `TypeError` on `make_exec_sql_builtin` arity, `IndexError`/`ValueError` from `int(args[0].value)` on text, call-argument assertions.

- [ ] **Step 4: The builtin**

`squall/squall/builtins/exec_sql.py`:

```python
@cache
def _parsed(text: str) -> ParsedSql:
    return parse_exec_sql(text)


@dataclass(frozen=True)
class _Undeclared:
    """An OPEN whose cursor has no declaration in its program."""


@dataclass(frozen=True)
class _Call:
    """One __exec_sql call: the statement, an OPEN's declaration, the VARCHAR shapes."""

    parsed: ParsedSql
    declaration: ParsedSql | _Undeclared
    field_meta: Mapping[str, FieldMeta]


def _shapes(values: Sequence[str]) -> Mapping[str, FieldMeta]:
    return {
        values[i]: FieldMeta(category="VARCHAR", len_var=values[i + 1], text_var=values[i + 2])
        for i in range(0, len(values), 3)
    }


def _call(values: Sequence[str]) -> _Call:
    parsed = _parsed(values[0])
    match parsed.kind, values[1:]:
        case Kind.OPEN, ():
            return _Call(parsed, _Undeclared(), {})
        case Kind.OPEN, (declaration, *rest):
            return _Call(parsed, _parsed(declaration), _shapes(rest))
        case _, rest:
            return _Call(parsed, _Undeclared(), _shapes(rest))
```

(`from functools import cache`; `from squall.parser.parse import parse_exec_sql`.)

`_Ctx` loses `cursors` and `field_meta`. Every handler takes `(ctx, call, vm)` and reads `call.parsed` where it read `parsed`, and `call.field_meta` where it read `ctx.field_meta`. `_h_declare_cursor` is deleted and `Kind.DECLARE_CURSOR` joins `_NO_OP_KINDS`. `_open_on` matches `call.declaration`:

```python
def _open_on(backend: SqlBackend, ctx: _Ctx, call: _Call, vm) -> None:
    match call.declaration:
        case _Undeclared():
            write_sqlcode(vm, -1)
        case declaration:
            _open_declared_cursor(backend, ctx, call, declaration, vm)
```

`_close_all_cursors` iterates `tuple(ctx.open_cursors)` (the DECLARE registry is gone; only open cursors need closing). `make_exec_sql_builtin(connections, initial_connector=_NO_CONNECTOR, *, tolerant=False)` drops `plans`, `field_meta` and `cursors`; `__exec_sql` is:

```python
    def __exec_sql(args: Sequence[TypedValue], vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        call = _call([str(a.value) for a in args])
        _HANDLERS.get(call.parsed.kind, _h_query)(ctx, call, vm)
        return BuiltinResult(value=None)
```

Rewrite the module docstring's Design bullets: the arguments are the statement's text (parsed here, memoised per process), an OPEN's declaration, and VARCHAR shapes; no plan pool.

- [ ] **Step 5: The lowering**

`squall/squall/data_division_exec_sql.py`: `derive_cursors(data) -> Mapping[str, str]` — name → `entry["exec_sql_text"]` for every entry whose parse is a named `DECLARE CURSOR` (same filter as now).

`squall/squall/strategy.py`: the constructor builds the builtin with `make_exec_sql_builtin(connections, initial_connector=initial_connector, tolerant=tolerant)` and registers it; it holds no stores and drops the `stores` parameter. Per-program lowering state, reset by `preprocess_program_dict`:

```python
        self._declarations: dict[str, str] = {}
        self._varchar: dict[str, FieldMeta] = {}
```

```python
    def preprocess_program_dict(self, data: dict) -> dict:  # type: ignore[type-arg]
        """Start a program: its WORKING-STORAGE cursor declarations and its
        inferred VARCHAR groups, both for this program only."""
        self._declarations.clear()
        self._declarations.update(derive_cursors(data))
        self._varchar.clear()
        self._varchar.update(
            {name.upper(): meta for name, meta in derive_field_meta(data).items()}
        )
        return data
```

`lower`: WHENEVER handling unchanged; then

```python
        plan = parse_exec_sql(exec_sql_stmt.text)
        match plan.kind, plan.cursor:
            case Kind.DECLARE_CURSOR, NamedCursor(name):
                self._declarations[name] = exec_sql_stmt.text
                return
            case Kind.OPEN, NamedCursor(name) if name in self._declarations:
                declaration = self._declarations[name]
                bound = plan.in_vars or parse_exec_sql(declaration).in_vars
                self._emit_exec_sql_call(ctx, (exec_sql_stmt.text, declaration, *self._shapes(bound)))
            case _:
                self._emit_exec_sql_call(
                    ctx, (exec_sql_stmt.text, *self._shapes((*plan.in_vars, *plan.out_vars)))
                )
        self._emit_whenever_checks(ctx, materialised)
```

with

```python
    def _shapes(self, host_vars) -> tuple[str, ...]:
        return tuple(
            part
            for hv in host_vars
            if hv.name.upper() in self._varchar
            for part in (hv.name, *varchar_children(self._varchar[hv.name.upper()]))
        )

    def _emit_exec_sql_call(self, ctx: EmitContext, values: tuple[str, ...]) -> None:
        """Emit one ``Const`` per call-site value, then ``__exec_sql`` over them."""
        from interpreter.func_name import FuncName
        from interpreter.instructions import CallFunction, Const
        from interpreter.types.type_expr import UNKNOWN

        regs = tuple(ctx.fresh_reg() for _ in values)
        for reg, value in zip(regs, values, strict=True):
            ctx.emit_inst(Const(result_reg=reg, value=value, type_expr=UNKNOWN))
        ctx.emit_inst(
            CallFunction(result_reg=ctx.fresh_reg(), func_name=FuncName(_BUILTIN_NAME), args=regs)
        )
```

`varchar_children` is `squall.binding._varchar_children` made public (rename it, update its two callers in `binding.py`). Note the `for` loop over `zip` emits instructions — the same imperative emission the file already does through `ctx.emit_inst`; strategy.py is fp-lint-excluded and its reason is updated in Step 7. Delete the now-unused imports (`SharedSqlStores`, `merge_*`, `_append_plan`, `MappingProxyType`, `ParsedSql`, `Absent`, `ABSENT`). Rewrite the module docstring's Slice-1 bullets to describe the call-site arguments.

`squall/squall/coprocessor.py`: `_make_strategy` returns `SqlLoweringStrategy(connections, initial_connector=initial_connector, tolerant=tolerant)`; delete `stores` and the docstring paragraph about `SharedSqlStores` (replace with: every call site carries its own statement, so the one registered builtin serves every program).

`squall/squall/strategy_stores.py`: keep `register`; delete the rest if `rg -n "strategy_stores import" squall red_dragon_forge tests` shows no other importer.

- [ ] **Step 6: Run the tests**

Run: `. ./bridge-env.sh && cd squall && uv run --no-sync python -m pytest -q 2>&1 | tail -2; cd .. && uv run --no-sync python -m pytest tests/integration/test_sql_adapter.py tests/integration/test_cics_sql_composition.py tests/integration/test_jackal_sql_step.py -q 2>&1 | tail -2`
Expected: all succeed.

- [ ] **Step 7: fp.json reasons**

- `squall/squall/strategy_stores.py`: "Builtin registration into the VM's process-global Builtins.TABLE, the one write the SQL strategy makes to state it does not own." (or remove the file's entry if it is deleted)
- `squall/squall/strategy.py`: rewrite the reason: (1) subscript and clear/update mutation of the strategy's own per-program lowering state (`_whenever`, `_declarations`, `_varchar`), reset at each program's `preprocess_program_dict`; (2)–(4) unchanged (`data: dict` and `stmt: object` protocol signatures); (5) the `for` loop emitting one `Const` per call-site value through `ctx.emit_inst`, an imperative emission API.
- `squall/squall/builtins/exec_sql.py`: drop violation (4) (`ctx.cursors[...]`, gone) and renumber; the count changes from seven to six.

Run: `pre-commit run python-fp-lint-check --hook-stage manual --all-files 2>&1 | tail -3` — Expected: no new violations in non-excluded files.

- [ ] **Step 8: Mutation checks**

(1) In `_shapes` (strategy), return `()` → `test_a_varchar_host_variable_carries_its_shape` and the `test_crud_e2e` VARCHAR test fail. (2) In `lower`, drop the declaration from the OPEN call → `test_an_open_carries_its_working_storage_declaration` and the cursor tests fail. (3) Replace `@cache` with nothing → `test_a_repeated_statement_is_parsed_once` fails (no `cache_info`). Restore after each.

- [ ] **Step 9: Commit**

```bash
git add -A squall tests/integration/test_carddemo_db2_compile.py fp.json
git commit -m "refactor(squall): every EXEC SQL call site carries its own statement

__exec_sql receives the statement's text (parsed at run time, memoised by
text), an OPEN's cursor declaration, and the VARCHAR shapes of the host
variables it binds. The plan pool, the cursor and field-metadata stores and
SharedSqlStores are gone: a program's IR alone runs it."
```

---

### Task 3: Cross-process proof, docs, gate

**Files:**
- Create: `squall/tests/integration/test_cross_process_run.py`, `squall/tests/integration/cross_process_runner.py`
- Modify: `squall/tests/integration/squall_cobol_helpers.py` (extract `run_linked_program`)
- Modify: `docs/reference/squall/architecture.md` (lines 26-29 and the `strategy.py`, `strategy_stores.py`, `data_division_exec_sql.py` rows)

- [ ] **Step 1: The cross-process test**

First extract the run half of `run_cobol` in `squall/tests/integration/squall_cobol_helpers.py` so a parent and a child can share it:

```python
def run_linked_program(linked, max_steps: int = 1000):
    """Run a compiled program from its entry label; return the final VMState."""
    from interpreter.func_name import FuncName
    from interpreter.vm.vm import StackFrame
    from interpreter import constants as _constants

    initial_vm = VMState()
    initial_vm.data_layout = linked.data_layout
    initial_vm.call_stack.append(
        StackFrame(function_name=FuncName(_constants.MAIN_FRAME_NAME))
    )
    return run_linked(
        linked,
        entry_point=EntryPoint.function(lambda ref: ref.label == linked.entry_func_label),
        max_steps=max_steps,
        initial_vm=initial_vm,
    )
```

and make `run_cobol` end with `return run_linked_program(linked, max_steps)` (its comments move with the code).

Create `squall/tests/integration/cross_process_runner.py`:

```python
"""Run a pickled SQL program in this process, with only a fresh strategy registered."""

import pickle
import sqlite3
import sys
from pathlib import Path

from squall.backends.sqlite import SqliteBackend
from squall.strategy import SqlLoweringStrategy
from squall_cobol_helpers import read_ws_field, run_linked_program

conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE EMP (EMP_ID INTEGER NOT NULL, EMP_NAME VARCHAR(9))")
SqlLoweringStrategy({"SAMPLE": SqliteBackend(conn)})
linked = pickle.loads(Path(sys.argv[1]).read_bytes())
vm = run_linked_program(linked, max_steps=4000)
print(read_ws_field(vm, "EMP-NAME-LEN"), read_ws_field(vm, "EMP-NAME-TEXT").rstrip())
```

(Use the import path `test_crud_e2e.py` uses for `SqliteBackend`.)

Create `squall/tests/integration/test_cross_process_run.py`:

```python
"""A SQL program lowered in one process runs in another with no lowering state."""

import pickle
import sqlite3
import subprocess
import sys
from pathlib import Path

from squall.dclgen import generate, write
from squall_cobol_helpers import compile_cobol
from test_crud_e2e import _VARCHAR_PROGRAM


def test_a_program_lowered_here_runs_in_a_fresh_process(bridge_jar, tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE EMP (EMP_ID INTEGER NOT NULL, EMP_NAME VARCHAR(9))")
    write(generate(conn, "EMP", record_name="EMPREC"), tmp_path)
    _frontend, linked = compile_cobol(
        _VARCHAR_PROGRAM, bridge_jar, {"SAMPLE": None}, copybook_dirs=[tmp_path]
    )
    unit = tmp_path / "unit.pickle"
    unit.write_bytes(pickle.dumps(linked))

    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("cross_process_runner.py")), str(unit)],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parent,
    )

    assert result.stdout.strip() == "7 SANDERS"
```

Match the import style the other squall integration tests use for `squall_cobol_helpers` and `test_crud_e2e` (package-relative if `tests/integration/__init__.py` makes them a package; then the runner is run with `-m` and `cwd` at `squall/`). `{"SAMPLE": None}` works because nothing connects at compile time; if the strategy constructor rejects it, give it an in-memory `SqliteBackend`.

- [ ] **Step 2: Run it**

Run: `. ./bridge-env.sh && cd squall && uv run --no-sync python -m pytest tests/integration/test_cross_process_run.py -q`
Expected: succeeds. Mutation: delete the runner's `SqlLoweringStrategy(...)` line → FAIL (`__exec_sql` unregistered), so the builtin registration is the only thing the child needs besides the IR.

- [ ] **Step 3: Docs**

`docs/reference/squall/architecture.md`:
- lines 26-29: "The lowering strategy turns each EXEC SQL statement into a `__exec_sql` call carrying the statement's text, an OPEN's cursor declaration and the VARCHAR shapes of the host variables it binds. The builtin parses the text once per process and runs it on the current connection. A lowered program needs nothing from the lowering to run."
- `strategy.py` row: "...lowers `ExecSqlStatement` to self-contained `__exec_sql` calls, registers the builtins."
- `strategy_stores.py` row: "Builtin registration into `Builtins.TABLE`." (or delete the row if the file is deleted)
- `data_division_exec_sql.py` row: "Recovers WORKING-STORAGE `DECLARE CURSOR` texts from the bridge JSON."

- [ ] **Step 4: Gate**

Run: `make fmt && uv run pyright 2>&1 | tail -1 && uv run lint-imports | tail -1 && pre-commit run python-fp-lint-check --hook-stage manual --all-files | tail -1`, then `docker inspect -f '{{.State.Health.Status}}' squall-db2` (restart if unhealthy) and `. ./bridge-env.sh && make test-all > /tmp/squall-ir.log 2>&1; grep -E "^=+ .* in [0-9.]+s" /tmp/squall-ir.log`
Expected: pyright error count unchanged from before Task 1 (32, all cobble); every suite succeeds, including squall's Db2 e2e tests and the root CardDemo DB2 composition tests.

- [ ] **Step 5: Commit, push, beads**

```bash
git add squall/tests/integration/test_cross_process_run.py squall/tests/integration/cross_process_runner.py squall/tests/integration/squall_cobol_helpers.py docs/reference/squall/architecture.md
git commit -m "test(squall): a lowered SQL program runs in a fresh process"
git push origin main
```

File a forge bead for the parse/lower/link split's next step if none exists, referencing red-dragon-ajps; `bd export -o issues/issues.jsonl`, commit, push.
