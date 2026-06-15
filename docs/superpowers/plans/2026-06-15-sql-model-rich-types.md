# Richer SQL Model Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ParsedSql`'s `X | None` Optionals and bare-`str` closed sets with precise types — proper `enum.Enum`s and frozen-dataclass sum types with explicit null objects — eliminating `None` from the SQL model, with **zero behaviour change**. (squall-pzg; spec: `docs/superpowers/specs/2026-06-15-sql-model-rich-types-design.md`.)

**Architecture:** A new pure-data module `squall/parser/sql_model.py` holds `HostVar`, the new enums/sum types, `FieldMeta`, and `ParsedSql`. `parse.py` becomes the builder. Behaviour (`emit`, `resolve`) stays in consumers (`strategy`, `binding`/`exec_sql`) via `match`. The refactor is done field-by-field; the existing **267** tests (run with `PROLEAP_BRIDGE_JAR` + `SQUALL_DB2_DSN` + `SQUALL_DB2_DSN2`) plus per-type unit tests keep every task boundary green.

**Tech Stack:** Python 3.13, `enum`, `dataclasses`, `typing.TypedDict`; Lark parser; pytest; `python_fp_lint` + `pyright` (warnings-only) + `black`.

**Environment for the full suite:**
```bash
export PROLEAP_BRIDGE_JAR=~/code/squall/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
export SQUALL_DB2_DSN="DATABASE=MOJO;HOSTNAME=localhost;PORT=50000;PROTOCOL=TCPIP;UID=db2inst1;PWD=db2rocks;"
export SQUALL_DB2_DSN2="DATABASE=MOJO2;HOSTNAME=localhost;PORT=50000;PROTOCOL=TCPIP;UID=db2inst1;PWD=db2rocks;"
```
(If DB2 is down: `docker exec db2server su - db2inst1 -c "db2start"`.)

---

## File Structure

- **Create** `squall/parser/sql_model.py` — `HostVar`, `Kind`, `WheneverCondition`, the sum-type dataclasses + aliases, `FieldMeta`, `ParsedSql`. Pure data; imports only stdlib.
- **Modify** `squall/parser/parse.py` — imports the model; builder helpers return typed objects; `kind = Kind(stmt.data)`.
- **Modify** `squall/builtins/exec_sql.py` — `_HANDLERS: dict[Kind, …]`; cursor/connect handlers `match`; collection types.
- **Modify** `squall/strategy.py` — whenever state `dict[WheneverCondition, WheneverAction]`; relation table keyed by enum; `match action`.
- **Modify** `squall/preprocess.py` — `include` reader; `field_meta: Mapping[str, FieldMeta]`.
- **Modify** `squall/binding.py` — `field_meta`/`_meta_for` typed as `FieldMeta`.
- **Modify** tests: `test_parse.py`, `test_whenever.py`, `test_connection.py`, `test_strategy.py` (assertions move to the new types); **create** `tests/unit/test_sql_model.py`.

---

## Task 1: Create `sql_model.py`; move `HostVar`/`ParsedSql`; add the new types

**Files:**
- Create: `squall/parser/sql_model.py`
- Modify: `squall/parser/parse.py` (top of file)
- Test: `tests/unit/test_sql_model.py`

This task is **purely additive/relocating**: `ParsedSql` keeps its current (old) field types; the new types are added but unused. The suite stays green.

- [ ] **Step 1: Create `squall/parser/sql_model.py`** with this exact content:

