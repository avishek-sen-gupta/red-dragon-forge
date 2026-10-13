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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from squall.backend import SqlBackend
from squall.binding import (
    read_params,
    resolve_dml_sqlcode,
    write_outputs,
    write_sqlcode,
)
from squall.connector import DbConnector, NamedDbConnector, NullDbConnector
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
from squall.strategy_stores import ABSENT, Absent

if TYPE_CHECKING:
    from interpreter.types.typed_value import TypedValue
    from interpreter.vm.vm_types import BuiltinResult

# SQLCODEs for connection lifecycle (DB2-faithful values).
SQLCODE_NO_CONNECTION = -1024  # a data statement issued while disconnected
SQLCODE_DB_NOT_FOUND = -1013  # CONNECT TO an unknown database name
SQLCODE_NOT_ESTABLISHED = -1338  # SET CONNECTION to a connection not established
SQLCODE_CURSOR_NOT_OPEN = -501  # FETCH/CLOSE on a cursor that is not open right now
# (never DECLAREd, DECLAREd but never OPENed, or already CLOSEd -- Db2 reports the
# same -501 for all three; only a genuinely open cursor is exempt)

# The host-var declare-section bookends are purely declarative — no DB effect.
_NO_OP_KINDS = frozenset({Kind.BEGIN_DECLARE, Kind.END_DECLARE})

