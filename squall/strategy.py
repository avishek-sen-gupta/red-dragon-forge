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
    from interpreter.func_name import FuncName

    key = FuncName(name)
    if key in table:
        logger.warning("Builtins.TABLE already contains %s — overwriting.", key)
    table[key] = fn


class SqlLoweringStrategy:
    """Full SQL lowering strategy.  Inject at ``CobolFrontend`` construction."""

    def __init__(self, backend: SqlBackend) -> None:
        from interpreter.vm.builtins import Builtins

        self._backend = backend
        # Constant pool of plans parsed at lowering time. Each EXEC SQL site is
        # lowered to a Const carrying its index here; the builtin closes over the
        # same list and looks the plan up at run time. Plans never travel through
        # the IR as objects (the VM's Const handling only round-trips primitives).
        self._plans: list = []
        _register(
            Builtins.TABLE, _BUILTIN_NAME, make_exec_sql_builtin(backend, self._plans)
        )

    # ── Protocol methods ──────────────────────────────────────────────────────

    def handles(self, stmt: Any) -> bool:
        from interpreter.cobol.cobol_statements import ExecSqlStatement

        return isinstance(stmt, ExecSqlStatement)

    def preprocess_program_dict(self, data: dict) -> dict:  # type: ignore[type-arg]
        """No-op for slice 1 — return *data* unchanged."""
        return data

    def on_procedure_entry(
        self,
        ctx: EmitContext,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """No-op for slice 1 — SQL needs no per-procedure prologue."""

    def lower(
        self,
        ctx: EmitContext,
        stmt: Any,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """Lower one ``ExecSqlStatement`` to a ``CallFunction(__exec_sql, …)``."""
        from interpreter.func_name import FuncName
        from interpreter.instructions import CallFunction, Const

        from squall.parser.parse import parse_exec_sql

        # Parse the directive ONCE, here at lowering time. The statement is
        # static, so the Lark parse must not run at execution time (it would
        # re-parse on every pass through a PERFORM loop). The runtime builtin
        # receives the already-parsed ParsedSql plan and only binds + executes.
        plan = parse_exec_sql(stmt.text)
        plan_index = len(self._plans)
        self._plans.append(plan)

        # Carry only the plan's pool index through the IR (a primitive the VM's
        # Const handling round-trips cleanly); the builtin resolves it to the plan.
        index_reg = ctx.fresh_reg()
        ctx.emit_inst(Const(result_reg=index_reg, value=plan_index))

        # Emit the call; the builtin looks up the parsed plan and drives execution.
        result_reg = ctx.fresh_reg()
        ctx.emit_inst(
            CallFunction(
                result_reg=result_reg,
                func_name=FuncName(_BUILTIN_NAME),
                args=(index_reg,),
            )
        )