```python
"""
squall.parser.sql_model
~~~~~~~~~~~~~~~~~~~~~~~~~
Pure-data types for the parsed EXEC SQL model. No interpreter / binding imports:
behaviour (lowering, host-var resolution) lives in the consumers (strategy,
binding/exec_sql), which ``match`` on these sums.

Design tenets: no ``None`` in the model — every "absent" case is an explicit
null object; dataless closed sets are proper ``enum.Enum`` (NOT ``StrEnum`` — no
implicit ``==`` with ``str``); sums that carry data are frozen-dataclass unions.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TypedDict


# ── Host variables ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class HostVar:
    name: str  # e.g. "WS-BAL" (no leading colon)
    indicator: str | None  # e.g. "WS-IND" for :WS-BAL:WS-IND, else None


# ── Statement kind (one member per grammar `?stmt` alternative) ───────────────
class Kind(enum.Enum):
    SELECT_INTO = "select_into"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    DECLARE_CURSOR = "declare_cursor"
    DECLARE_TABLE = "declare_table"
    DECLARE_STATEMENT = "declare_statement"
    DECLARE_VARIABLE = "declare_variable"
    FETCH = "fetch"
    OPEN = "open_"
    CLOSE = "close"
    COMMIT = "commit"
    ROLLBACK = "rollback"
    SAVEPOINT = "savepoint"
    RELEASE = "release"
    CONNECT = "connect"
    SET_CONNECTION = "set_connection"
    DISCONNECT = "disconnect"
    INCLUDE = "include"
    WHENEVER = "whenever"
    ALLOCATE_CURSOR = "allocate_cursor"
    MERGE = "merge"
    VALUES_INTO = "values_into"
    PREPARE = "prepare"
    EXECUTE = "execute_"
    DESCRIBE = "describe"
    GET_DIAGNOSTICS = "get_diagnostics"
    SIGNAL = "signal"
    BEGIN_DECLARE = "begin_declare"
    END_DECLARE = "end_declare"
    FREE_LOCATOR = "free_locator"
    HOLD_LOCATOR = "hold_locator"
    ASSOCIATE = "associate"
    CALL = "call"
    SET = "set"
    LOCK = "lock"
    GENERIC = "generic"


# ── Cursor reference ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class NamedCursor:
    name: str


@dataclass(frozen=True)
class NoCursor:
    pass


CursorRef = NamedCursor | NoCursor


# ── INCLUDE target ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class IncludeName:
    name: str


@dataclass(frozen=True)
class NoInclude:
    pass


IncludeRef = IncludeName | NoInclude


# ── Connection target ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LiteralDb:
    name: str  # upper-cased literal database name


@dataclass(frozen=True)
class HostVarDb:
    var: HostVar  # resolved at run time by the consumer


DbName = LiteralDb | HostVarDb


@dataclass(frozen=True)
class ConnectTo:
    # The named connection target for CONNECT TO / SET CONNECTION / DISCONNECT
    # <name>. The Kind distinguishes the operation; this carries the target db.
    db: DbName


@dataclass(frozen=True)
class ConnectReset:
    pass


@dataclass(frozen=True)
class NoConnect:
    pass


ConnectSpec = ConnectTo | ConnectReset | NoConnect


# ── WHENEVER condition (dataless closed set → enum) ───────────────────────────
class WheneverCondition(enum.Enum):
    SQLERROR = "SQLERROR"
    NOT_FOUND = "NOT FOUND"
    SQLWARNING = "SQLWARNING"
    NONE = "none"  # null object: the statement carries no WHENEVER condition


# ── WHENEVER action (GoTo carries data → dataclass union) ─────────────────────
@dataclass(frozen=True)
class GoTo:
    target: str


@dataclass(frozen=True)
class Continue:
    pass


@dataclass(frozen=True)
class NoOpAction:
    pass


WheneverAction = GoTo | Continue | NoOpAction


# ── dclgen sidecar descriptor (host var -> FieldMeta) ─────────────────────────
class FieldMeta(TypedDict, total=False):
    category: str  # ZONED_DECIMAL | ALPHANUMERIC | COMP3 | BINARY | VARCHAR
    offset: int
    length: int
    total_digits: int
    decimal_digits: int
    signed: bool
    len_var: str  # VARCHAR group only
    text_var: str  # VARCHAR group only


# ── The parsed statement ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class ParsedSql:
    kind: str  # the grammar kind, e.g. "select_into"  (→ Kind in Task 2)
    in_vars: tuple[HostVar, ...]  # input (bind) host vars, in source order
    out_vars: tuple[HostVar, ...]  # output (INTO) host vars, in order
    cursor: str | None  # cursor name for cursor statements  (→ CursorRef, Task 3)
    query: str  # cleaned SQL for the DB
    include_name: str | None = None  # INCLUDE target  (→ include: IncludeRef, Task 4)
    # Connection management  (→ connect: ConnectSpec, Task 5)
    connect_variant: str | None = None
    connect_db: str | HostVar | None = None
    # WHENEVER directive  (→ WheneverCondition / WheneverAction, Task 6)
    whenever_condition: str | None = None
    whenever_action: str | None = None
    whenever_target: str | None = None
```

- [ ] **Step 2: Re-point `parse.py` to import `HostVar`/`ParsedSql` from the model.** In `squall/parser/parse.py`, delete the local `HostVar` and `ParsedSql` class definitions and the now-unused `dataclass` import if appropriate, and add near the top (after `from lark import Lark, Token, Tree`):

```python
from squall.parser.sql_model import HostVar, ParsedSql
```

Keep everything else in `parse.py` unchanged. (`from squall.parser.parse import HostVar, ParsedSql` still works via this re-export, so no consumer/test imports break.)

- [ ] **Step 3: Write `tests/unit/test_sql_model.py`** (sanity that the new types construct and compare by value / identity):

