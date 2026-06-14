"""
squall.builtins.exec_sql
~~~~~~~~~~~~~~~~~~~~~~~~
Factory for the ``__exec_sql`` builtin — the single dispatch point for all
EXEC SQL … END-EXEC statements in slice 1.

Design
------
* ``make_exec_sql_builtin`` closes over a ``SqlBackend`` and returns a
  callable with the RedDragon builtin signature ``(args, vm) -> BuiltinResult``.
* The function is pure given a fixed backend; the backend carries the one
  mutable boundary (the DB connection).
* Slice-1 scope:
    - ``select_into``: parse, bind inputs, execute, write outputs, write SQLCODE.
    - DML kinds with a non-empty query (insert/update/delete/…): execute + write SQLCODE.
    - No-query cursor kinds (fetch/open_/close): raise ``NotImplementedError``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from squall.backend import SqlBackend
from squall.binding import read_params, write_outputs, write_sqlcode
from squall.parser.parse import parse_exec_sql

if TYPE_CHECKING:
    from interpreter.vm.vm_types import BuiltinResult

# Cursor kinds whose query string is empty — not implemented in slice 1.
_NO_QUERY_CURSOR_KINDS = frozenset({"fetch", "open_", "close"})


def make_exec_sql_builtin(backend: SqlBackend) -> Callable:  # type: ignore[type-arg]
    """Return a ``__exec_sql`` builtin closing over *backend*.

    The returned callable has the standard RedDragon builtin signature:
    ``(args: list[TypedValue], vm: VMState) -> BuiltinResult``.
    """

    def __exec_sql(args: list, vm: object) -> "BuiltinResult":  # type: ignore[type-arg]
        from interpreter.vm.vm_types import BuiltinResult  # noqa: PLC0415

        # args[0] is a TypedValue wrapping the raw EXEC SQL … END-EXEC text.
        raw_arg = args[0]
        text: str = raw_arg.value if hasattr(raw_arg, "value") else raw_arg

        parsed = parse_exec_sql(text)

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
            write_outputs(vm, out_names, result.rows[0])  # type: ignore[arg-type]

        write_sqlcode(vm, result.sqlcode)  # type: ignore[arg-type]

        return BuiltinResult(value=None)

    return __exec_sql
