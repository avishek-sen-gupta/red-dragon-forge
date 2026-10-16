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
* The arguments are what the call site carries: the statement's text, an
  OPEN's cursor declaration text, and the VARCHAR shapes of the host variables
  it binds (``squall.strategy.SqlLoweringStrategy.lower``). The text is parsed
  here, memoised per process, so a statement in a PERFORM loop is parsed once.
* Connection lifecycle is **faithful**: a run starts *disconnected*. ``CONNECT
  TO <db>`` sets the current connection from the registry; ``SET CONNECTION``
  switches it; ``CONNECT RESET`` / ``DISCONNECT`` clears it. Data statements
  route through the current connection and report ``-1024`` when there is none.
  The current connection is per-run mutable session state (a ``_ConnState``
  holder), alongside the set of open cursors and each program's field layout,
  parsed from its declarations at its first EXEC SQL (``_Layouts``).
* Dispatch:
    - ``connect`` / ``set_connection`` / ``disconnect``: manage the session.
    - ``select_into``: bind inputs, execute, write outputs, write SQLCODE.
    - DML kinds with a non-empty query (insert/update/delete/…): execute + write SQLCODE.
    - Cursor kinds (open_/fetch/close): driven through the current connection's
      cursor surface; OPEN carries its declaration. DECLARE CURSOR is
      declarative and runs nothing.
    - Declare-section bookends: no-op with SQLCODE 0.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from typing import TYPE_CHECKING

from interpreter.cobol.field_position import FieldPosition
from interpreter.cobol.layout_data import field_positions
from interpreter.instructions import Data
from squall.backend import SqlBackend
from squall.binding import (
    read_params,
    resolve_dml_sqlcode,
    write_outputs,
    write_sqlcode,
)
from squall.connector import DbConnector, NamedDbConnector, NullDbConnector
from squall.parser.parse import parse_exec_sql
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
_NO_OP_KINDS = frozenset({Kind.BEGIN_DECLARE, Kind.END_DECLARE, Kind.DECLARE_CURSOR})

# A module-level singleton rather than a call in make_exec_sql_builtin's own
# default (B008 — mirrors squall.strategy._NO_CONNECTOR exactly): a fresh
# NullDbConnector() is stateless, so every caller that doesn't pass its own
# can safely share this one instance.
_NO_CONNECTOR: DbConnector = NullDbConnector()


def _host_names(host_vars) -> tuple[str, ...]:
    """The host-var names, in order — the form read_params/write_outputs expect."""
    return tuple(hv.name for hv in host_vars)


def _bind_row(
    vm,
    layout: Mapping[str, FieldPosition],
    out_vars,
    result,
    field_meta: Mapping[str, FieldMeta],
) -> int:
    """Bind *result*'s first row into *out_vars*; return the resulting SQLCODE.

    A no-row result leaves the host vars untouched and reports ``result.sqlcode``
    (0 / 100). On a strict-coercion failure ``write_outputs`` writes nothing and
    returns the failure code, which overrides the otherwise-successful SQLCODE.
    """
    if not result.rows:
        return result.sqlcode
    status = write_outputs(
        vm, layout, _host_names(out_vars), result.rows[0], field_meta
    )
    return status if status != 0 else result.sqlcode


@dataclass
class _ConnState:
    """The mutable current-connection holder. ``current is None`` means the run
    is disconnected (the initial state, and after CONNECT RESET / DISCONNECT)."""

    current: SqlBackend | None = None


@dataclass(frozen=True)
class _Layouts:
    """Each program's field layout, parsed at its first EXEC SQL in the run; keyed by the identity of the program's Data, which each entry keeps alive."""

    parse: Callable[[Sequence[Data]], Mapping[str, FieldPosition]]
    by_program: dict[
        tuple[int, ...], tuple[Sequence[Data], Mapping[str, FieldPosition]]
    ]

    def of(self, declarations: Sequence[Data]) -> Mapping[str, FieldPosition]:
        key = tuple(id(d) for d in declarations)
        if key not in self.by_program:
            self.by_program[key] = (declarations, self.parse(declarations))
        return self.by_program[key][1]


@dataclass(frozen=True)
class _Undeclared:
    """An OPEN whose cursor has no declaration in its program."""


@cache
def _parsed(text: str) -> ParsedSql:
    return parse_exec_sql(text)


def _shapes(values: Sequence[str]) -> Mapping[str, FieldMeta]:
    """VARCHAR field metadata from the call's (group, length child, text child) triples."""
    return {
        values[i]: FieldMeta(
            category="VARCHAR", len_var=values[i + 1], text_var=values[i + 2]
        )
        for i in range(0, len(values), 3)
    }


