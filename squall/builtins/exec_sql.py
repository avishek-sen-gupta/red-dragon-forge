"""
squall.builtins.exec_sql
~~~~~~~~~~~~~~~~~~~~~~~~
Factory for the ``__exec_sql`` builtin — the single dispatch point for all
EXEC SQL … END-EXEC statements in slice 1.

Design
------
* ``make_exec_sql_builtin`` closes over a ``SqlBackend`` and returns a
  callable with the RedDragon builtin signature ``(args, vm) -> BuiltinResult``.
* The single argument is the ``ParsedSql`` plan produced ONCE at lowering time
  (``squall.strategy.SqlLoweringStrategy.lower``). The builtin does **no
  parsing** at run time — it only binds host vars and executes the plan, so a
  statement in a PERFORM loop is parsed once, not on every pass.
* The function is pure given a fixed backend; the backend carries the one
  mutable boundary (the DB connection).
* Dispatch:
    - ``select_into``: bind inputs, execute, write outputs, write SQLCODE.
    - DML kinds with a non-empty query (insert/update/delete/…): execute + write SQLCODE.
    - Cursor kinds (declare_cursor/open_/fetch/close): driven through the
      backend's cursor surface via a per-run cursor registry.
    - Connection / declare-section directives: no-op with SQLCODE 0.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from squall.backend import SqlBackend
from squall.binding import read_params, write_outputs, write_sqlcode

if TYPE_CHECKING:
    from interpreter.vm.vm_types import BuiltinResult

# Directives that are precompiler/runtime bookkeeping with no effect on an
# injected backend: connection management and the host-var declare-section
# bookends. They no-op with SQLCODE 0 — the backend connection is pre-established
# (squall is handed a SqlBackend), and DECLARE SECTION is purely declarative.
_NO_OP_KINDS = frozenset(
    {"connect", "disconnect", "set_connection", "begin_declare", "end_declare"}
)


def _host_names(host_vars) -> tuple[str, ...]:
    """The host-var names, in order — the form read_params/write_outputs expect."""
    return tuple(hv.name for hv in host_vars)


def _bind_row(vm, out_vars, result, field_meta: Mapping[str, dict]) -> int:
    """Bind *result*'s first row into *out_vars*; return the resulting SQLCODE.

    A no-row result leaves the host vars untouched and reports ``result.sqlcode``
    (0 / 100). On a strict-coercion failure ``write_outputs`` writes nothing and
    returns the failure code, which overrides the otherwise-successful SQLCODE.
    """
    if not result.rows:
        return result.sqlcode
    status = write_outputs(vm, _host_names(out_vars), result.rows[0], field_meta)
    return status if status != 0 else result.sqlcode


@dataclass(frozen=True)
class _Ctx:
    """The per-run handler context: the backend, the cursor registry (mutated in
    place across DECLARE→OPEN→FETCH→CLOSE), and the dclgen field metadata."""

    backend: SqlBackend
    cursors: dict
    field_meta: Mapping[str, dict]


def _h_noop(_ctx: _Ctx, _parsed, vm) -> None:
    # Connection / declare-section directives have no DB effect.
    write_sqlcode(vm, 0)


def _h_declare_cursor(ctx: _Ctx, parsed, vm) -> None:
    # Declaration only — remember the SELECT + its host vars for OPEN.
    ctx.cursors[parsed.cursor] = parsed
    write_sqlcode(vm, 0)


def _h_open(ctx: _Ctx, parsed, vm) -> None:
    decl = ctx.cursors.get(parsed.cursor)
    if decl is None:
        write_sqlcode(vm, -1)  # cursor not declared
        return
    # Host vars are captured at OPEN: OPEN ... USING overrides, else the cursor
    # SELECT's own host vars.
    params = read_params(
        vm, _host_names(parsed.in_vars or decl.in_vars), ctx.field_meta
    )
    ctx.backend.open_cursor(parsed.cursor, decl.query, params)
    write_sqlcode(vm, 0)


def _h_fetch(ctx: _Ctx, parsed, vm) -> None:
    result = ctx.backend.fetch(parsed.cursor)
    write_sqlcode(vm, _bind_row(vm, parsed.out_vars, result, ctx.field_meta))


def _h_close(ctx: _Ctx, parsed, vm) -> None:
    ctx.backend.close(parsed.cursor)
    write_sqlcode(vm, 0)


def _h_commit(ctx: _Ctx, _parsed, vm) -> None:
    ctx.backend.commit()
    write_sqlcode(vm, 0)


def _h_rollback(ctx: _Ctx, _parsed, vm) -> None:
    ctx.backend.rollback()
    write_sqlcode(vm, 0)


def _h_query(ctx: _Ctx, parsed, vm) -> None:
    # All remaining kinds carry a non-empty query string.
    params = read_params(vm, _host_names(parsed.in_vars), ctx.field_meta)
    result = ctx.backend.execute(parsed.query, params)
    code = (
        _bind_row(vm, parsed.out_vars, result, ctx.field_meta)
        if parsed.kind == "select_into"
        else result.sqlcode
    )
    write_sqlcode(vm, code)


# Dispatch table: EXEC SQL kind -> handler. Kinds with a non-empty query
# (select_into / insert / update / delete / …) fall to _h_query (the default).
_HANDLERS = {
    "declare_cursor": _h_declare_cursor,
    "open_": _h_open,
    "fetch": _h_fetch,
    "close": _h_close,
    "commit": _h_commit,
    "rollback": _h_rollback,
    **{kind: _h_noop for kind in _NO_OP_KINDS},
}


def make_exec_sql_builtin(
    backend: SqlBackend, plans: list, field_meta: Mapping[str, dict]
) -> Callable:
    """Return a ``__exec_sql`` builtin over *backend*, the plan pool, and the dclgen
    *field_meta* map (loaded once by the prepass, shared by reference).

    *plans* is the lowering-time constant pool of ``ParsedSql`` objects
    (``SqlLoweringStrategy._plans``). Each call site passes its plan's pool index
    as the single argument; the builtin resolves it and dispatches by kind via
    ``_HANDLERS`` — it never parses at run time.

    The returned callable has the standard RedDragon builtin signature:
    ``(args: list[TypedValue], vm: VMState) -> BuiltinResult``.
    """
    # One cursor registry per run (DECLARE records, OPEN reads).
    ctx = _Ctx(backend=backend, cursors={}, field_meta=field_meta)

    def __exec_sql(args: list, vm: object) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        parsed = plans[int(args[0].value)]
        _HANDLERS.get(parsed.kind, _h_query)(ctx, parsed, vm)
        return BuiltinResult(value=None)

    return __exec_sql
