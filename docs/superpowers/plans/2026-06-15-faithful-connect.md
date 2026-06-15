# Faithful CONNECT — Connection Registry + Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace squall's no-op `CONNECT` / `SET CONNECTION` / `DISCONNECT` / `CONNECT RESET` with faithful, program-controlled connection semantics: a name→backend **registry**, a per-run **current connection**, and **always-disconnected** start (SQL before a successful CONNECT returns `-1024`). (squall-yml.)

**Architecture:** `CONNECT` is a *runtime* statement, so the connection state is a per-run **SQL session** held in the `__exec_sql` builtin's `_Ctx` closure, unified with the existing cursor registry: `{connections: dict[str, SqlBackend], current: SqlBackend | None, connected: bool, cursors, field_meta}`. `current` starts `None`. `CONNECT TO <name>` sets `current = connections[name]`; `SET CONNECTION` switches it; `CONNECT RESET`/`DISCONNECT` clears it. Every `execute`/cursor/commit handler routes through `current` and returns `-1024` when disconnected. The registry holds *live* (non-serializable) backends, so it stays process/closure state by necessity; nothing here goes in the VM byte-region.

**Tech Stack:** Python; squall (`squall/parser/parse.py`, `squall/builtins/exec_sql.py`, `squall/strategy.py`); RedDragon vendored interpreter; pytest; **two DB2 databases** via two DSNs (`SQUALL_DB2_DSN` + `SQUALL_DB2_DSN2`); ProLeap via `PROLEAP_BRIDGE_JAR`.

**Scope:** `CONNECT TO <literal|:hostvar> [USER..USING..]`, `CONNECT RESET`, `DISCONNECT [<name>|ALL|CURRENT]`, `SET CONNECTION <name>`; lifecycle codes `0` / `-1024` (no connection) / `-1013` (db not found) / `-1338` (connection not established). **Out of scope:** credential *validation* (backends are pre-authenticated — `USER`/`USING` are read but not checked); two-phase commit; the cicada pseudo-conversational reset hook (that is `cicada-6hv` + `squall-ipq`, separate).

