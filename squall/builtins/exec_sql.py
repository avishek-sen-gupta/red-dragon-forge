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
from typing import TYPE_CHECKING

from squall.backend import SqlBackend
from squall.binding import _NO_META, read_params, write_outputs, write_sqlcode

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


def make_exec_sql_builtin(
    backend: SqlBackend, plans: list, field_meta: Mapping[str, dict] = _NO_META
) -> Callable:
    """Return a ``__exec_sql`` builtin closing over *backend*, the plan pool, and
    the dclgen *field_meta* map (loaded once by the prepass, shared by reference).

    *plans* is the lowering-time constant pool of ``ParsedSql`` objects
    (``SqlLoweringStrategy._plans``). Each call site passes its plan's pool index
    as the single argument; the builtin resolves it and dispatches by kind — it
    never parses at run time.

    The returned callable has the standard RedDragon builtin signature:
    ``(args: list[TypedValue], vm: VMState) -> BuiltinResult``.
    """

    # Runtime cursor registry: cursor name -> the declared ParsedSql (its SELECT
    # + input host vars). DECLARE records it; OPEN reads it. One run, one builtin.
    cursors: dict = {}

    def _no_op(_parsed, vm) -> None:
        # Connection / declare-section directives have no DB effect.
        write_sqlcode(vm, 0)

    def _declare_cursor(parsed, vm) -> None:
        # Declaration only — remember the SELECT + its host vars for OPEN.
        cursors[parsed.cursor] = parsed
        write_sqlcode(vm, 0)

    def _open(parsed, vm) -> None:
        decl = cursors.get(parsed.cursor)
        if decl is None:
            write_sqlcode(vm, -1)  # cursor not declared
            return
        # Host vars are captured at OPEN: OPEN ... USING overrides, else the
        # cursor SELECT's own host vars.
        params = read_params(
            vm, _host_names(parsed.in_vars or decl.in_vars), field_meta
        )
        backend.open_cursor(parsed.cursor, decl.query, params)
        write_sqlcode(vm, 0)

    def _fetch(parsed, vm) -> None:
        result = backend.fetch(parsed.cursor)
        write_sqlcode(vm, _bind_row(vm, parsed.out_vars, result, field_meta))

    def _close(parsed, vm) -> None:
        backend.close(parsed.cursor)
        write_sqlcode(vm, 0)

    def _query(parsed, vm) -> None:
        # All remaining kinds carry a non-empty query string.
        params = read_params(vm, _host_names(parsed.in_vars), field_meta)
        result = backend.execute(parsed.query, params)
        code = (
            _bind_row(vm, parsed.out_vars, result, field_meta)
            if parsed.kind == "select_into"
            else result.sqlcode
        )
        write_sqlcode(vm, code)

    handlers: dict = {
        "declare_cursor": _declare_cursor,
        "open_": _open,
        "fetch": _fetch,
        "close": _close,
        **{kind: _no_op for kind in _NO_OP_KINDS},
    }

    def __exec_sql(args: list, vm: object) -> BuiltinResult:
        from interpreter.vm.vm_types import BuiltinResult

        # args[0] wraps the constant-pool INDEX of the plan parsed ONCE at lowering
        # time. No parsing here — resolve the plan and dispatch by kind; kinds with
        # a non-empty query (select_into / insert / update / …) fall to _query.
        parsed = plans[int(args[0].value)]
        handlers.get(parsed.kind, _query)(parsed, vm)
        return BuiltinResult(value=None)

    return __exec_sql