```python
"""
tests/unit/test_sql_model.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The pure-data SQL model types: frozen-dataclass value equality, enum identity,
and that enums are NOT implicitly comparable to strings (proper Enum, not StrEnum).
"""

from __future__ import annotations

from squall.parser.sql_model import (
    ConnectReset,
    ConnectTo,
    Continue,
    GoTo,
    HostVar,
    HostVarDb,
    IncludeName,
    Kind,
    LiteralDb,
    NamedCursor,
    NoConnect,
    NoCursor,
    NoInclude,
    NoOpAction,
    WheneverCondition,
)


def test_kind_constructs_from_grammar_string_but_is_not_a_string():
    assert Kind("select_into") is Kind.SELECT_INTO
    assert Kind.SELECT_INTO != "select_into"  # proper Enum, no implicit str equality


def test_whenever_condition_constructs_and_is_not_a_string():
    assert WheneverCondition("NOT FOUND") is WheneverCondition.NOT_FOUND
    assert WheneverCondition.SQLERROR != "SQLERROR"


def test_dataclass_sums_compare_by_value():
    assert NamedCursor("C1") == NamedCursor("C1")
    assert NamedCursor("C1") != NoCursor()
    assert GoTo("ERR") == GoTo("ERR")
    assert GoTo("ERR") != Continue()
    assert ConnectTo(LiteralDb("SAMPLE")) == ConnectTo(LiteralDb("SAMPLE"))
    assert ConnectTo(HostVarDb(HostVar("DB", None))) != ConnectReset()


def test_null_objects_are_distinct_singletons_by_type():
    assert NoCursor() == NoCursor()
    assert NoInclude() == NoInclude()
    assert NoConnect() == NoConnect()
    assert NoOpAction() == NoOpAction()
```

- [ ] **Step 4: Run** — `uv run python -m pytest tests/unit/test_sql_model.py tests/unit/test_parse.py -q`. Expected: PASS (new tests green; parse tests unaffected by the move).

- [ ] **Step 5: Full unit suite** — `uv run python -m pytest tests/unit/ -q` (with env). Expected: 250 + 5 sql_model = 255 (no DB2 needed for unit). PASS.

- [ ] **Step 6: Commit**

```bash
git add squall/parser/sql_model.py squall/parser/parse.py tests/unit/test_sql_model.py
git commit -m "refactor(sql): add sql_model module (enums + sum types); move HostVar/ParsedSql"
```

---

## Task 2: `kind: str` → `kind: Kind`

**Files:** Modify `squall/parser/sql_model.py`, `parse.py`, `builtins/exec_sql.py`, `strategy.py`, `preprocess.py`; tests `test_parse.py`, `test_whenever.py`, `test_connection.py`, `test_strategy.py`.

- [ ] **Step 1: Update the failing tests first** (they assert `kind == "<str>"`, which is now `False`). Replace, by exact mapping:
  - `tests/unit/test_parse.py`: `p.kind == "select_into"`→`p.kind is Kind.SELECT_INTO`; `"fetch"`→`Kind.FETCH`; `"insert"`→`Kind.INSERT`; `"declare_cursor"`→`Kind.DECLARE_CURSOR`; `"open_"`→`Kind.OPEN`; `"close"`→`Kind.CLOSE`; `"delete"`→`Kind.DELETE`; `"commit"`→`Kind.COMMIT`. Add `from squall.parser.sql_model import Kind`. (Line 136 `p.kind = "something_else"` tests frozen immutability — leave the assignment; it still raises `FrozenInstanceError` regardless of value.)
  - `tests/unit/test_whenever.py`: `p.kind == "whenever"`→`p.kind is Kind.WHENEVER` (2 sites). Add the import.
  - `tests/unit/test_connection.py`: `p.kind == "connect"`→`is Kind.CONNECT`; `"set_connection"`→`Kind.SET_CONNECTION`; `"disconnect"`→`Kind.DISCONNECT`. Add the import.
  - `tests/unit/test_strategy.py:135`: `plan.kind == "select_into"`→`plan.kind is Kind.SELECT_INTO`. Add the import.

- [ ] **Step 2: Run a touched test to confirm it fails** — `uv run python -m pytest tests/unit/test_parse.py -q`. Expected: FAIL (kind is still a `str`, so `is Kind.X` is False).

- [ ] **Step 3: Change `ParsedSql.kind` type** in `sql_model.py`:

```python
    kind: Kind  # the statement kind
```

- [ ] **Step 4: Build a `Kind` in `parse.py`.** In `parse_exec_sql`, change `kind: str = stmt.data` to:

```python
    kind: Kind = Kind(stmt.data)
```
Add `Kind` (and the other model types used later) to the `from squall.parser.sql_model import …` line. Then convert the kind-set constants and comparisons in `parse.py`:

