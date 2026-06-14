# Squall EXEC SQL — Slice 1 Implementation Plan (SELECT … INTO)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run a real COBOL program containing `EXEC SQL SELECT … INTO :host-vars FROM tbl WHERE col = :host-var END-EXEC` end-to-end through RedDragon + Squall against a seeded SQLite table, binding host variables and setting `SQLCODE`.

**Architecture:** The RedDragon seam already exists (`ExecSqlStatement` opaque node, `extension_strategies` array, bridge `serializeExecSql` — RedDragon `main` `ab598905`). Squall adds: a Lark **parser** that strips the `EXEC SQL`/`END-EXEC` envelope and extracts host-vars (NO regex — grammar terminals); a dialect/DB-agnostic **binding engine** (field ↔ param via `data_layout`, `SQLCODE`); a **`SqlBackend`** protocol + **`SqliteBackend`**; a **`__exec_sql` builtin**; and a **`SqlLoweringStrategy`** implementing `RedDragonExtensionLoweringStrategy`. The strategy lowers each `EXEC SQL` to `Const` args + `CallFunction(__exec_sql, …)`; the builtin reads input host-var fields, runs the query via the backend, writes the `INTO` fields and `SQLCODE`.

**Tech stack:** Python 3 (uv), Lark (parser), stdlib `sqlite3` (backend), pytest. Depends on RedDragon (`interpreter.*`) via `vendor/red-dragon` submodule. Integration test needs the ProLeap JAR (reuse the existing `~/code/red-dragon` build via `PROLEAP_BRIDGE_JAR`).

**Repo:** `~/code/squall` (currently docs-only). Work on a branch; the design lives in `docs/design/2026-06-13-exec-sql-support-design.md`.

**Key invariants** (CLAUDE.md): no `squall → cicada` import; no edits to RedDragon `vm/**`/`ir.py`/`run.py`; binding engine is dialect/backend-agnostic; **no regex/string-surgery for SQL** — parsing is the Lark grammar; tests follow the `bridge_jar` fixture pattern (single `os.environ["PROLEAP_BRIDGE_JAR"]`, no skip/default).

---

## File structure

```
squall/
  __init__.py
  parser.py            # Lark grammar + parse_exec_sql(text) -> ParsedSql
  backend.py           # SqlBackend protocol + SqlResult dataclass
  backends/
    __init__.py
    sqlite.py          # SqliteBackend
  binding.py           # host-var field <-> param marshaling + SQLCODE (uses vm.data_layout)
  builtins/
    __init__.py
    exec_sql.py        # make_exec_sql_builtin(backend) -> __exec_sql
  strategy.py          # SqlLoweringStrategy (RedDragonExtensionLoweringStrategy)
tests/
  unit/   conftest.py + test_parser.py, test_sqlite_backend.py, test_binding.py,
          test_exec_sql_builtin.py, test_strategy.py
  integration/  conftest.py (bridge_jar) + test_select_into_e2e.py
pyproject.toml
vendor/red-dragon  (submodule @ ab598905)
```

**Test commands:** unit `uv run python -m pytest tests/unit -q` (no JAR); integration `PROLEAP_BRIDGE_JAR=$HOME/code/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar uv run python -m pytest tests/integration -q`.

---

## Task 0: Scaffold the repo

**Files:** `pyproject.toml`, `squall/__init__.py`, `vendor/red-dragon` (submodule), `tests/unit/__init__.py`, `tests/integration/__init__.py`.

- [ ] **Step 1: Add the RedDragon submodule pinned at the seam commit.**
```bash
cd ~/code/squall
git submodule add git@github.com:avishek-sen-gupta/red-dragon.git vendor/red-dragon
git -C vendor/red-dragon checkout ab598905
git add .gitmodules vendor/red-dragon
```
- [ ] **Step 2: Write `pyproject.toml`** (uv; editable RedDragon path dep; lark; pytest):
```toml
[project]
name = "squall"
version = "0.1.0"
description = "EXEC SQL coprocessor runtime for RedDragon COBOL"
requires-python = ">=3.11"
dependencies = ["lark>=1.1"]

[tool.uv]
dev-dependencies = ["pytest>=8", "black>=24"]

[tool.uv.sources]
red-dragon = { path = "vendor/red-dragon", editable = true }

[project.optional-dependencies]
reddragon = ["red-dragon"]

[tool.pytest.ini_options]
pythonpath = ["."]
```
> Note: confirm RedDragon's distribution name (`grep -m1 '^name' vendor/red-dragon/pyproject.toml`). If it isn't `red-dragon`, match it here and in the `[tool.uv.sources]` key. If RedDragon has no installable package metadata, fall back to `pythonpath = [".", "vendor/red-dragon"]` in `[tool.pytest.ini_options]` and drop the source dep.
- [ ] **Step 3:** create `squall/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` (empty); run `uv sync`; verify `uv run python -c "import interpreter.cobol.cobol_statements as m; print(m.ExecSqlStatement)"` prints the class (proves RedDragon import works).
- [ ] **Step 4: Commit** `chore: scaffold squall package + vendor/red-dragon submodule`.