@dataclass(frozen=True)
class _Ctx:
    """The handler context: the connection registry (name → backend), the
    mutable current-connection holder and the set of cursor names currently
    OPEN — both per run — plus what one call carries: the VARCHAR field
    metadata of the host variables it binds and, for an OPEN, its cursor's
    declaration. ``__exec_sql`` derives the per-call context with
    ``dataclasses.replace``, which shares the per-run state by reference.
    """

    connections: Mapping[str, SqlBackend]
    conn: _ConnState
    open_cursors: set[str]
    field_meta: Mapping[str, FieldMeta]
    declaration: ParsedSql | _Undeclared
    layout: Mapping[str, FieldPosition]
    layouts: _Layouts
    tolerant: bool = False


def _current(ctx: _Ctx, vm) -> SqlBackend | None:
    """The current connection, or None after writing SQLCODE -1024 (disconnected).

    A None return means the caller must stop — the no-connection SQLCODE has
    already been written.
    """
    match ctx.conn.current:
        case None:
            write_sqlcode(vm, ctx.layout, SQLCODE_NO_CONNECTION)
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
            value = read_params(vm, ctx.layout, (var.name,), ctx.field_meta)[0]
            return str(value).strip().upper()
        case _:
            raise AssertionError(f"_resolve_db reached with {spec!r}")


def _h_noop(ctx: _Ctx, _parsed, vm) -> None:
    # Declare-section bookends have no DB effect.
    write_sqlcode(vm, ctx.layout, 0)


def _h_connect(ctx: _Ctx, parsed, vm) -> None:
    # CONNECT RESET disconnects; CONNECT TO <db> establishes the current
    # connection from the registry, resolved through the same DbConnector
    # abstraction the pre-run initial_connector uses (one resolution path, not
    # two). Credentials (USER/USING) are intentionally never read — backends
    # are pre-authenticated — so the testbed's unconditional double-CONNECT
    # idiom (re-connect to the same db) succeeds idempotently.
    if isinstance(parsed.connect, ConnectReset):
        ctx.conn.current = None
        write_sqlcode(vm, ctx.layout, 0)
        return
    match NamedDbConnector(_resolve_db(parsed.connect, ctx, vm)).connect(
        ctx.connections
    ):
        case None:
            write_sqlcode(vm, ctx.layout, SQLCODE_DB_NOT_FOUND)
        case backend:
            ctx.conn.current = backend
            write_sqlcode(vm, ctx.layout, 0)


def _h_set_connection(ctx: _Ctx, parsed, vm) -> None:
    # Switch the current connection to an already-registered database, resolved
    # through the same DbConnector abstraction as CONNECT TO.
    match NamedDbConnector(_resolve_db(parsed.connect, ctx, vm)).connect(
        ctx.connections
    ):
        case None:
            write_sqlcode(vm, ctx.layout, SQLCODE_NOT_ESTABLISHED)
        case backend:
            ctx.conn.current = backend
            write_sqlcode(vm, ctx.layout, 0)


def _h_disconnect(ctx: _Ctx, _parsed, vm) -> None:
    ctx.conn.current = None
    write_sqlcode(vm, ctx.layout, 0)


def _cursor_name(ref) -> str:
    """The cursor name; cursor handlers only ever run for NamedCursor refs."""
    match ref:
        case NamedCursor(name):
            return name
        case _:
            raise AssertionError(f"cursor handler reached with {ref!r}")


def _open_declared_cursor(
    backend: SqlBackend, ctx: _Ctx, parsed, decl, name: str, vm
) -> None:
    """The OPEN half once *name* is known to have a DECLARE on file — split
    out of ``_open_on`` to keep it under the statement-count gate."""
    # Host vars are captured at OPEN: OPEN ... USING overrides, else the
    # cursor SELECT's own host vars.
    params = read_params(
        vm,
        ctx.layout,
        _host_names(parsed.in_vars or decl.in_vars),
        ctx.field_meta,
        tolerant=ctx.tolerant,
    )
    sqlcode = backend.open_cursor(name, decl.query, params)
    if sqlcode == 0:
        ctx.open_cursors.add(name)
    write_sqlcode(vm, ctx.layout, sqlcode)


def _open_on(backend: SqlBackend, ctx: _Ctx, parsed, vm) -> None:
    """The OPEN half that needs a live connection — split out of _h_open so
    neither function nests a second is-None guard inside the first."""
    name = _cursor_name(parsed.cursor)
    match ctx.declaration:
        case _Undeclared():
            write_sqlcode(vm, ctx.layout, -1)  # cursor not declared
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
                write_sqlcode(vm, ctx.layout, SQLCODE_CURSOR_NOT_OPEN)
                return
            result = backend.fetch(name)
            write_sqlcode(
                vm,
                ctx.layout,
                _bind_row(vm, ctx.layout, parsed.out_vars, result, ctx.field_meta),
            )