**Decisions locked in brainstorm (do not relitigate):**
- **Always start disconnected.** Connections are explicit in fully-formed code; tests that run SQL without a CONNECT are *incomplete programs* and get a CONNECT added (Task 4).
- **Registry replaces the single `backend`** through strategy/builtin/helper.
- **Per-run closure session** (registry in closure is unavoidable — live backends don't serialize). The cicada cross-turn-leak concern is handled at the cicada boundary (`cicada-6hv`), not here.
- **Synthetic testbed uses two real DB2 databases** (no standalone testbed program does multi-db).

**Verified facts (before writing this plan):**
- Parse kinds & trees: `CONNECT TO sample` → kind `connect`, tree `connect → [CONNECT, TO, NAME("sample")]`; `CONNECT TO :db USER :u USING :p` → kind `connect`, `in_vars = [db, u, p]` (host vars, in order), tree has `TO` then a `HOST_VAR_TOK`; `CONNECT RESET` → `connect`, tree `[CONNECT, RESET]`; `SET CONNECTION db2` → kind `set_connection`; `DISCONNECT db2` → kind `disconnect`. So for the literal form the target is the NAME after `TO`; for the host-var form the target is `in_vars[0]` (and `in_vars[1:]` are the credentials).
- Today `connect`/`disconnect`/`set_connection` are in `_NO_OP_KINDS` → `_h_noop` (SQLCODE 0).
- The builtin already keeps per-run state in `_Ctx` (cursors); connection state joins it.

---

## File Structure

- **Modify** `squall/parser/parse.py` — surface `connect_variant` + `connect_db` on `ParsedSql`.
- **Modify** `squall/builtins/exec_sql.py` — `_Ctx` gains `connections`/`current`/`connected`; new connection handlers; `execute`/cursor handlers gate on `current`; drop `connect`/`disconnect`/`set_connection` from `_NO_OP_KINDS`.
- **Modify** `squall/strategy.py` — `__init__` takes `connections: dict[str, SqlBackend]`.
- **Modify** `tests/integration/squall_cobol_helpers.py` — `run_cobol`/`compile_cobol` take `connections`.
- **Modify** existing unit + integration tests — pass a registry; add explicit CONNECT; session-style unit harness (Task 4).
- **Create** `tests/unit/test_connection.py` — parse + lifecycle unit tests.
- **Create** `tests/integration/test_db2_connect_e2e.py` — two-DB2-database routing e2e.

---

## Task 1: `ParsedSql` carries the connection directive

**Files:** Modify `squall/parser/parse.py`; Test `tests/unit/test_connection.py`.

- [ ] **Step 1: Failing test** — create `tests/unit/test_connection.py`:

```python
"""
tests/unit/test_connection.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Faithful CONNECT: registry routing + per-run connection lifecycle (squall-yml).
"""
from __future__ import annotations

from squall.parser.parse import parse_exec_sql, HostVar


def test_parse_connect_to_literal():
    p = parse_exec_sql("EXEC SQL CONNECT TO sample END-EXEC")
    assert p.kind == "connect"
    assert p.connect_variant == "TO"
    assert p.connect_db == "SAMPLE"  # DB2 upper-cases database names


def test_parse_connect_to_hostvar():
    p = parse_exec_sql("EXEC SQL CONNECT TO :dbname USER :u USING :p END-EXEC")
    assert p.connect_variant == "TO"
    assert p.connect_db == HostVar(name="dbname", indicator=None)


def test_parse_connect_reset():
    p = parse_exec_sql("EXEC SQL CONNECT RESET END-EXEC")
    assert p.connect_variant == "RESET"
    assert p.connect_db is None


def test_parse_set_connection():
    p = parse_exec_sql("EXEC SQL SET CONNECTION db2 END-EXEC")
    assert p.kind == "set_connection"
    assert p.connect_db == "DB2"


def test_parse_disconnect():
    p = parse_exec_sql("EXEC SQL DISCONNECT db2 END-EXEC")
    assert p.kind == "disconnect"
    assert p.connect_db == "DB2"
```

- [ ] **Step 2: Run → fail** (`AttributeError: connect_variant`). `uv run python -m pytest tests/unit/test_connection.py -q`

- [ ] **Step 3: Add `ParsedSql` fields** (after the whenever fields, or after `include_name` if WHENEVER not yet merged):

```python
    # Connection management (kinds connect / set_connection / disconnect).
    connect_variant: str | None = None  # "TO" / "RESET" (connect only); None otherwise
    connect_db: "str | HostVar | None" = None  # target db: literal (upper-cased) or HostVar
```

- [ ] **Step 4: Extract in `parse_exec_sql`** — add a helper:

```python
def _connection_fields(
    stmt: Tree, kind: str
) -> tuple[str | None, "str | HostVar | None"]:
    """Return (variant, target) for connect/set_connection/disconnect, else Nones.

    - connect: variant is "RESET" or "TO". For TO, the target is the NAME after
      TO (literal, upper-cased) or the first input host var (e.g. CONNECT TO :db).
    - set_connection / disconnect: variant None; target is the NAME (upper-cased).
    """
    if kind not in ("connect", "set_connection", "disconnect"):
        return None, None
    toks = [c for c in stmt.children if isinstance(c, Token)]
    if kind == "connect":
        if any(t.type == "RESET" for t in toks):
            return "RESET", None
        # CONNECT TO <target>: NAME after TO, else the first host var.
        after_to = _token_after(toks, "TO")
        if after_to is not None and after_to.type == "NAME":
            return "TO", str(after_to).upper()
        first_hv = stmt and _collect_input_hv_tokens(stmt)
        target = (
            _parse_host_var_tok(first_hv[0].value) if first_hv else None
        )
        return "TO", target
    # set_connection / disconnect: first NAME token is the target.
    name = next((str(t) for t in toks if t.type == "NAME"), None)
    return None, (name.upper() if name else None)


def _token_after(tokens: list, kind: str):
    """Return the Token immediately following the first token of type *kind*."""
    for i, t in enumerate(tokens[:-1]):
        if t.type == kind:
            return tokens[i + 1]
    return None
```

Then in `parse_exec_sql`:

```python
    conn_variant, conn_db = _connection_fields(stmt, kind)
    return ParsedSql(
        ...,
        connect_variant=conn_variant,
        connect_db=conn_db,
    )
```

- [ ] **Step 5: Run → pass** (5 passed). **Step 6: Commit**

```bash
git add squall/parser/parse.py tests/unit/test_connection.py
git commit -m "feat(sql): surface CONNECT/SET CONNECTION/DISCONNECT target on ParsedSql"
```

---

## Task 2: Builtin — connection registry + per-run lifecycle

**Files:** Modify `squall/builtins/exec_sql.py`; Test `tests/unit/test_connection.py` (append).

- [ ] **Step 1: Failing test** — append (uses the strategy/helper from Task 3, so this step is written to drive both; if executing strictly task-by-task, write the assertion now and let it fail until Task 3 lands the registry plumbing):

```python
import os
import importlib.util
from pathlib import Path

_HELPERS = Path(__file__).parent.parent / "integration" / "squall_cobol_helpers.py"
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HELPERS)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
compile_cobol = _helpers.compile_cobol


def _sqlite(seed_ddl="CREATE TABLE T (ID INTEGER)"):
    import sqlite3
    from squall.backends.sqlite import SqliteBackend

    conn = sqlite3.connect(":memory:")
    conn.execute(seed_ddl)
    conn.commit()
    return SqliteBackend(conn)


_PROG_NO_CONNECT = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOCONN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-N PIC S9(9) COMP.
       PROCEDURE DIVISION.
           EXEC SQL INSERT INTO T VALUES (1) END-EXEC
           MOVE SQLCODE TO WS-N.
           STOP RUN.
"""


def test_sql_before_connect_is_minus_1024(bridge_jar=None):
    """SQL issued before any CONNECT returns SQLCODE -1024 (no connection)."""
    jar = os.environ["PROLEAP_BRIDGE_JAR"]
    backend = _sqlite()
    _f, linked = compile_cobol(_PROG_NO_CONNECT, jar, {"SAMPLE": backend}, copybook_dirs=[])
    vm = _helpers.run_linked_for_test(linked)  # see helper note in Task 3
    assert _helpers.read_ws_field(vm, "WS-N") == -1024
    # nothing was inserted, since the statement never reached the backend
    assert backend._conn.execute("SELECT COUNT(*) FROM T").fetchone()[0] == 0
```

(If a `run_linked_for_test` convenience is not desired, fold this assertion into the Task-5 e2e instead; the essential check is "SQL before CONNECT ⇒ -1024 and no DB effect".)

- [ ] **Step 2: Add connection state to `_Ctx`** — make `_Ctx` carry the registry + a mutable connection holder:

```python
@dataclass
class _ConnState:
    """The mutable current-connection holder (None == disconnected)."""
    current: object | None = None  # SqlBackend | None


@dataclass(frozen=True)
class _Ctx:
    connections: Mapping[str, SqlBackend]   # name -> backend registry (live)
    conn: _ConnState                        # mutable current-connection holder
    cursors: dict
    field_meta: Mapping[str, dict]
```

- [ ] **Step 3: Connection handlers + name resolution** — add to `exec_sql.py`:

```python
SQLCODE_NO_CONNECTION = -1024   # SQL with no current connection
SQLCODE_DB_NOT_FOUND = -1013    # CONNECT TO an unknown database
SQLCODE_NOT_ESTABLISHED = -1338  # SET CONNECTION to a non-established connection


def _resolve_db_name(ctx: _Ctx, vm, parsed) -> str:
    """The target database name: a literal, or the runtime value of a host var."""
    target = parsed.connect_db
    if isinstance(target, str):
        return target
    # host-var target: read it from WS and upper-case (DB2 db names are upper).
    value = read_params(vm, (target.name,), ctx.field_meta)[0]
    return str(value).strip().upper()


def _h_connect(ctx: _Ctx, parsed, vm) -> None:
    if parsed.connect_variant == "RESET":
        ctx.conn.current = None
        write_sqlcode(vm, 0)
        return
    name = _resolve_db_name(ctx, vm, parsed)
    backend = ctx.connections.get(name)
    if backend is None:
        write_sqlcode(vm, SQLCODE_DB_NOT_FOUND)
        return
    ctx.conn.current = backend
    write_sqlcode(vm, 0)


def _h_set_connection(ctx: _Ctx, parsed, vm) -> None:
    backend = ctx.connections.get(_resolve_db_name(ctx, vm, parsed))
    if backend is None:
        write_sqlcode(vm, SQLCODE_NOT_ESTABLISHED)
        return
    ctx.conn.current = backend
    write_sqlcode(vm, 0)


def _h_disconnect(ctx: _Ctx, _parsed, vm) -> None:
    ctx.conn.current = None
    write_sqlcode(vm, 0)
```

> **Requirement — idempotent re-connect + credentials ignored (do not "optimize" away).**
> `_h_connect` must (a) succeed and return SQLCODE 0 when the program CONNECTs to a
> name that is already current — it simply re-assigns `current` to the same backend —
> and (b) **never read or validate** the `USER`/`USING` host vars (they exist in the
> statement's `in_vars` but `_h_connect` only resolves `connect_db`). This is not
> cosmetic: **28 of the 30 GitHub testbed `.sqb` programs** use this idiom (verified in
> `cursor.sqb`, `updat.sqb`, `static.sqb`, …):
>
> ```cobol
>        if userid = spaces
>          EXEC SQL CONNECT TO sample END-EXEC      *> conditional connect
>        else
>          ...
>          accept passwd-name.                       *> period ENDS the IF here
>        EXEC SQL CONNECT TO sample USER :userid USING :passwd END-EXEC.  *> runs UNCONDITIONALLY
> ```
>
> Because the period terminates the `IF`, the second `CONNECT TO sample USER/USING`
> fires on *every* path — so when `userid` is spaces (the batch default with no input
> channel), the program connects to `SAMPLE`, then immediately connects to `SAMPLE`
> again with empty credentials. Both must yield SQLCODE 0 against the `{"SAMPLE": ...}`
> registry, leaving `current` pointing at the same backend. If `_h_connect` rejected a
> re-connect, or tried to authenticate the empty `USER`/`USING`, every one of these 28
> unmodified testbed programs would fail. The two non-connecting programs
> (`inpsrv.sqb`, `outsrv.sqb`) are stored procedures that run inside the engine and
> correctly never CONNECT — they are out of scope here.
>
> Add a unit test in `tests/unit/test_connection.py` asserting the idiom (re-CONNECT to
> the current db, and a `CONNECT TO :db USER :u USING :p` whose creds are unread, both
> return 0 and leave `current` set).

- [ ] **Step 4: Gate execute/cursor handlers on the current connection** — route them through `ctx.conn.current` instead of a fixed backend, returning `-1024` when disconnected. For `_h_query`:

```python
def _h_query(ctx: _Ctx, parsed, vm) -> None:
    if ctx.conn.current is None:
        write_sqlcode(vm, SQLCODE_NO_CONNECTION)
        return
    params = read_params(vm, _host_names(parsed.in_vars), ctx.field_meta)
    result = ctx.conn.current.execute(parsed.query, params)
    code = (
        _bind_row(vm, parsed.out_vars, result, ctx.field_meta)
        if parsed.kind == "select_into"
        else result.sqlcode
    )
    write_sqlcode(vm, code)
```

Apply the same `if ctx.conn.current is None: -1024; return` guard and `ctx.conn.current` routing to `_h_open`, `_h_fetch`, `_h_close`, `_h_commit`, `_h_rollback` (each uses `ctx.conn.current` where it used `ctx.backend`).

- [ ] **Step 5: Register the handlers + drop the no-ops** — update `_HANDLERS` and `_NO_OP_KINDS`:

```python
_NO_OP_KINDS = frozenset({"begin_declare", "end_declare"})  # connection kinds removed

_HANDLERS = {
    "declare_cursor": _h_declare_cursor,
    "open_": _h_open,
    "fetch": _h_fetch,
    "close": _h_close,
    "commit": _h_commit,
    "rollback": _h_rollback,
    "connect": _h_connect,
    "set_connection": _h_set_connection,
    "disconnect": _h_disconnect,
    **{kind: _h_noop for kind in _NO_OP_KINDS},
}
```

- [ ] **Step 6: Build `_Ctx` with the registry** in `make_exec_sql_builtin`:

```python
def make_exec_sql_builtin(
    connections: Mapping[str, SqlBackend], plans: list, field_meta: Mapping[str, dict]
) -> Callable:
    ctx = _Ctx(connections=connections, conn=_ConnState(current=None),
               cursors={}, field_meta=field_meta)
    def __exec_sql(args, vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult
        parsed = plans[int(args[0].value)]
        _HANDLERS.get(parsed.kind, _h_query)(ctx, parsed, vm)
        return BuiltinResult(value=None)
    return __exec_sql
```

(`_bind_row` etc. unchanged.)

- [ ] **Step 7:** `uv run python -m pytest tests/unit/test_connection.py -q` → PASS once Task 3 lands the plumbing; **Commit** with Task 3.

---

## Task 3: Thread the registry through strategy + helper

**Files:** Modify `squall/strategy.py`, `tests/integration/squall_cobol_helpers.py`.

- [ ] **Step 1: `SqlLoweringStrategy.__init__`** takes `connections: Mapping[str, SqlBackend]` (replacing `backend`); pass to `make_exec_sql_builtin(connections, self._plans, field_meta)`. Update the docstring/attribute (`self._connections`).

- [ ] **Step 2: helper** — `compile_cobol`/`run_cobol` parameter `backend` → `connections: dict[str, SqlBackend]`; pass to `SqlLoweringStrategy(connections, prepass.field_meta)`. (Optional convenience for single-db callers: accept a lone `SqlBackend` and wrap it as `{"SAMPLE": backend}` — decide in review; the explicit-registry form is the faithful default.)

- [ ] **Step 3:** runs after Task 4 (callers updated). Commit Tasks 2+3 together once the suite is migrated:

```bash
git add squall/builtins/exec_sql.py squall/strategy.py tests/integration/squall_cobol_helpers.py tests/unit/test_connection.py
git commit -m "feat(sql): connection registry + per-run lifecycle (-1024/-1013/-1338); always-disconnected"
```

---

## Task 4: Migrate the existing suite to explicit connections

(Always-disconnected means every program that runs SQL must CONNECT, and every caller must pass a registry. The `.sqb` testbed programs already `CONNECT TO sample`; the inline test programs and the unit harness do not.)

- [ ] **Step 1: Inline integration programs** — prepend `EXEC SQL CONNECT TO SAMPLE END-EXEC` to each inline program that lacks one, and pass `{"SAMPLE": backend}` instead of `backend`:
  - `tests/integration/test_crud_e2e.py` — `_PROGRAM` and `_VARCHAR_PROGRAM`.
  - `tests/integration/test_include_dclgen_e2e.py` — `_COBOL_INCLUDE_DCLGEN` (both hit/miss).
  - `tests/integration/test_select_into_e2e.py` — its program(s).
  Each `run_cobol(..., backend, ...)` → `run_cobol(..., {"SAMPLE": backend}, ...)`.

- [ ] **Step 2: `.sqb` integration tests** — `test_db2_cursor_e2e`, `test_db2_static_e2e`, `test_db2_transactions`: these already `CONNECT TO sample`, so only register the backend under `"SAMPLE"`: `run_cobol(src, jar, {"SAMPLE": Db2Backend(conn)}, ...)`.

- [ ] **Step 3: Unit harness (session-style)** — in `tests/unit/test_builtin.py` and `tests/unit/test_cursor.py`, the builtin is now disconnected at start. Restructure `_call_builtin` into a session helper that builds ONE builtin over a registry and issues a `CONNECT` first, e.g.:

```python
def _session(backend):
    """Return (issue, vm, region) — `issue(sql)` runs one EXEC SQL on a shared
    builtin (so connection + cursor state persist across calls)."""
    from squall.parser.parse import parse_exec_sql
    plans: list = []
    builtin = make_exec_sql_builtin({"SAMPLE": backend}, plans, {})
    vm, region = _make_vm()
    def issue(sql):
        plans.append(parse_exec_sql(sql))
        return builtin([_TypedValue(len(plans) - 1)], vm)
    issue("EXEC SQL CONNECT TO SAMPLE END-EXEC")  # establish the connection
    return issue, vm, region
```

Rewrite each test to `issue, vm, region = _session(backend); issue("EXEC SQL SELECT … END-EXEC"); assert …`. (test_cursor's DECLARE/OPEN/FETCH/CLOSE sequence runs on the one `issue`.) Keep `test_binding.py` unchanged — it exercises `read_params`/`write_outputs` *below* the connection layer.

- [ ] **Step 4: Full unit + (sqlite) integration regression** — `uv run python -m pytest tests/ -q` (DB2 env optional for this step) → green. **Commit** with Tasks 2+3.

---

## Task 5: DB2 two-database routing e2e

**Prerequisite (one-time):** a second DB2 database alongside `MOJO`, with its own DSN:

```bash
docker exec db2server su - db2inst1 -c "db2 create database MOJO2"
# export SQUALL_DB2_DSN2="DATABASE=MOJO2;HOSTNAME=localhost;PORT=50000;PROTOCOL=TCPIP;UID=db2inst1;PWD=db2rocks;"
```

**Files:** Create `tests/integration/test_db2_connect_e2e.py`.

- [ ] **Step 1: Failing test** — a program that routes between two databases and exercises the lifecycle codes:

```python
"""
tests/integration/test_db2_connect_e2e.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Faithful CONNECT against TWO real Db2 databases (MOJO + MOJO2). A program
CONNECTs to DBA, inserts, CONNECTs to DBB, inserts, RESETs, then a final
statement must report -1024. We verify each row landed in the right database and
the disconnected statement failed. Requires PROLEAP_BRIDGE_JAR, SQUALL_DB2_DSN,
SQUALL_DB2_DSN2 (no skip, fail loud).
"""
from __future__ import annotations
import importlib.util, os
from pathlib import Path

_HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("squall_cobol_helpers", _HERE / "squall_cobol_helpers.py")
_helpers = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_helpers)
run_cobol = _helpers.run_cobol
read_ws_field = _helpers.read_ws_field
bridge_jar = _helpers.bridge_jar  # noqa: F401

from squall.backends.db2 import Db2Backend
_DB2_INCLUDES = _HERE / "db2_includes"

_PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONNE2E.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
       01 WS-RC PIC S9(9) COMP.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC SQL CONNECT TO DBA END-EXEC
           EXEC SQL INSERT INTO ROUTED VALUES (111) END-EXEC
           EXEC SQL CONNECT TO DBB END-EXEC
           EXEC SQL INSERT INTO ROUTED VALUES (222) END-EXEC
           EXEC SQL CONNECT RESET END-EXEC
           EXEC SQL INSERT INTO ROUTED VALUES (999) END-EXEC
           MOVE SQLCODE TO WS-RC.
           STOP RUN.
"""


def test_connect_routes_between_two_db2_databases(bridge_jar):
    import ibm_db
    ca = ibm_db.connect(os.environ["SQUALL_DB2_DSN"], "", "")
    cb = ibm_db.connect(os.environ["SQUALL_DB2_DSN2"], "", "")

    def setup(c):
        try: ibm_db.exec_immediate(c, "DROP TABLE ROUTED")
        except Exception: pass
        ibm_db.exec_immediate(c, "CREATE TABLE ROUTED (ID INTEGER)")
        ibm_db.commit(c)
    try:
        setup(ca); setup(cb)
        vm = run_cobol(
            _PROGRAM, bridge_jar,
            {"DBA": Db2Backend(ca), "DBB": Db2Backend(cb)},
            copybook_dirs=[_DB2_INCLUDES], max_steps=4000,
        )
        # row 111 routed to DBA only; 222 to DBB only.
        def count(c, v):
            s = ibm_db.exec_immediate(c, f"SELECT COUNT(*) FROM ROUTED WHERE ID={v}")
            ibm_db.fetch_row(s); return int(ibm_db.result(s, 0))
        assert count(ca, 111) == 1 and count(ca, 222) == 0
        assert count(cb, 222) == 1 and count(cb, 111) == 0
        # the INSERT after CONNECT RESET hit no connection.
        assert read_ws_field(vm, "WS-RC") == -1024
        assert count(ca, 999) == 0 and count(cb, 999) == 0
    finally:
        for c in (ca, cb):
            try: ibm_db.exec_immediate(c, "DROP TABLE ROUTED"); ibm_db.commit(c)
            except Exception: pass
            ibm_db.close(c)
```

- [ ] **Step 2: Run → green** (routing + `-1024`). Add a second test for `-1013` (`CONNECT TO BOGUS`) and `SET CONNECTION` switching, mirroring the structure.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_db2_connect_e2e.py
git commit -m "test(sql): two-database DB2 CONNECT routing + lifecycle e2e"
```

---

## Task 6: Full regression, lint, bead

- [ ] **Step 1:** `uv run python -m black squall/ tests/`
- [ ] **Step 2:** `SQUALL_DB2_DSN=… SQUALL_DB2_DSN2=… PROLEAP_BRIDGE_JAR=… uv run python -m pytest tests/ -q` → all green.
- [ ] **Step 3:** `uv run python -m python_fp_lint check squall/parser/parse.py squall/builtins/exec_sql.py squall/strategy.py` and `uv run pyright …` → no new violations.
- [ ] **Step 4:** close the bead:

```bash
bd close squall-yml --reason "Faithful CONNECT: name->backend registry, per-run connection lifecycle (always-disconnected; -1024/-1013/-1338), routing/SET CONNECTION/RESET. Two-DB2-database routing e2e. Credential validation and the cicada pseudo-conversational reset (cicada-6hv / squall-ipq) remain out of scope."
```

---

## Notes for the implementer

- **`current` is the only mutable connection state.** Keep it in the `_ConnState` holder inside the (frozen) `_Ctx` — the registry dict and cursors dict are mutated in place exactly like today.
- **Why a registry, not a single backend:** `CONNECT TO <name>` *routes*; the synthetic e2e proves a row lands only in the named database. The single-backend convenience wrapper (`{"SAMPLE": backend}`) is for tests, not the contract.
- **Always-disconnected is deliberate** — do not add a "start connected" shortcut. SQL before CONNECT must be `-1024`; that is what makes the lifecycle real and is exercised by `test_sql_before_connect_is_minus_1024` and the post-`RESET` insert in the e2e.
- **Per-run scope:** the session lives in the builtin closure (per compiled program / per run for batch). Do **not** try to persist it across runs/turns — under cicada that is closed at the pseudo-conversational `RETURN` by `cicada-6hv`/`squall-ipq`, and conversational runs preserve it naturally.
- **Credentials are surfaced but never consumed** — the parser leaves `USER`/`USING` host vars in `in_vars`, but `_h_connect` resolves only `connect_db` and never reads or authenticates them (backends are pre-authenticated). See the Task 2 idempotent-re-connect requirement — this is what lets the testbed's unconditional double-CONNECT idiom pass unmodified. Don't pretend to authenticate.
- **Do not** put any of this in the VM byte-region: the registry holds live, non-serializable backends, and squall must not edit `interpreter/vm/**`.
