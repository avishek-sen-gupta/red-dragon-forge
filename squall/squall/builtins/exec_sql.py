"""
squall.builtins.exec_sql
~~~~~~~~~~~~~~~~~~~~~~~~
Factory for the ``__exec_sql`` builtin — the single dispatch point for all
EXEC SQL … END-EXEC statements in slice 1.

Design
------
* ``make_exec_sql_builtin`` closes over a **connection registry** (name →
  ``SqlBackend``) and returns a callable with the RedDragon builtin signature
  ``(args, vm) -> BuiltinResult``.
* The single argument is the ``ParsedSql`` plan produced ONCE at lowering time
  (``squall.strategy.SqlLoweringStrategy.lower``). The builtin does **no
  parsing** at run time — it only binds host vars and executes the plan, so a
  statement in a PERFORM loop is parsed once, not on every pass.
* Connection lifecycle is **faithful**: a run starts *disconnected*. ``CONNECT
  TO <db>`` sets the current connection from the registry; ``SET CONNECTION``
  switches it; ``CONNECT RESET`` / ``DISCONNECT`` clears it. Data statements
  route through the current connection and report ``-1024`` when there is none.
  The current connection is the one piece of per-run mutable session state (a
  ``_ConnState`` holder), alongside the cursor registry.
* Dispatch:
    - ``connect`` / ``set_connection`` / ``disconnect``: manage the session.
    - ``select_into``: bind inputs, execute, write outputs, write SQLCODE.
    - DML kinds with a non-empty query (insert/update/delete/…): execute + write SQLCODE.
    - Cursor kinds (declare_cursor/open_/fetch/close): driven through the
      current connection's cursor surface via a per-run cursor registry.
    - Declare-section bookends: no-op with SQLCODE 0.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from squall.backend import SqlBackend
from squall.connector import DbConnector, NamedDbConnector, NullDbConnector
from squall.binding import (
    read_params,
    validate_field_meta,
    write_outputs,
    write_sqlcode,
)
from squall.parser.sql_model import (
    ConnectReset,
    ConnectTo,
    FieldMeta,
    HostVarDb,
    Kind,
    LiteralDb,
    NamedCursor,
    ParsedSql,
)

if TYPE_CHECKING:
    from interpreter.vm.vm_types import BuiltinResult

# SQLCODEs for connection lifecycle (DB2-faithful values).
SQLCODE_NO_CONNECTION = -1024  # a data statement issued while disconnected
SQLCODE_DB_NOT_FOUND = -1013  # CONNECT TO an unknown database name
SQLCODE_NOT_ESTABLISHED = -1338  # SET CONNECTION to a connection not established

# The host-var declare-section bookends are purely declarative — no DB effect.
_NO_OP_KINDS = frozenset({Kind.BEGIN_DECLARE, Kind.END_DECLARE})


def _host_names(host_vars) -> tuple[str, ...]:
    """The host-var names, in order — the form read_params/write_outputs expect."""
    return tuple(hv.name for hv in host_vars)


def _bind_row(vm, out_vars, result, field_meta: Mapping[str, FieldMeta]) -> int:
    """Bind *result*'s first row into *out_vars*; return the resulting SQLCODE.

    A no-row result leaves the host vars untouched and reports ``result.sqlcode``
    (0 / 100). On a strict-coercion failure ``write_outputs`` writes nothing and
    returns the failure code, which overrides the otherwise-successful SQLCODE.
    """
    if not result.rows:
        return result.sqlcode
    status = write_outputs(vm, _host_names(out_vars), result.rows[0], field_meta)
    return status if status != 0 else result.sqlcode


@dataclass
class _ConnState:
    """The mutable current-connection holder. ``current is None`` means the run
    is disconnected (the initial state, and after CONNECT RESET / DISCONNECT)."""

    current: SqlBackend | None = None


@dataclass(frozen=True)
class _Ctx:
    """The per-run handler context: the connection registry (name → backend),
    the mutable current-connection holder, the cursor registry (mutated in place
    across DECLARE→OPEN→FETCH→CLOSE), and the dclgen field metadata."""

    connections: Mapping[str, SqlBackend]
    conn: _ConnState
    cursors: dict[str, ParsedSql]
    field_meta: Mapping[str, FieldMeta]
    tolerant: bool = False


def _current(ctx: _Ctx, vm) -> SqlBackend | None:
    """The current connection, or None after writing SQLCODE -1024 (disconnected).

    Mirrors the ``cursors.get(...) is None`` guard pattern: a None return means
    the caller must stop — the no-connection SQLCODE has already been written.
    """
    if ctx.conn.current is None:
        write_sqlcode(vm, SQLCODE_NO_CONNECTION)
        return None
    return ctx.conn.current


def _resolve_db(spec, ctx: _Ctx, vm) -> str:
    """The target database name from a ConnectTo spec: a parse-time literal, or
    the runtime value of a host var (DB2 database names are upper-cased)."""
    match spec:
        case ConnectTo(LiteralDb(name)):
            return name
        case ConnectTo(HostVarDb(var)):
            value = read_params(vm, (var.name,), ctx.field_meta)[0]
            return str(value).strip().upper()
        case _:
            raise AssertionError(f"_resolve_db reached with {spec!r}")


def _h_noop(_ctx: _Ctx, _parsed, vm) -> None:
    # Declare-section bookends have no DB effect.
    write_sqlcode(vm, 0)


def _h_connect(ctx: _Ctx, parsed, vm) -> None:
    # CONNECT RESET disconnects; CONNECT TO <db> establishes the current
    # connection from the registry, resolved through the same DbConnector
    # abstraction the pre-run initial_connector uses (one resolution path, not
    # two). Credentials (USER/USING) are intentionally never read — backends
    # are pre-authenticated — so the testbed's unconditional double-CONNECT
    # idiom (re-connect to the same db) succeeds idempotently.
    if isinstance(parsed.connect, ConnectReset):
        ctx.conn.current = None
        write_sqlcode(vm, 0)
        return
    backend = NamedDbConnector(_resolve_db(parsed.connect, ctx, vm)).connect(
        ctx.connections
    )
    if backend is None:
        write_sqlcode(vm, SQLCODE_DB_NOT_FOUND)
        return
    ctx.conn.current = backend
    write_sqlcode(vm, 0)


def _h_set_connection(ctx: _Ctx, parsed, vm) -> None:
    # Switch the current connection to an already-registered database, resolved
    # through the same DbConnector abstraction as CONNECT TO.
    backend = NamedDbConnector(_resolve_db(parsed.connect, ctx, vm)).connect(
        ctx.connections
    )
    if backend is None:
        write_sqlcode(vm, SQLCODE_NOT_ESTABLISHED)
        return
    ctx.conn.current = backend
    write_sqlcode(vm, 0)


def _h_disconnect(ctx: _Ctx, _parsed, vm) -> None:
    ctx.conn.current = None
    write_sqlcode(vm, 0)


def _cursor_name(ref) -> str:
    """The cursor name; cursor handlers only ever run for NamedCursor refs."""
    match ref:
        case NamedCursor(name):
            return name
        case _:
            raise AssertionError(f"cursor handler reached with {ref!r}")


def _h_declare_cursor(ctx: _Ctx, parsed, vm) -> None:
    # Declaration only — remember the SELECT + its host vars for OPEN.
    ctx.cursors[_cursor_name(parsed.cursor)] = parsed
    write_sqlcode(vm, 0)


def _h_open(ctx: _Ctx, parsed, vm) -> None:
    backend = _current(ctx, vm)
    if backend is None:
        return
    decl = ctx.cursors.get(_cursor_name(parsed.cursor))
    if decl is None:
        write_sqlcode(vm, -1)  # cursor not declared
        return
    # Host vars are captured at OPEN: OPEN ... USING overrides, else the cursor
    # SELECT's own host vars.
    params = read_params(
        vm,
        _host_names(parsed.in_vars or decl.in_vars),
        ctx.field_meta,
        tolerant=ctx.tolerant,
    )
    backend.open_cursor(_cursor_name(parsed.cursor), decl.query, params)
    write_sqlcode(vm, 0)


def _h_fetch(ctx: _Ctx, parsed, vm) -> None:
    backend = _current(ctx, vm)
    if backend is None:
        return
    result = backend.fetch(_cursor_name(parsed.cursor))
    write_sqlcode(vm, _bind_row(vm, parsed.out_vars, result, ctx.field_meta))


def _h_close(ctx: _Ctx, parsed, vm) -> None:
    backend = _current(ctx, vm)
    if backend is None:
        return
    backend.close(_cursor_name(parsed.cursor))
    write_sqlcode(vm, 0)


def _h_commit(ctx: _Ctx, _parsed, vm) -> None:
    backend = _current(ctx, vm)
    if backend is None:
        return
    backend.commit()
    write_sqlcode(vm, 0)


def _h_rollback(ctx: _Ctx, _parsed, vm) -> None:
    backend = _current(ctx, vm)
    if backend is None:
        return
    backend.rollback()
    write_sqlcode(vm, 0)


def _reset_session(ctx: _Ctx) -> None:
    """Implicit SYNCPOINT: commit the current connection (if any) and close
    every declared cursor — models the unit-of-work commit + cursor release a
    real CICS-attached Db2 session gets at task end. ``backend.close`` is a
    no-op for a name that was never actually opened, so it's safe to close
    every DECLAREd cursor unconditionally rather than tracking which ones are
    currently open.
    """
    backend = ctx.conn.current
    if backend is None:
        return
    backend.commit()
    for name in ctx.cursors:
        backend.close(name)


def _h_query(ctx: _Ctx, parsed, vm) -> None:
    # All remaining kinds carry a non-empty query string.
    backend = _current(ctx, vm)
    if backend is None:
        return
    params = read_params(
        vm, _host_names(parsed.in_vars), ctx.field_meta, tolerant=ctx.tolerant
    )
    result = backend.execute(parsed.query, params)
    code = (
        _bind_row(vm, parsed.out_vars, result, ctx.field_meta)
        if parsed.kind is Kind.SELECT_INTO
        else result.sqlcode
    )
    write_sqlcode(vm, code)


# Dispatch table: EXEC SQL kind -> handler. Kinds with a non-empty query
# (select_into / insert / update / delete / …) fall to _h_query (the default).
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


def make_exec_sql_builtin(
    connections: Mapping[str, SqlBackend],
    plans: list,
    field_meta: Mapping[str, FieldMeta],
    initial_connector: DbConnector = NullDbConnector(),
    *,
    tolerant: bool = False,
) -> tuple[Callable, Callable]:
    """Return a ``__exec_sql`` builtin over the connection registry *connections*
    (name → backend), the plan pool, and the dclgen *field_meta* map (loaded once
    by the prepass, shared by reference).

    The run starts *disconnected*: a data statement before a successful CONNECT
    reports SQLCODE -1024. ``CONNECT TO``/``SET CONNECTION`` select the current
    connection from *connections*, through the same ``DbConnector`` abstraction
    ``initial_connector`` uses; ``CONNECT RESET``/``DISCONNECT`` clear it.

    *initial_connector*, when it resolves a backend, is already current when
    the run starts — modelling the CICS Db2 attachment facility, which
    establishes the thread before a plan-bound program's first SQL statement
    runs (the program itself never issues ``EXEC SQL CONNECT``). The default
    ``NullDbConnector()`` preserves the faithful disconnected-start behaviour
    for programs that do their own ``CONNECT``; pass a ``NamedDbConnector(name)``
    to model the attachment facility instead.

    *plans* is the lowering-time constant pool of ``ParsedSql`` objects
    (``SqlLoweringStrategy._plans``). Each call site passes its plan's pool index
    as the single argument; the builtin resolves it and dispatches by kind via
    ``_HANDLERS`` — it never parses at run time.

    Both ``exec_sql_builtin`` and ``reset_session_builtin`` have the standard
    RedDragon builtin signature: ``(args: list[TypedValue], vm: VMState) ->
    BuiltinResult`` — both close over the same per-run session state.
    """
    # Per-run session: the current connection (resolved once, up front, via
    # initial_connector — disconnected unless it names a real entry) + the
    # cursor registry (DECLARE records, OPEN reads).
    ctx = _Ctx(
        connections=connections,
        conn=_ConnState(current=initial_connector.connect(connections)),
        cursors={},
        field_meta=field_meta,
        tolerant=tolerant,
    )

    def __exec_sql(args: list, vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        # Fail loud on any dclgen/copybook category drift before binding anything.
        # Stateless: validate_field_meta is a pure check over the (fixed) layout
        # and field_meta — cheap dict lookups, re-run per call rather than cached
        # behind a mutable "already validated" flag.
        validate_field_meta(vm.data_layout, field_meta, tolerant=tolerant)

        parsed = plans[int(args[0].value)]
        _HANDLERS.get(parsed.kind, _h_query)(ctx, parsed, vm)
        return BuiltinResult(value=None)

    def __reset_session(args: list, vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        _reset_session(ctx)
        return BuiltinResult(value=None)

    return __exec_sql, __reset_session