---

## Task 1: `SqlBackend` protocol + `SqlResult`

**Files:** create `squall/backend.py`; test `tests/unit/test_sqlite_backend.py` (shared).

- [ ] **Step 1: Write the failing test** (in `tests/unit/test_sqlite_backend.py`):
```python
from squall.backend import SqlResult, SqlBackend


def test_sqlresult_fields():
    r = SqlResult(rows=[(42,)], rowcount=1, sqlcode=0)
    assert r.rows == [(42,)] and r.rowcount == 1 and r.sqlcode == 0


def test_protocol_is_runtime_checkable():
    class _Fake:
        def execute(self, sql, params): return SqlResult([], 0, 0)
    assert isinstance(_Fake(), SqlBackend)
```
- [ ] **Step 2:** run `uv run python -m pytest tests/unit/test_sqlite_backend.py -q` → FAIL (ImportError).
- [ ] **Step 3: Implement `squall/backend.py`:**
```python
"""SqlBackend protocol — the pluggable DB boundary. The binding engine hands a
parametrized query + params here; the backend owns dialect, placeholder style,
transactions. Dialect/DB knowledge lives ONLY behind this seam."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SqlResult:
    rows: list[tuple]   # result rows (SELECT); empty for DML
    rowcount: int       # affected rows (DML); len(rows) for SELECT
    sqlcode: int        # 0 ok, +100 not found, negative on error


@runtime_checkable
class SqlBackend(Protocol):
    def execute(self, sql: str, params: list[Any]) -> SqlResult: ...
```
- [ ] **Step 4:** run the test → PASS. **Step 5: Commit** `feat(squall): SqlBackend protocol + SqlResult`.

---

## Task 2: `SqliteBackend`

**Files:** create `squall/backends/__init__.py`, `squall/backends/sqlite.py`; test `tests/unit/test_sqlite_backend.py` (append).

- [ ] **Step 1: Append the failing tests:**
```python
import sqlite3
from squall.backends.sqlite import SqliteBackend


def _seeded_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)")
    conn.execute("INSERT INTO ACCOUNT VALUES (11, 500)")
    conn.commit()
    return conn


def test_select_returns_row_and_sqlcode_0():
    be = SqliteBackend(_seeded_conn())
    r = be.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", [11])
    assert r.rows == [(500,)] and r.sqlcode == 0 and r.rowcount == 1


def test_select_no_row_is_sqlcode_100():
    be = SqliteBackend(_seeded_conn())
    r = be.execute("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", [999])
    assert r.rows == [] and r.sqlcode == 100


def test_error_is_negative_sqlcode():
    be = SqliteBackend(_seeded_conn())
    r = be.execute("SELECT nope FROM nope", [])
    assert r.sqlcode < 0
```
- [ ] **Step 2:** run → FAIL. **Step 3: Implement `squall/backends/sqlite.py`:**
```python
"""SqliteBackend — first concrete SqlBackend. Owns the ? placeholder + SQLite
dialect; maps outcomes to SQLCODE (0 / +100 not-found / negative error)."""
from __future__ import annotations
import sqlite3
from typing import Any
from squall.backend import SqlResult


class SqliteBackend:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: list[Any]) -> SqlResult:
        try:
            cur = self._conn.execute(sql, params)
        except sqlite3.Error:
            return SqlResult(rows=[], rowcount=0, sqlcode=-1)
        if cur.description is not None:  # a SELECT (cursor yields rows)
            rows = cur.fetchall()
            return SqlResult(rows=rows, rowcount=len(rows), sqlcode=0 if rows else 100)
        self._conn.commit()
        return SqlResult(rows=[], rowcount=cur.rowcount, sqlcode=0)
```
- [ ] **Step 4:** run → PASS. **Step 5: Commit** `feat(squall): SqliteBackend`.

---

## Task 3: Lark parser — envelope strip + host-var extraction

**Files:** create `squall/parser.py`; test `tests/unit/test_parser.py`. NO regex; the `EXEC SQL`/`END-EXEC` envelope and the `INTO` clause are grammar constructs.