```python
_CURSOR_KINDS: Final[frozenset[Kind]] = frozenset(
    {Kind.DECLARE_CURSOR, Kind.OPEN, Kind.CLOSE, Kind.FETCH}
)
_NO_QUERY_KINDS: Final[frozenset[Kind]] = frozenset({Kind.FETCH, Kind.OPEN, Kind.CLOSE})
_HAS_INTO_CLAUSE: Final[frozenset[Kind]] = frozenset({Kind.SELECT_INTO, Kind.VALUES_INTO})
```
and update the helper signatures/comparisons (`kind: str` → `kind: Kind`):
  - `_include_name`: `if kind != "include":` → `if kind is not Kind.INCLUDE:`
  - `_connection_fields`: `if kind == "connect":` → `is Kind.CONNECT`; `if kind in ("set_connection", "disconnect"):` → `if kind in (Kind.SET_CONNECTION, Kind.DISCONNECT):`
  - `_whenever_fields`: `if kind != "whenever":` → `is not Kind.WHENEVER`
  - `_cursor_name`: `if kind not in _CURSOR_KINDS:` (unchanged form; set is now `frozenset[Kind]`)
  - `_build_query`: `if kind in _NO_QUERY_KINDS:` (unchanged); `if kind == "declare_cursor"` → `is Kind.DECLARE_CURSOR`; `if kind in _HAS_INTO_CLAUSE:` (unchanged)

- [ ] **Step 5: Update `exec_sql.py`** dispatch:

```python
from squall.parser.sql_model import Kind   # add to imports

_NO_OP_KINDS = frozenset({Kind.BEGIN_DECLARE, Kind.END_DECLARE})

_HANDLERS = {
    Kind.CONNECT: _h_connect,
    Kind.SET_CONNECTION: _h_set_connection,
    Kind.DISCONNECT: _h_disconnect,
    Kind.DECLARE_CURSOR: _h_declare_cursor,
    Kind.OPEN: _h_open,
    Kind.FETCH: _h_fetch,
    Kind.CLOSE: _h_close,
    Kind.COMMIT: _h_commit,
    Kind.ROLLBACK: _h_rollback,
    **{kind: _h_noop for kind in _NO_OP_KINDS},
}
```
In `_h_query`, change `if parsed.kind == "select_into"` to `if parsed.kind is Kind.SELECT_INTO`. The dispatch `_HANDLERS.get(parsed.kind, _h_query)` is unchanged (now keyed by `Kind`).

- [ ] **Step 6: Update `strategy.py`** — `if plan.kind == "whenever":` → `if plan.kind is Kind.WHENEVER:` and add `from squall.parser.sql_model import Kind` to the local imports already present in `lower` (the block that imports `parse_exec_sql`).

- [ ] **Step 7: Update `preprocess.py`** — `if parsed.kind == "include" and parsed.include_name is not None:` → `if parsed.kind is Kind.INCLUDE and parsed.include_name is not None:` and `from squall.parser.sql_model import Kind`.

- [ ] **Step 8: Run** — `uv run python -m pytest tests/unit/ -q` (255 green), then the full suite with env: `uv run python -m pytest tests/ -q` (267 green).

- [ ] **Step 9: Commit**

```bash
git add squall/parser/sql_model.py squall/parser/parse.py squall/builtins/exec_sql.py squall/strategy.py squall/preprocess.py tests/unit/
git commit -m "refactor(sql): kind is a proper Kind enum, not str"
```

---

## Task 3: `cursor: str | None` → `cursor: CursorRef`

**Files:** Modify `sql_model.py`, `parse.py`, `exec_sql.py`; tests `test_parse.py`.

- [ ] **Step 1: Update tests.** In `tests/unit/test_parse.py`: `p.cursor == "ACC-CURSOR"` → `p.cursor == NamedCursor("ACC-CURSOR")`; `p.cursor == "MyCursor"` → `NamedCursor("MyCursor")`; `p.cursor is None` → `p.cursor == NoCursor()`. Add `from squall.parser.sql_model import NamedCursor, NoCursor`.

- [ ] **Step 2: Run** — `uv run python -m pytest tests/unit/test_parse.py -q`. Expected: FAIL (cursor is still `str | None`).

- [ ] **Step 3: Change the field** in `sql_model.py`: `cursor: CursorRef`.

- [ ] **Step 4: Rename `_cursor_name` → `_cursor_ref` in `parse.py`** and return the sum:

```python
def _cursor_ref(stmt: Tree, kind: Kind) -> CursorRef:
    """The cursor as NamedCursor(name), else NoCursor() for non-cursor statements."""
    if kind not in _CURSOR_KINDS:
        return NoCursor()
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "NAME":
            return NamedCursor(str(child))
    return NoCursor()
```
Update the call site in `parse_exec_sql`: `cursor = _cursor_ref(stmt, kind)`. Add `CursorRef, NamedCursor, NoCursor` to the model import.

- [ ] **Step 5: Update the cursor handlers in `exec_sql.py`** to extract the name via `match`. Add a tiny helper and use it:

