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
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from squall.backend import SqlBackend
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.parser.sql_model import (
    FieldMeta,
    GoTo,
    Kind,
    ParsedSql,
    WheneverAction,
    WheneverCondition,
)

if TYPE_CHECKING:
    from interpreter.cobol.emit_context import EmitContext
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout

logger = logging.getLogger(__name__)

_BUILTIN_NAME = "__exec_sql"

# WHENEVER condition -> (COBOL comparison op, literal) for the synthetic check.
# SQLWARNING is omitted: it needs SQLCA SQLWARN populated (squall-ud0).
_WHENEVER_RELATION: dict[WheneverCondition, tuple[str, str]] = {
    WheneverCondition.SQLERROR: ("<", "0"),
    WheneverCondition.NOT_FOUND: ("=", "100"),
}


def _register(table: dict, name: str, fn: object) -> None:  # type: ignore[type-arg]
    """Insert *fn* into *table* under ``FuncName(name)``."""
    from interpreter.func_name import FuncName

    key = FuncName(name)
    if key in table:
        logger.warning("Builtins.TABLE already contains %s — overwriting.", key)
    table[key] = fn


class SqlLoweringStrategy:
    """Full SQL lowering strategy.  Inject at ``CobolFrontend`` construction."""

    def __init__(
        self,
        connections: Mapping[str, SqlBackend],
        field_meta: Mapping[str, FieldMeta],
    ) -> None:
        from interpreter.vm.builtins import Builtins

        # The connection registry (name → backend). A run starts disconnected;
        # the program's EXEC SQL CONNECT selects from this registry at run time.
        self._connections = connections
        # dclgen host-var metadata, loaded once by the prepass and passed in by
        # reference. The builtin (and the binding engine it calls) consult it to
        # drive VARCHAR 49-group codecs and typed validation.
        self._field_meta = field_meta
        # WHENEVER directive state: condition -> action. Updated in textual order
        # as `lower` sees each WHENEVER statement (precompiler scoping). A stored
        # Continue/NoOpAction disables a previously-active branch (the emit loop
        # no-ops on them).
        self._whenever: dict[WheneverCondition, WheneverAction] = {}
        # Constant pool of plans parsed at lowering time. Each EXEC SQL site is
        # lowered to a Const carrying its index here; the builtin closes over the
        # same list and looks the plan up at run time. Plans never travel through
        # the IR as objects (the VM's Const handling only round-trips primitives).
        self._plans: list[ParsedSql] = []
        _register(
            Builtins.TABLE,
            _BUILTIN_NAME,
            make_exec_sql_builtin(connections, self._plans, field_meta),
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
        """Lower one ``ExecSqlStatement``.

        WHENEVER is a compile-time directive: it updates per-condition state and
        emits no runtime IR. Every other kind lowers to a ``__exec_sql`` call,
        followed by the synthetic ``IF SQLCODE <cmp> <val> GO TO <target>`` for
        each active (non-CONTINUE) condition.
        """
        from interpreter.func_name import FuncName
        from interpreter.instructions import CallFunction, Const

        from squall.parser.parse import parse_exec_sql

        # Parse the directive ONCE, here at lowering time. The statement is
        # static, so the Lark parse must not run at execution time (it would
        # re-parse on every pass through a PERFORM loop). The runtime builtin
        # receives the already-parsed ParsedSql plan and only binds + executes.
        plan = parse_exec_sql(stmt.text)

        if plan.kind is Kind.WHENEVER:
            # Precompiler directive: record the (condition -> action) and emit no
            # IR. A Continue/NoOpAction simply overrides any active GoTo so the
            # emit loop stops branching for that condition.
            self._whenever[plan.whenever_condition] = plan.whenever_action
            return

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

        # Automatic SQLCODE branching for each active WHENEVER condition.
        self._emit_whenever_checks(ctx, materialised)

    def _emit_whenever_checks(
        self,
        ctx: EmitContext,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """Emit ``IF SQLCODE <cmp> <val> GO TO target`` for each active condition.

        Built as a synthetic COBOL IF and lowered through ``ctx.lower_statement``
        so RedDragon's native IF + GO TO lowering (condition + label resolution)
        is reused — no raw-IR branch emission, no coupling to label naming.
        """
        from interpreter.cobol.cobol_statements import parse_statement

        for condition, action in self._whenever.items():
            match action:
                case GoTo(target):
                    if condition not in _WHENEVER_RELATION:
                        continue  # SQLWARNING / custom conditions deferred — slice 3
                    op, value = _WHENEVER_RELATION[condition]
                    if_stmt = parse_statement(
                        {
                            "type": "IF",
                            "condition": {
                                "not": False,
                                "relation": {
                                    "left": {"kind": "ref", "name": "SQLCODE"},
                                    "op": op,
                                    "right": {"kind": "lit", "value": value},
                                },
                            },
                            "children": [{"type": "GOTO", "operands": [target]}],
                        }
                    )
                    ctx.lower_statement(if_stmt, materialised)
                case _:  # Continue, NoOpAction
                    pass