# A module-level singleton rather than a call in make_exec_sql_builtin's own
# default (B008 — mirrors squall.strategy._NO_CONNECTOR exactly): a fresh
# NullDbConnector() is stateless, so every caller that doesn't pass its own
# can safely share this one instance.
_NO_CONNECTOR: DbConnector = NullDbConnector()


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
    across DECLARE→OPEN→FETCH→CLOSE), the dclgen field metadata, and the set of
    cursor names currently OPEN.

    ``cursors`` and ``open_cursors`` answer different questions and must not be
    conflated: ``cursors`` is "has this name ever been DECLAREd" (it survives
    OPEN/CLOSE and even task end — see ``_close_all_cursors``), while
    ``open_cursors`` is "can FETCH/CLOSE act on this name right now". A name can
    be declared without being open (never OPENed yet, or already CLOSEd), which
    is exactly the case Db2 reports SQLCODE -501 for.
    """

    connections: Mapping[str, SqlBackend]
    conn: _ConnState
    cursors: dict[str, ParsedSql]
    open_cursors: set[str]
    field_meta: Mapping[str, FieldMeta]
    tolerant: bool = False


def _current(ctx: _Ctx, vm) -> SqlBackend | None:
    """The current connection, or None after writing SQLCODE -1024 (disconnected).

    A None return means the caller must stop — the no-connection SQLCODE has
    already been written.
    """
    match ctx.conn.current:
        case None:
            write_sqlcode(vm, SQLCODE_NO_CONNECTION)
            return None
        case backend:
            return backend


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
    match NamedDbConnector(_resolve_db(parsed.connect, ctx, vm)).connect(
        ctx.connections
    ):
        case None:
            write_sqlcode(vm, SQLCODE_DB_NOT_FOUND)
        case backend:
            ctx.conn.current = backend
            write_sqlcode(vm, 0)


def _h_set_connection(ctx: _Ctx, parsed, vm) -> None:
    # Switch the current connection to an already-registered database, resolved
    # through the same DbConnector abstraction as CONNECT TO.
    match NamedDbConnector(_resolve_db(parsed.connect, ctx, vm)).connect(
        ctx.connections
    ):
        case None:
            write_sqlcode(vm, SQLCODE_NOT_ESTABLISHED)
        case backend:
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


def _open_declared_cursor(
    backend: SqlBackend, ctx: _Ctx, parsed, decl, name: str, vm
) -> None:
    """The OPEN half once *name* is known to have a DECLARE on file — split
    out of ``_open_on`` to keep it under the statement-count gate."""
    # Host vars are captured at OPEN: OPEN ... USING overrides, else the
    # cursor SELECT's own host vars.
    params = read_params(
        vm,
        _host_names(parsed.in_vars or decl.in_vars),
        ctx.field_meta,
        tolerant=ctx.tolerant,
    )
    sqlcode = backend.open_cursor(name, decl.query, params)
    if sqlcode == 0:
        ctx.open_cursors.add(name)
    write_sqlcode(vm, sqlcode)


def _open_on(backend: SqlBackend, ctx: _Ctx, parsed, vm) -> None:
    """The OPEN half that needs a live connection — split out of _h_open so
    neither function nests a second is-None guard inside the first."""
    name = _cursor_name(parsed.cursor)
    match ctx.cursors.get(name):
        case None:
            write_sqlcode(vm, -1)  # cursor not declared
        case decl:
            _open_declared_cursor(backend, ctx, parsed, decl, name, vm)


def _h_open(ctx: _Ctx, parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            _open_on(backend, ctx, parsed, vm)


def _h_fetch(ctx: _Ctx, parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            name = _cursor_name(parsed.cursor)
            if name not in ctx.open_cursors:
                # Db2-faithful -501: covers a name never reached by DECLARE
                # CURSOR, a declared cursor never OPENed, and one already
                # CLOSEd -- all three are "not open right now", distinct from
                # a genuinely open cursor with no more rows, which the
                # backend itself reports as end-of-cursor (+100).
                write_sqlcode(vm, SQLCODE_CURSOR_NOT_OPEN)
                return
            result = backend.fetch(name)
            write_sqlcode(vm, _bind_row(vm, parsed.out_vars, result, ctx.field_meta))


def _h_close(ctx: _Ctx, parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            name = _cursor_name(parsed.cursor)
            if name not in ctx.open_cursors:
                write_sqlcode(vm, SQLCODE_CURSOR_NOT_OPEN)
                return
            backend.close(name)
            ctx.open_cursors.discard(name)
            write_sqlcode(vm, 0)


def _h_commit(ctx: _Ctx, _parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            backend.commit()
            write_sqlcode(vm, 0)


def _h_rollback(ctx: _Ctx, _parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            backend.rollback()
            write_sqlcode(vm, 0)


def _close_all_cursors(ctx: _Ctx, backend: SqlBackend) -> None:
    """``backend.close`` is a no-op for a name that was never actually
    opened, so it's safe to close every DECLAREd cursor unconditionally
    rather than checking ``open_cursors`` first for each one. The DECLARE
    registry (``ctx.cursors``) itself is untouched here -- a WORKING-STORAGE
    DECLARE must survive task end, since nothing will ever re-DECLARE it.
    ``open_cursors`` is cleared, though: every one of them really is closed
    now, and a stale entry would let a later FETCH wrongly believe a cursor
    still open.
    """
    for name in ctx.cursors:
        backend.close(name)
    ctx.open_cursors.clear()


def _end_of_uow(ctx: _Ctx, *, commit: bool, close_cursors: bool) -> None:
    """Settle the current connection's pending unit of work and, when asked,
    release every declared cursor. Shared by task end, syncpoint and
    rollback — they differ only in whether they commit or roll back, and
    whether cursors are closed.
    """
    match ctx.conn.current:
        case None:
            return
        case backend:
            (backend.commit if commit else backend.rollback)()
            if close_cursors:
                _close_all_cursors(ctx, backend)


def _reset_session(ctx: _Ctx) -> None:
    """Implicit task end (EXEC CICS RETURN): commit the current connection
    (if any) and close every declared cursor — models the unit-of-work
    commit + cursor release a real CICS-attached Db2 session gets at task
    end.
    """
    _end_of_uow(ctx, commit=True, close_cursors=True)


def _syncpoint(ctx: _Ctx) -> None:
    """EXEC CICS SYNCPOINT: commit the current connection, but do NOT close
    cursors.

    Ruling (task-6 brief): real CICS closes non-WITH-HOLD cursors at
    syncpoint too, but every squall-composed program observed so far
    (COTRTLIC) opens, fetches and closes each cursor within one paragraph
    inside a single task, so no cursor is ever open across one of its
    syncpoints. Closing here would be more faithful and equally harmless
    today; not closing is simpler and cannot break the observed programs —
    a future WITH HOLD program makes this a deliberate revisit, not a
    surprise.
    """
    _end_of_uow(ctx, commit=True, close_cursors=False)


def _rollback_uow(ctx: _Ctx) -> None:
    """EXEC CICS SYNCPOINT ROLLBACK (and, via a composed on_abend callable,
    an abending task): undo the pending unit of work and close every
    declared cursor — a rolled-back transaction leaves nothing worth
    keeping open.
    """
    _end_of_uow(ctx, commit=False, close_cursors=True)


def _h_query(ctx: _Ctx, parsed, vm) -> None:
    # All remaining kinds carry a non-empty query string.
    match _current(ctx, vm):
        case None:
            return
        case backend:
            params = read_params(
                vm, _host_names(parsed.in_vars), ctx.field_meta, tolerant=ctx.tolerant
            )
            result = backend.execute(parsed.query, params)
            code = (
                _bind_row(vm, parsed.out_vars, result, ctx.field_meta)
                if parsed.kind is Kind.SELECT_INTO
                else resolve_dml_sqlcode(parsed.kind, result)
            )
            write_sqlcode(vm, code, result.sqlerrm)


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


def _make_uow_builtin(ctx: _Ctx, effect: Callable[[_Ctx], None]) -> Callable:
    """Wrap a no-argument unit-of-work effect (``_reset_session``,
    ``_syncpoint``, ``_rollback_uow``) as a builtin with the standard
    RedDragon signature — the three CICS commit-boundary hooks share this
    shape and differ only in *effect*."""

    def _uow_builtin(args: Sequence[TypedValue], vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        effect(ctx)
        return BuiltinResult(value=None)

    return _uow_builtin


def make_exec_sql_builtin(
    connections: Mapping[str, SqlBackend],
    plans: Sequence[ParsedSql],
    field_meta: Mapping[str, FieldMeta],
    initial_connector: DbConnector = _NO_CONNECTOR,
    *,
    tolerant: bool = False,
    cursors: dict[str, ParsedSql] | Absent = ABSENT,
) -> tuple[Callable, Callable, Callable, Callable]:
    """Return a ``__exec_sql`` builtin over the connection registry *connections*
    (name → backend), the plan pool, and the dclgen *field_meta* map (loaded once
    by the prepass, shared by reference).

    *cursors*, when given, becomes ``ctx.cursors`` by the SAME object
    reference rather than a copy — it is ``SqlLoweringStrategy``'s own
    ``self._cursors_store``, which ``preprocess_program_dict`` populates
    with ``DECLARE CURSOR`` plans recovered from outside PROCEDURE DIVISION
    (``squall.data_division_exec_sql``) *after* this function returns. Only
    sharing the object, not a snapshot of it, lets a later OPEN see those
    entries. When *cursors* is ``ABSENT`` (the default), a fresh, private
    dict is built instead — unchanged behaviour for every existing caller
    that never had WORKING-STORAGE cursors to recover.

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

    Returns four builtins, all sharing the standard RedDragon signature
    (``(args: list[TypedValue], vm: VMState) -> BuiltinResult``) and the same
    per-run session state: ``__exec_sql`` itself, then the three CICS
    commit-boundary hooks a composed cicada registers this strategy under by
    name convention — ``reset_session`` (task end: commit + close cursors),
    ``syncpoint`` (commit only, cursors stay open — see ``_syncpoint``), and
    ``rollback`` (roll back + close cursors).
    """
    # Per-run session: the current connection (resolved once, up front, via
    # initial_connector — disconnected unless it names a real entry) + the
    # cursor registry (DECLARE records, OPEN reads).
    ctx = _Ctx(
        connections=connections,
        conn=_ConnState(current=initial_connector.connect(connections)),
        cursors={} if isinstance(cursors, Absent) else cursors,
        open_cursors=set(),
        field_meta=field_meta,
        tolerant=tolerant,
    )

    def __exec_sql(args: Sequence[TypedValue], vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        parsed = plans[int(args[0].value)]
        _HANDLERS.get(parsed.kind, _h_query)(ctx, parsed, vm)
        return BuiltinResult(value=None)

    return (
        __exec_sql,
        _make_uow_builtin(ctx, _reset_session),
        _make_uow_builtin(ctx, _syncpoint),
        _make_uow_builtin(ctx, _rollback_uow),
    )