```python
from squall.parser.sql_model import NamedCursor   # add to imports

def _cursor_name(ref) -> str:
    """The cursor name; cursor handlers only ever run for NamedCursor refs."""
    match ref:
        case NamedCursor(name):
            return name
        case _:
            raise AssertionError(f"cursor handler reached with {ref!r}")
```
Then replace the four `parsed.cursor` uses:
  - `_h_declare_cursor`: `ctx.cursors[parsed.cursor] = parsed` → `ctx.cursors[_cursor_name(parsed.cursor)] = parsed`
  - `_h_open`: `decl = ctx.cursors.get(parsed.cursor)` → `decl = ctx.cursors.get(_cursor_name(parsed.cursor))`; `backend.open_cursor(parsed.cursor, …)` → `backend.open_cursor(_cursor_name(parsed.cursor), …)`
  - `_h_fetch`: `backend.fetch(parsed.cursor)` → `backend.fetch(_cursor_name(parsed.cursor))`
  - `_h_close`: `backend.close(parsed.cursor)` → `backend.close(_cursor_name(parsed.cursor))`

- [ ] **Step 6: Run** — `uv run python -m pytest tests/ -q` (267 green).

- [ ] **Step 7: Commit**

```bash
git add squall/parser/sql_model.py squall/parser/parse.py squall/builtins/exec_sql.py tests/unit/test_parse.py
git commit -m "refactor(sql): cursor is CursorRef (NamedCursor | NoCursor), not str | None"
```

---

## Task 4: `include_name: str | None` → `include: IncludeRef`

**Files:** Modify `sql_model.py`, `parse.py`, `preprocess.py`. (No test reads `include_name` directly; `test_preprocess.py` exercises the prepass end-to-end.)

- [ ] **Step 1: Change the field** in `sql_model.py`: replace `include_name: str | None = None` with `include: IncludeRef = NoInclude()`. (Keep it after `query`; it has a default so field order is fine. Import nothing — `NoInclude` is defined above in the same module, but a default value referencing it must come after its definition; `ParsedSql` is last in the file, so `NoInclude()` is in scope.)

- [ ] **Step 2: Rename `_include_name` → `_include_ref` in `parse.py`:**

```python
def _include_ref(stmt: Tree, kind: Kind) -> IncludeRef:
    """The INCLUDE target as IncludeName(name), else NoInclude()."""
    if kind is not Kind.INCLUDE:
        return NoInclude()
    for child in stmt.children:
        if isinstance(child, Token) and child.type == "NAME":
            return IncludeName(str(child))
    return NoInclude()
```
Update `parse_exec_sql`: `inc = _include_ref(stmt, kind)` and pass `include=inc` (rename the kwarg from `include_name=inc_name`). Add `IncludeRef, IncludeName, NoInclude` to the model import.

- [ ] **Step 3: Update `preprocess.py`** `_includes` (line ~151):

```python
from squall.parser.sql_model import IncludeName, Kind   # add to imports

# inside _includes:
        if parsed.kind is Kind.INCLUDE and isinstance(parsed.include, IncludeName):
            yield start, end, indent, parsed.include.name
```
(Everything downstream already works on the yielded `include_name` string.)

- [ ] **Step 4: Run** — `uv run python -m pytest tests/ -q` (267 green; `test_preprocess.py` + the DCLGEN include e2e cover this).

- [ ] **Step 5: Commit**

```bash
git add squall/parser/sql_model.py squall/parser/parse.py squall/preprocess.py
git commit -m "refactor(sql): include is IncludeRef (IncludeName | NoInclude), not include_name str | None"
```

---

## Task 5: `connect_variant` + `connect_db` → `connect: ConnectSpec`

**Files:** Modify `sql_model.py`, `parse.py`, `exec_sql.py`; tests `test_connection.py`.

`ConnectTo(db)` carries the target for `CONNECT TO`, `SET CONNECTION`, and `DISCONNECT <name>` alike (Kind distinguishes the op); `ConnectReset` is `CONNECT RESET`; `NoConnect` is every non-connection kind.

- [ ] **Step 1: Update tests** in `tests/unit/test_connection.py`:
  - `test_parse_connect_to_literal`: `p.connect_variant == "TO"` + `p.connect_db == "SAMPLE"` → `assert p.connect == ConnectTo(LiteralDb("SAMPLE"))`.
  - `test_parse_connect_to_hostvar`: `p.connect_variant == "TO"` + `p.connect_db == HostVar(name="dbname", indicator=None)` → `assert p.connect == ConnectTo(HostVarDb(HostVar("dbname", None)))`.
  - `test_parse_connect_to_literal_with_creds_ignores_creds`: → `assert p.connect == ConnectTo(LiteralDb("SAMPLE"))`.
  - `test_parse_connect_reset`: `p.connect_variant == "RESET"` + `p.connect_db is None` → `assert p.connect == ConnectReset()`.
  - `test_parse_set_connection`: `p.connect_db == "DB2"` → `assert p.connect == ConnectTo(LiteralDb("DB2"))`.
  - `test_parse_disconnect`: `p.connect_db == "DB2"` → `assert p.connect == ConnectTo(LiteralDb("DB2"))`.
  - Add `from squall.parser.sql_model import ConnectReset, ConnectTo, HostVarDb, LiteralDb` (HostVar already imported).

