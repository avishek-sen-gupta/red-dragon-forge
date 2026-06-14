"""
squall.strategy
~~~~~~~~~~~~~~~
``SqlLoweringStrategy`` — the injectable extension-lowering strategy for
EXEC SQL … END-EXEC statements in the RedDragon COBOL frontend.

Implements ``RedDragonExtensionLoweringStrategy`` (match the protocol
signatures exactly).  Registered as an element of the
``CobolFrontend.extension_strategies`` array.

Slice-1 scope:
* All ``ExecSqlStatement`` nodes are lowered to a single
  ``CallFunction("__exec_sql", [<verbatim-text const>])`` call.
* The ``__exec_sql`` builtin (registered in ``Builtins.TABLE`` at
  construction) handles per-kind dispatch.
* ``on_procedure_entry`` and ``preprocess_program_dict`` are no-ops.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from squall.backend import SqlBackend
from squall.builtins.exec_sql import make_exec_sql_builtin

if TYPE_CHECKING:
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout

logger = logging.getLogger(__name__)

_BUILTIN_NAME = "__exec_sql"


def _register(table: dict, name: str, fn: object) -> None:  # type: ignore[type-arg]
    """Insert *fn* into *table* under ``FuncName(name)``."""
    from interpreter.func_name import FuncName  # noqa: PLC0415

    key = FuncName(name)
    if key in table:
        logger.warning(
            "Builtins.TABLE already contains %s — overwriting.", key
        )
    table[key] = fn


class SqlLoweringStrategy:
    """Full SQL lowering strategy.  Inject at ``CobolFrontend`` construction."""

    def __init__(self, backend: SqlBackend) -> None:
        from interpreter.vm.builtins import Builtins  # noqa: PLC0415

        self._backend = backend
        _register(Builtins.TABLE, _BUILTIN_NAME, make_exec_sql_builtin(backend))

    # ── Protocol methods ──────────────────────────────────────────────────────

    def handles(self, stmt: Any) -> bool:
        from interpreter.cobol.cobol_statements import ExecSqlStatement  # noqa: PLC0415

        return isinstance(stmt, ExecSqlStatement)

    def preprocess_program_dict(self, data: dict) -> dict:  # type: ignore[type-arg]
        """No-op for slice 1 — return *data* unchanged."""
        return data

    def on_procedure_entry(
        self,
        ctx: "EmitContext",
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        """No-op for slice 1 — SQL needs no per-procedure prologue."""

    def lower(
        self,
        ctx: "EmitContext",
        stmt: Any,
        materialised: "MaterialisedSectionedLayout",
    ) -> None:
        """Lower one ``ExecSqlStatement`` to a ``CallFunction(__exec_sql, …)``."""
        from interpreter.func_name import FuncName  # noqa: PLC0415
        from interpreter.instructions import CallFunction, Const  # noqa: PLC0415

        # Load the verbatim EXEC SQL … END-EXEC text into a fresh register.
        text_reg = ctx.fresh_reg()
        ctx.emit_inst(Const(result_reg=text_reg, value=stmt.text))

        # Emit the call; the builtin reads the text and drives execution.
        result_reg = ctx.fresh_reg()
        ctx.emit_inst(
            CallFunction(
                result_reg=result_reg,
                func_name=FuncName(_BUILTIN_NAME),
                args=(text_reg,),
            )
        )