`parse_exec_sql(text)` returns a frozen `ParsedSql(out_vars, in_vars, query)` where:
- `out_vars`: the `INTO :a, :b` host-var names (uppercased, no leading `:`), in order — the SELECT result targets.
- `in_vars`: host-var names appearing in the executable query (e.g. the WHERE clause), in left-to-right order — the bind params.
- `query`: the executable SQL with the `INTO` clause removed and every `:host-var` replaced by the backend placeholder `?`. (Slice 1 hardwires `?` for SQLite; later the backend can supply its placeholder style.)

- [ ] **Step 1: Write the failing test:**
```python
from squall.parser import parse_exec_sql, ParsedSql


def test_select_into_extracts_vars_and_query():
    p = parse_exec_sql(
        "EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC"
    )
    assert p.out_vars == ["WS-BAL"]
    assert p.in_vars == ["WS-ID"]
    assert p.query == "SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?"


def test_multi_into_targets():
    p = parse_exec_sql(
        "EXEC SQL SELECT A, B INTO :V1, :V2 FROM T WHERE K = :K END-EXEC"
    )
    assert p.out_vars == ["V1", "V2"]
    assert p.in_vars == ["K"]
    assert p.query == "SELECT A, B FROM T WHERE K = ?"


def test_case_insensitive_envelope_and_keywords():
    p = parse_exec_sql("exec sql select a into :x from t end-exec")
    assert p.out_vars == ["X"] and p.in_vars == [] and p.query == "select a from t"
```
- [ ] **Step 2:** run → FAIL. **Step 3: Implement `squall/parser.py`** with a Lark grammar. Starting point (iterate under TDD until the tests pass):
```python
"""EXEC SQL parser (slice 1: SELECT … INTO). A Lark grammar strips the
EXEC SQL / END-EXEC envelope and the embedded INTO clause as grammar constructs —
no regex/string surgery. Host vars (:NAME) are grammar tokens; the executable
query is reconstructed with them replaced by ? placeholders."""
from __future__ import annotations
from dataclasses import dataclass
from lark import Lark, Token

_GRAMMAR = r"""
start: "EXEC"i "SQL"i select "END-EXEC"i
select: SELECT_KW select_list INTO_KW into_list rest
SELECT_KW: "SELECT"i
INTO_KW: "INTO"i
select_list: /[^:]+?(?=\bINTO\b)/i   // text up to INTO (no host vars in slice-1 select list)
into_list: host_var ("," host_var)*
host_var: ":" CNAME
rest: item*
item: host_var | WORD | PUNCT
WORD: /[A-Za-z0-9_.]+/
PUNCT: /[(),=<>*\/+\-]/
CNAME: /[A-Za-z][A-Za-z0-9_-]*/
%import common.WS
%ignore WS
"""
# NOTE: the select_list lookahead is the one fragile spot; if Lark rejects it,
# model select_list as `item*` too and split on the INTO_KW token instead — keep
# all of this INSIDE the grammar/tree walk, never a regex over the raw input.

@dataclass(frozen=True)
class ParsedSql:
    out_vars: list[str]
    in_vars: list[str]
    query: str

_parser = Lark(_GRAMMAR, start="start", parser="earley", lexer="dynamic")

def parse_exec_sql(text: str) -> ParsedSql:
    tree = _parser.parse(text)
    # Walk the tree: collect into_list host vars (out_vars); rebuild the executable
    # query from select_list + "FROM…" rest, replacing host_var nodes with "?" and
    # recording their names in order (in_vars). Return ParsedSql(...).
    ...  # implement the tree walk to satisfy the tests
```
> The grammar/walk WILL need iteration — that's expected; the three tests are the contract. Keep envelope/keyword handling in the grammar (the `"…"i` terminals), never a regex over the input. If Earley + dynamic lexer is awkward, a hand-written **tokenizer** (a `lark` `Lark(... lexer="standard")` token stream you iterate) is acceptable — but NOT `re.sub` surgery on the raw text.
- [ ] **Step 4:** run → PASS (all 3). **Step 5: Commit** `feat(squall): EXEC SQL parser (SELECT INTO, host-var extraction)`.

---

## Task 4: Binding engine (field ↔ param, SQLCODE)