- [ ] **Step 2: Run** — `uv run python -m pytest tests/unit/test_connection.py -q`. Expected: FAIL.

- [ ] **Step 3: Change the fields** in `sql_model.py`: remove `connect_variant` and `connect_db`; add `connect: ConnectSpec = NoConnect()`.

- [ ] **Step 4: Replace `parse.py`'s connect extraction.** Remove `_conn_target` + `_connection_fields`; add:

```python
def _connect_spec(stmt: Tree, kind: Kind) -> ConnectSpec:
    """The connection target. CONNECT RESET -> ConnectReset; CONNECT TO / SET
    CONNECTION / DISCONNECT <name> -> ConnectTo(db); else NoConnect."""
    if kind is Kind.CONNECT:
        if any(isinstance(c, Token) and c.type == "RESET" for c in stmt.children):
            return ConnectReset()
        return ConnectTo(_connect_db(stmt))
    if kind in (Kind.SET_CONNECTION, Kind.DISCONNECT):
        name = next(
            (str(c) for c in stmt.children if isinstance(c, Token) and c.type == "NAME"),
            "",
        )
        return ConnectTo(LiteralDb(name.upper()))
    return NoConnect()


def _connect_db(stmt: Tree) -> DbName:
    """The CONNECT TO target db: a NAME literal (upper-cased) or a host var."""
    node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "conn_target"),
        None,
    )
    if node is not None:
        inner = node.children[0]
        if isinstance(inner, Token) and inner.type == "NAME":
            return LiteralDb(str(inner).upper())
        return HostVarDb(_parse_host_var_tok(inner.children[0].value))
    raise AssertionError("CONNECT TO without a conn_target")
```
In `parse_exec_sql`: replace the `conn_variant, conn_db = _connection_fields(...)` line with `connect = _connect_spec(stmt, kind)`, and replace the `connect_variant=…, connect_db=…` kwargs with `connect=connect`. Add `ConnectSpec, ConnectTo, ConnectReset, NoConnect, DbName, LiteralDb, HostVarDb` to the model import. (`set_connection`/`disconnect` targets are always literal NAMEs — host-var forms aren't in scope, matching today's behaviour.)

- [ ] **Step 5: Replace the connect handlers in `exec_sql.py`.** Remove `_resolve_db_name`; add a `match`-based resolver and rewrite the three handlers:

```python
from squall.parser.sql_model import ConnectReset, ConnectTo, HostVarDb, LiteralDb  # add

def _resolve_db(spec, ctx: _Ctx, vm) -> str:
    """The target database name from a ConnectTo spec (literal, or host-var value)."""
    match spec:
        case ConnectTo(LiteralDb(name)):
            return name
        case ConnectTo(HostVarDb(var)):
            return str(read_params(vm, (var.name,), ctx.field_meta)[0]).strip().upper()
        case _:
            raise AssertionError(f"_resolve_db reached with {spec!r}")


def _h_connect(ctx: _Ctx, parsed, vm) -> None:
    if isinstance(parsed.connect, ConnectReset):
        ctx.conn.current = None
        write_sqlcode(vm, 0)
        return
    backend = ctx.connections.get(_resolve_db(parsed.connect, ctx, vm))
    if backend is None:
        write_sqlcode(vm, SQLCODE_DB_NOT_FOUND)
        return
    ctx.conn.current = backend
    write_sqlcode(vm, 0)


def _h_set_connection(ctx: _Ctx, parsed, vm) -> None:
    backend = ctx.connections.get(_resolve_db(parsed.connect, ctx, vm))
    if backend is None:
        write_sqlcode(vm, SQLCODE_NOT_ESTABLISHED)
        return
    ctx.conn.current = backend
    write_sqlcode(vm, 0)
```
(`_h_disconnect` is unchanged — it ignores the target and sets `current = None`.)

- [ ] **Step 6: Run** — `uv run python -m pytest tests/ -q` (267 green; the DB2 CONNECT routing e2e covers the runtime paths).

- [ ] **Step 7: Commit**

```bash
git add squall/parser/sql_model.py squall/parser/parse.py squall/builtins/exec_sql.py tests/unit/test_connection.py
git commit -m "refactor(sql): connect is ConnectSpec (ConnectTo | ConnectReset | NoConnect)"
```

---

## Task 6: `whenever_*` → `WheneverCondition` + `WheneverAction`

**Files:** Modify `sql_model.py`, `parse.py`, `strategy.py`; tests `test_whenever.py`.