def _h_close(ctx: _Ctx, parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            name = _cursor_name(parsed.cursor)
            if name not in ctx.open_cursors:
                write_sqlcode(vm, ctx.layout, SQLCODE_CURSOR_NOT_OPEN)
                return
            backend.close(name)
            ctx.open_cursors.discard(name)
            write_sqlcode(vm, ctx.layout, 0)


def _h_commit(ctx: _Ctx, _parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            backend.commit()
            write_sqlcode(vm, ctx.layout, 0)


def _h_rollback(ctx: _Ctx, _parsed, vm) -> None:
    match _current(ctx, vm):
        case None:
            return
        case backend:
            backend.rollback()
            write_sqlcode(vm, ctx.layout, 0)


def _close_all_cursors(ctx: _Ctx, backend: SqlBackend) -> None:
    """Close every open cursor and forget them all: a stale entry would let a
    later FETCH wrongly believe a cursor still open. A cursor's declaration is
    not run-time state -- each OPEN carries it -- so nothing else is reset.
    """
    for name in tuple(ctx.open_cursors):
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
                vm,
                ctx.layout,
                _host_names(parsed.in_vars),
                ctx.field_meta,
                tolerant=ctx.tolerant,
            )
            result = backend.execute(parsed.query, params)
            code = (
                _bind_row(vm, ctx.layout, parsed.out_vars, result, ctx.field_meta)
                if parsed.kind is Kind.SELECT_INTO
                else resolve_dml_sqlcode(parsed.kind, result)
            )
            write_sqlcode(vm, ctx.layout, code, result.sqlerrm)


# Dispatch table: EXEC SQL kind -> handler. Kinds with a non-empty query
# (select_into / insert / update / delete / …) fall to _h_query (the default).
_HANDLERS = {
    Kind.CONNECT: _h_connect,
    Kind.SET_CONNECTION: _h_set_connection,
    Kind.DISCONNECT: _h_disconnect,
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


def _call_context(ctx: _Ctx, parsed: ParsedSql, rest: Sequence[str]) -> _Ctx:
    match parsed.kind, rest:
        case Kind.OPEN, (declaration, *shapes):
            return replace(
                ctx, declaration=_parsed(declaration), field_meta=_shapes(shapes)
            )
        case _:
            return replace(ctx, field_meta=_shapes(rest))


def make_exec_sql_builtin(
    connections: Mapping[str, SqlBackend],
    initial_connector: DbConnector = _NO_CONNECTOR,
    *,
    tolerant: bool = False,
    layout_of: Callable[
        [Sequence[Data]], Mapping[str, FieldPosition]
    ] = field_positions,
) -> tuple[Callable, Callable, Callable, Callable]:
    """Return a ``__exec_sql`` builtin over the connection registry *connections*
    (name → backend).

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

    Each call's first argument is the statement's text. An OPEN's second, when
    present, is its cursor's declaration; every other argument is a VARCHAR
    shape, three at a time. The builtin parses the text (memoised) and
    dispatches by kind via ``_HANDLERS``.

    Returns four builtins, all sharing the standard RedDragon signature
    (``(args: list[TypedValue], vm: VMState) -> BuiltinResult``) and the same
    per-run session state: ``__exec_sql`` itself, then the three
    unit-of-work hooks a composer hands to a CICS runtime —
    ``reset_session`` (task end: commit + close cursors),
    ``syncpoint`` (commit only, cursors stay open — see ``_syncpoint``), and
    ``rollback`` (roll back + close cursors).
    """
    ctx = _Ctx(
        connections=connections,
        conn=_ConnState(current=initial_connector.connect(connections)),
        open_cursors=set(),
        field_meta={},
        declaration=_Undeclared(),
        layout={},
        layouts=_Layouts(layout_of, {}),
        tolerant=tolerant,
    )

    def __exec_sql(args: Sequence[TypedValue], vm) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        values = [str(a.value) for a in args]
        parsed = _parsed(values[0])
        call = replace(
            _call_context(ctx, parsed, values[1:]),
            layout=ctx.layouts.of(vm.declarations),
        )
        _HANDLERS.get(parsed.kind, _h_query)(call, parsed, vm)
        return BuiltinResult(value=None)

    return (
        __exec_sql,
        _make_uow_builtin(ctx, _reset_session),
        _make_uow_builtin(ctx, _syncpoint),
        _make_uow_builtin(ctx, _rollback_uow),
    )