**Files:** create `squall/binding.py`; test `tests/unit/test_binding.py`. Uses `vm.data_layout` + the WS region (mirror cicada's `cics/builtins/screen.py` `_read_ws_field`/`_write_ws_field`/`_ws_region`).

`squall/binding.py` exposes:
- `read_params(vm, in_names) -> list` — for each input host-var field name, read its bytes from the WS region and decode to a Python value (slice 1: numeric DISPLAY → int; alphanumeric → str). Mirror cics field decode via `vm.data_layout.get(name)` (offset/length/category).
- `write_outputs(vm, out_names, row) -> None` — for each `(name, value)` in `zip(out_names, row)`, encode + write into the WS field (mirror `_write_ws_field`).
- `write_sqlcode(vm, code) -> None` — write `code` into the `SQLCODE` field (the program's `01 SQLCODE PIC S9(9) …`, present via the data layout).

- [ ] **Step 1: Write the failing test** — build a minimal `VMState` with a WS region + `data_layout` for `WS-ID`, `WS-BAL`, `SQLCODE` (follow the construction in cicada `tests/unit/cics/test_screen_builtins.py`, which seeds `vm.data_layout` + a region; read that file in vendor or replicate its helper). Assert `read_params(vm, ["WS-ID"]) == [11]`; after `write_outputs(vm, ["WS-BAL"], (500,))` the `WS-BAL` field decodes to 500; after `write_sqlcode(vm, 100)` the `SQLCODE` field reads 100.
- [ ] **Step 2:** run → FAIL. **Step 3: Implement** `squall/binding.py`, reusing the cics field-access pattern (locate the WS region via the `__ws_region` local var → `vm.region_get`; `vm.data_layout.get(name)` → offset/length/category; decode/encode per category). Keep it dialect/DB-agnostic — it only touches COBOL fields and the SQL `INTO`/param positions, never SQL text.
- [ ] **Step 4:** run → PASS. **Step 5: Commit** `feat(squall): host-variable binding engine`.

> If exact WS-region/field-encode reuse from RedDragon is unclear, READ `vendor/red-dragon/.../cics?` — NO; cics lives in cicada, which squall must not import. Instead replicate the small read/write-field helpers locally in `binding.py` using `vm.data_layout` + `vm.region_get`/`region_set` (RedDragon VM API). Confirm the field dict keys (`offset`/`length`/`category`) against `vendor/red-dragon/interpreter/cobol/data_layout.py`.

---

## Task 5: `__exec_sql` builtin

**Files:** create `squall/builtins/__init__.py`, `squall/builtins/exec_sql.py`; test `tests/unit/test_exec_sql_builtin.py`.

`make_exec_sql_builtin(backend)` returns `__exec_sql(args, vm) -> BuiltinResult` where `args` carry (as `Const` values from lowering): `args[0]` = the executable query string; `args[1]` = the input host-var name list; `args[2]` = the `INTO` host-var name list. Behavior: `params = read_params(vm, args[1])`; `result = backend.execute(args[0], params)`; if rows, `write_outputs(vm, args[2], result.rows[0])`; `write_sqlcode(vm, result.sqlcode)`; return `BuiltinResult(value=None)`.

- [ ] **Step 1: Write the failing test** with a fake backend (returns a fixed `SqlResult`) + the minimal VM from Task 4; assert the `INTO` field gets the value and `SQLCODE` is set. **Step 2:** FAIL. **Step 3:** implement (`BuiltinResult`/`VMState`/`TypedValue` from `interpreter.vm.vm_types`; read `args[i].value`). **Step 4:** PASS. **Step 5: Commit** `feat(squall): __exec_sql builtin`.

---

## Task 6: `SqlLoweringStrategy`

**Files:** create `squall/strategy.py`; test `tests/unit/test_strategy.py`. Implements `RedDragonExtensionLoweringStrategy` (from `interpreter.cobol.red_dragon_extension_strategy`).

- `__init__(self, backend)`: store; register the builtin — `from interpreter.vm.builtins import Builtins; Builtins.TABLE.register("__exec_sql", make_exec_sql_builtin(backend))` (mirror cicada `cics/strategy.py`'s `_register(Builtins.TABLE, "__cics_…", …)` — confirm the exact register call).
- `handles(self, stmt)`: `isinstance(stmt, ExecSqlStatement)`.
- `preprocess_program_dict(self, data)`: return `data` (no-op, slice 1).
- `on_procedure_entry(self, ctx, materialised)`: no-op.
- `lower(self, ctx, stmt, materialised)`: `p = parse_exec_sql(stmt.text)`; emit `Const` regs for `p.query`, `p.in_vars`, `p.out_vars`; emit `CallFunction(result_reg=ctx.fresh_reg(), func_name=FuncName("__exec_sql"), args=(r_query, r_in, r_out))` (mirror the `ctx.emit_inst(CallFunction(...))` / `ctx.const_to_reg(...)` pattern in cicada `cics/strategy.py`).

- [ ] **Step 1: Write the failing test:** a fake `ctx` capturing `emit_inst`/`const_to_reg`/`fresh_reg` (or a real `EmitContext`); call `lower(ctx, ExecSqlStatement(text="EXEC SQL SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID END-EXEC"), None)`; assert a `CallFunction` to `__exec_sql` is emitted with Const args `("SELECT ACCT_BAL FROM ACCOUNT WHERE ACCT_ID = ?", ["WS-ID"], ["WS-BAL"])`. Also assert `handles()` true for `ExecSqlStatement`, false for a non-SQL stmt. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5: Commit** `feat(squall): SqlLoweringStrategy on the extension seam`.

---

## Task 7: Integration — real COBOL SELECT INTO end-to-end

**Files:** `tests/integration/conftest.py` (the `bridge_jar` fixture, single `os.environ["PROLEAP_BRIDGE_JAR"]` — copy the established pattern, no skip/default); `tests/integration/test_select_into_e2e.py`.

- [ ] **Step 1: Write the failing test.** Build the JAR-backed parser (`ProLeapCobolParser(RealSubprocessRunner(), bridge_jar)`); a seeded in-memory SQLite (`ACCOUNT(ACCT_ID, ACCT_BAL)` with `(11, 500)`); `frontend = CobolFrontend(parser, extension_strategies=[SqlLoweringStrategy(SqliteBackend(conn))])`. COBOL program:
```
IDENTIFICATION DIVISION.
PROGRAM-ID. SQLSEL.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-ID   PIC 9(4) VALUE 11.
01 WS-BAL  PIC 9(9) VALUE 0.
01 SQLCODE PIC S9(9) VALUE 0.
PROCEDURE DIVISION.
    EXEC SQL
        SELECT ACCT_BAL INTO :WS-BAL FROM ACCOUNT WHERE ACCT_ID = :WS-ID
    END-EXEC.
    STOP RUN.
```
Lower → run (via `interpreter.run.run_linked`/`run` with the Builtins registry); assert the `WS-BAL` field decodes to `500` and `SQLCODE` is `0`. (Mirror cicada `tests/integration/cics/*` for the run+region-read pattern; thread `bridge_jar`.)
- [ ] **Step 2:** FAIL (initially the binding/lowering not wired). **Step 3:** make it pass — this is the slice's integration glue; fix whatever the real run surfaces (entry-point resolution, the WS-region local-var name, the SQLCODE field presence). Do NOT add fallbacks; if `SQLCODE` isn't auto-declared, declare it in the program (as above).
- [ ] **Step 4:** PASS. **Step 5: Commit** `test(squall): SELECT INTO end-to-end on SQLite`.

---

## Task 8: Branch wrap-up

- [ ] Full unit suite green (`uv run python -m pytest tests/unit -q`); integration green with `PROLEAP_BRIDGE_JAR` exported.
- [ ] `uv run python -m black .`
- [ ] Commit/push the branch; open for review. Note follow-ups for slice 2+ (DML, cursors, COMMIT/ROLLBACK, INCLUDE) per the design doc.

---

## Self-review

**Spec coverage** (design §8 slice-1 row): bridge `serializeExecSql` ✓ (already in RedDragon); lowering ✓ (Task 6); binding ✓ (Task 4); execute ✓ (Tasks 2/5); bind-back + SQLCODE ✓ (Tasks 4/5); end-to-end ✓ (Task 7). Generic-layer-in-isolation: parser/binding/backend each unit-tested against fakes (Tasks 1–6) before the JAR integration (Task 7) ✓.

**No-regex check:** the only parsing is the Lark grammar (Task 3); envelope/keywords are grammar terminals. The plan explicitly forbids `re.sub` surgery and flags the one fragile grammar spot with a grammar-level fallback.

**Risk / iterate spots:** (1) the Lark grammar (Task 3) — TDD against the 3 concrete parse tests; (2) the WS-region/field encode-decode reuse (Task 4) — replicate RedDragon's `data_layout` access locally, do NOT import cicada; (3) `Builtins.TABLE` register call + `SQLCODE` auto-declaration (Tasks 5–7) — confirm against `vendor/red-dragon` and cicada's pattern during execution.

**Out of scope (slice 2+):** INSERT/UPDATE/DELETE, cursors, COMMIT/ROLLBACK, `EXEC SQL INCLUDE`, SQLCA, multi-row, dialect translation beyond SQLite.