- [ ] **Step 1: Update tests** in `tests/unit/test_whenever.py`:
  - `test_parse_whenever_sqlerror_goto`: `whenever_condition == "SQLERROR"` → `is WheneverCondition.SQLERROR`; `whenever_action == "GOTO"` + `whenever_target == "ERR-EXIT"` → `p.whenever_action == GoTo("ERR-EXIT")`.
  - `test_parse_whenever_go_to_two_words`: → `p.whenever_action == GoTo("ERR-EXIT")`.
  - `test_parse_whenever_not_found_continue`: `whenever_condition == "NOT FOUND"` → `is WheneverCondition.NOT_FOUND`; `whenever_action == "CONTINUE"` + `whenever_target is None` → `p.whenever_action == Continue()`.
  - `test_parse_non_whenever_has_no_whenever_fields`: `whenever_condition is None` → `is WheneverCondition.NONE`; `whenever_action is None` → `== NoOpAction()`; drop the `whenever_target` assertion (field removed).
  - Add `from squall.parser.sql_model import Continue, GoTo, NoOpAction, WheneverCondition`.

- [ ] **Step 2: Run** — `uv run python -m pytest tests/unit/test_whenever.py -q`. Expected: FAIL.

- [ ] **Step 3: Change the fields** in `sql_model.py`: remove `whenever_target`; set `whenever_condition: WheneverCondition = WheneverCondition.NONE` and `whenever_action: WheneverAction = NoOpAction()`.

- [ ] **Step 4: Rewrite the whenever extractors in `parse.py`:**

```python
def _whenever_fields(stmt: Tree, kind: Kind) -> tuple[WheneverCondition, WheneverAction]:
    if kind is not Kind.WHENEVER:
        return WheneverCondition.NONE, NoOpAction()
    cond_node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "whenever_cond"),
        None,
    )
    action_node = next(
        (c for c in stmt.children if isinstance(c, Tree) and c.data == "whenever_action"),
        None,
    )
    condition = (
        _whenever_condition(cond_node) if cond_node is not None else WheneverCondition.NONE
    )
    action = _whenever_action(action_node) if action_node is not None else NoOpAction()
    return condition, action


def _whenever_condition(node: Tree) -> WheneverCondition:
    tokens = [str(c) for c in node.children if isinstance(c, Token)]
    return WheneverCondition(" ".join(tokens).upper())


def _whenever_action(node: Tree) -> WheneverAction:
    tokens = [c for c in node.children if isinstance(c, Token)]
    if tokens and str(tokens[0]).upper() == "CONTINUE":
        return Continue()
    return GoTo(str(tokens[-1]))  # GOTO <name> / GO TO <name>: target is the trailing NAME
```
In `parse_exec_sql`: `wh_cond, wh_action = _whenever_fields(stmt, kind)` and pass `whenever_condition=wh_cond, whenever_action=wh_action` (drop `whenever_target=`). Add `WheneverCondition, WheneverAction, GoTo, Continue, NoOpAction` to the model import.

- [ ] **Step 5: Rewrite the whenever lowering in `strategy.py`.** Replace `_WHENEVER_RELATION` and the state/loop:

```python
from squall.parser.sql_model import (  # local import block in lower(), plus module-level for the table
    Continue, GoTo, NoOpAction, WheneverCondition,
)

# module level, replacing the old string-keyed table:
_WHENEVER_RELATION: dict[WheneverCondition, tuple[str, str]] = {
    WheneverCondition.SQLERROR: ("<", "0"),
    WheneverCondition.NOT_FOUND: ("=", "100"),
}
```
`__init__`: `self._whenever: dict[WheneverCondition, WheneverAction] = {}`.
The whenever branch in `lower`:
```python
        if plan.kind is Kind.WHENEVER:
            self._whenever[plan.whenever_condition] = plan.whenever_action
            return
```
(Storing `Continue()`/`NoOpAction()` is how CONTINUE disables a branch — the emit loop no-ops on them; no `del`, no `None`.)
`_emit_whenever_checks`:
```python
        for condition, action in self._whenever.items():
            match action:
                case GoTo(target):
                    if condition in _WHENEVER_RELATION:
                        op, value = _WHENEVER_RELATION[condition]
                        if_stmt = parse_statement(
                            {
                                "type": "IF",
                                "condition": {
                                    "not": False,
                                    "relation": {
                                        "left": {"kind": "ref", "name": "SQLCODE"},
                                        "op": op,
                                        "right": {"kind": "lit", "value": value},
                                    },
                                },
                                "children": [{"type": "GOTO", "operands": [target]}],
                            }
                        )
                        ctx.lower_statement(if_stmt, materialised)
                case _:  # Continue, NoOpAction
                    pass
```
(`parse_statement` import stays inside `_emit_whenever_checks` as today.)

- [ ] **Step 6: Run** — `uv run python -m pytest tests/ -q` (267 green; the WHENEVER DB2 e2e covers the GoTo branch).

- [ ] **Step 7: Commit**

