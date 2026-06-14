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
* Slice-1 scope:
    - ``select_into``: bind inputs, execute, write outputs, write SQLCODE.
    - DML kinds with a non-empty query (insert/update/delete/…): execute + write SQLCODE.
    - No-query cursor kinds (fetch/open_/close): raise ``NotImplementedError``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from squall.backend import SqlBackend
from squall.binding import read_params, write_outputs, write_sqlcode

if TYPE_CHECKING:
    from interpreter.vm.vm_types import BuiltinResult

# Cursor kinds whose query string is empty — not implemented in slice 1.
_NO_QUERY_CURSOR_KINDS = frozenset({"fetch", "open_", "close"})

# Directives that are precompiler/runtime bookkeeping with no effect on an
# injected backend: connection management and the host-var declare-section
# bookends. They no-op with SQLCODE 0 — the backend connection is pre-established
# (squall is handed a SqlBackend), and DECLARE SECTION is purely declarative.
_NO_OP_KINDS = frozenset(
    {"connect", "disconnect", "set_connection", "begin_declare", "end_declare"}
)


def make_exec_sql_builtin(backend: SqlBackend, plans: list) -> Callable:  # type: ignore[type-arg]
    """Return a ``__exec_sql`` builtin closing over *backend* and the plan pool.

    *plans* is the lowering-time constant pool of ``ParsedSql`` objects
    (``SqlLoweringStrategy._plans``). Each call site passes its plan's pool index
    as the single argument; the builtin resolves it and executes — it never
    parses at run time.

    The returned callable has the standard RedDragon builtin signature:
    ``(args: list[TypedValue], vm: VMState) -> BuiltinResult``.
    """

    def __exec_sql(args: list, vm: object) -> "BuiltinResult":  # type: ignore[type-arg]
        from interpreter.vm.vm_types import BuiltinResult  # noqa: PLC0415

        # args[0] wraps the constant-pool INDEX of the plan parsed ONCE at
        # lowering time (squall.strategy.SqlLoweringStrategy.lower). No parsing
        # happens here — the builtin only binds host vars and executes.
        raw_arg = args[0]
        index = raw_arg.value if hasattr(raw_arg, "value") else raw_arg
        parsed = plans[int(index)]

        # Connection / declare-section directives have no DB effect — no-op.
        if parsed.kind in _NO_OP_KINDS:
            write_sqlcode(vm, 0)  # type: ignore[arg-type]
            return BuiltinResult(value=None)

        # Raise early for no-query cursor kinds (slice-1 not-yet-supported).
        if parsed.kind in _NO_QUERY_CURSOR_KINDS:
            raise NotImplementedError(
                f"squall slice 1: {parsed.kind} not yet supported"
            )

        # All remaining kinds have a non-empty query string.
        in_names = tuple(hv.name for hv in parsed.in_vars)
        params = read_params(vm, in_names)  # type: ignore[arg-type]
        result = backend.execute(parsed.query, params)

        if parsed.kind == "select_into" and result.rows:
            out_names = tuple(hv.name for hv in parsed.out_vars)
            # Strict coercion: if any value can't be assigned to its host var,
            # nothing is written and the statement fails with that SQLCODE
            # (overriding the otherwise-successful 0).
            status = write_outputs(vm, out_names, result.rows[0])  # type: ignore[arg-type]
            if status != 0:
                write_sqlcode(vm, status)  # type: ignore[arg-type]
                return BuiltinResult(value=None)

        write_sqlcode(vm, result.sqlcode)  # type: ignore[arg-type]

        return BuiltinResult(value=None)

    return __exec_sql