```bash
git add squall/parser/sql_model.py squall/parser/parse.py squall/strategy.py tests/unit/test_whenever.py
git commit -m "refactor(sql): whenever_* become WheneverCondition enum + WheneverAction sum (no whenever_target)"
```

---

## Task 7: Parameterize the loose collections

**Files:** Modify `sql_model.py` (already has `FieldMeta`), `preprocess.py`, `strategy.py`, `exec_sql.py`, `binding.py`.

- [ ] **Step 1: `_plans` / `cursors`.**
  - `squall/strategy.py`: `self._plans: list = []` → `self._plans: list[ParsedSql] = []` (add `ParsedSql` to the model import).
  - `squall/builtins/exec_sql.py`: `_Ctx.cursors: dict` → `cursors: dict[str, ParsedSql]` (import `ParsedSql`).

- [ ] **Step 2: `field_meta: Mapping[str, dict]` → `Mapping[str, FieldMeta]`** at every annotation site. Add `from squall.parser.sql_model import FieldMeta` to each module.
  - `squall/preprocess.py`: `PrepassResult.field_meta: Mapping[str, FieldMeta]`; `_load_field_meta(...) -> FieldMeta`-valued dict (its return annotation `-> dict` → `-> dict[str, FieldMeta]`).
  - `squall/strategy.py`: `__init__(..., field_meta: Mapping[str, FieldMeta])`.
  - `squall/builtins/exec_sql.py`: `_bind_row(..., field_meta: Mapping[str, FieldMeta])`, `_Ctx.field_meta: Mapping[str, FieldMeta]`, `make_exec_sql_builtin(..., field_meta: Mapping[str, FieldMeta])`.
  - `squall/binding.py`: `_meta_for(field_meta: Mapping[str, FieldMeta], name: str) -> FieldMeta`; `read_params(..., field_meta: Mapping[str, FieldMeta])`; the two `_read_one`/`write` helpers' `field_meta: Mapping[str, FieldMeta]`. (`FieldMeta` is a `TypedDict`, so `.get(...)` calls in `binding.py` keep working unchanged.)

- [ ] **Step 3: Run** — `uv run python -m pytest tests/ -q` (267 green — annotations only, no runtime change).

- [ ] **Step 4: Commit**

```bash
git add squall/parser/sql_model.py squall/preprocess.py squall/strategy.py squall/builtins/exec_sql.py squall/binding.py
git commit -m "refactor(sql): parameterize collections (_plans/cursors: ParsedSql; field_meta: FieldMeta)"
```

---

## Task 8: Full regression, lint, close bead

**Files:** none (verification).

- [ ] **Step 1: Format** — `uv run python -m black squall/ tests/`.

- [ ] **Step 2: Full suite** — with env set: `uv run python -m pytest tests/ -q`. Expected: **267 + 5 (sql_model) = 272** green.

- [ ] **Step 3: Lint** — `uv run python -m python_fp_lint check squall/parser/sql_model.py squall/parser/parse.py squall/strategy.py squall/builtins/exec_sql.py squall/binding.py squall/preprocess.py` (no violations). `uv run pyright squall/parser/sql_model.py squall/parser/parse.py squall/strategy.py squall/builtins/exec_sql.py` — confirm the parameterization **removed** the prior `tuple[str|None,…]` / unparameterized-collection noise and added no new non-import errors.

- [ ] **Step 4: Close the bead**

```bash
bd close squall-pzg --reason "ParsedSql is now fully typed: Kind/WheneverCondition proper enums (no implicit str ==), CursorRef/IncludeRef/ConnectSpec/DbName/WheneverAction frozen-dataclass sums with explicit null objects (no None in the model), collections parameterized (list[ParsedSql], dict[str, ParsedSql], Mapping[str, FieldMeta]). Pure-data model in squall/parser/sql_model.py; emit/resolve behaviour stays in strategy/binding via match. Zero behaviour change; 272 tests green."
```

---

## Notes for the implementer

- **Zero behaviour change is the invariant.** Each task keeps the 267 pre-existing tests green; the only test edits are assertion *types* (string → enum/sum), never expected outcomes. If a behavioural test changes meaning, stop — something is wrong.
- **Order matters only for `Kind` (Task 2 first after scaffolding).** Tasks 3–6 are independent per-field migrations and can be reordered, but each must leave the suite green before the next.
- **`set_connection`/`disconnect` host-var targets are out of scope** — they were literal-only before this refactor too; `_connect_spec` keeps that (literal NAME → `ConnectTo(LiteralDb(...))`).
- **Null objects are compared by value** (frozen dataclasses) — `NoCursor() == NoCursor()` is `True`; tests rely on this.
- **Do not** turn `FieldMeta.category` into an enum here (separate binding-layer change; the values come from external dclgen JSON and are string-compared throughout `binding.py`).
- **Do not** import the interpreter or `squall.binding` into `sql_model.py` — it must stay pure data.
