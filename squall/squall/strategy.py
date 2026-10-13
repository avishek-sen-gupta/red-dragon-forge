"""
squall.strategy
~~~~~~~~~~~~~~~
``SqlLoweringStrategy`` — the injectable extension-lowering strategy for
EXEC SQL … END-EXEC statements in the RedDragon COBOL frontend.

Implements ``RedDragonExtensionLoweringStrategy`` (match the protocol
signatures exactly).  Registered as an element of the
``CobolFrontend.extension_strategies`` array.

* Every executable ``ExecSqlStatement`` lowers to one ``__exec_sql`` call that
  carries everything the builtin needs: the statement's text, an OPEN's cursor
  declaration, and the VARCHAR shapes of the host variables it binds. A
  lowered program needs nothing from the lowering to run.
* ``DECLARE CURSOR`` is declarative: it lowers to nothing, and its text travels
  on the OPEN. WORKING-STORAGE declarations come from the raw bridge JSON
  (``squall.data_division_exec_sql``); VARCHAR groups from the program's DATA
  DIVISION (``squall.dclgen_meta``). Both are per program.
* The ``__exec_sql`` builtin (registered in ``Builtins.TABLE`` at
  construction) handles per-kind dispatch.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from squall.backend import SqlBackend
from squall.binding import varchar_children
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.connector import DbConnector, NullDbConnector
from squall.data_division_exec_sql import derive_cursors
from squall.dclgen_meta import derive_field_meta
from squall.parser.sql_model import (
    GoTo,
    HostVar,
    Kind,
    NamedCursor,
    ParsedSql,
    WheneverAction,
    WheneverCondition,
)
from squall.program_scope import ProgramScope
from squall.strategy_stores import register

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

# A module-level singleton rather than a call in the constructor's own default
# — B008: a fresh NullDbConnector() is stateless, so every SqlLoweringStrategy
# that doesn't pass its own can safely share this one instance.
_NO_CONNECTOR: DbConnector = NullDbConnector()


class SqlLoweringStrategy:
    """Full SQL lowering strategy.  Inject at ``CobolFrontend`` construction."""

    name = "sql"

    def __init__(
        self,
        connections: Mapping[str, SqlBackend],
        initial_connector: DbConnector = _NO_CONNECTOR,
        *,
        tolerant: bool = False,
    ) -> None:
        # The connection registry (name → backend). A run starts disconnected;
        # the program's EXEC SQL CONNECT selects from this registry at run time.
        # Unless initial_connector resolves an entry that is already current —
        # modelling a CICS Db2-attached program, which is handed a live thread
        # by the attachment facility and never issues EXEC SQL CONNECT itself.
        self._connections = connections
        # WHENEVER directive state: condition -> action. Updated in textual order
        # as `lower` sees each WHENEVER statement (precompiler scoping). A stored
        # Continue/NoOpAction disables a previously-active branch (the emit loop
        # no-ops on them).
        self._whenever: dict[WheneverCondition, WheneverAction] = {}
        # The program being lowered; preprocess_program_dict starts a new one.
        self._scope = ProgramScope()
        exec_sql_fn, reset_session_fn, syncpoint_fn, rollback_fn = (
            make_exec_sql_builtin(
                connections, initial_connector=initial_connector, tolerant=tolerant
            )
        )
        self._register_builtins(
            exec_sql_fn, reset_session_fn, syncpoint_fn, rollback_fn
        )

    def _register_builtins(
        self, exec_sql_fn, reset_session_fn, syncpoint_fn, rollback_fn
    ) -> None:
        """Register ``__exec_sql`` plus the three generic, CICS-owned
        extension points (see cicada's CicsLoweringStrategy): cicada calls
        these with no idea what, if anything, is registered under them — the
        same name-convention-only composition __exec_sql itself uses, so
        neither package imports the other. __cics_task_end_hook fires at
        every task end (EXEC CICS RETURN, with or without TRANSID) and resets
        the session (commit + close every cursor). __cics_syncpoint_hook
        fires at EXEC CICS SYNCPOINT and commits WITHOUT closing cursors (see
        ``_syncpoint``'s docstring for the ruling). __cics_rollback_hook
        fires at EXEC CICS SYNCPOINT ROLLBACK, and — via a composed on_abend
        callable cicada never names — when a task abends: it rolls back and
        closes every cursor.
        """
        register(_BUILTIN_NAME, exec_sql_fn)
        register("__cics_task_end_hook", reset_session_fn)
        register("__cics_syncpoint_hook", syncpoint_fn)
        register("__cics_rollback_hook", rollback_fn)

    # ── Protocol methods ──────────────────────────────────────────────────────

    def handles(self, stmt: object) -> bool:
        from squall.statements import ExecSqlStatement

        return isinstance(stmt, ExecSqlStatement)

    def preprocess_program_dict(self, data: dict) -> dict:  # type: ignore[type-arg]
        """Start a program: its WORKING-STORAGE cursor declarations and its
        inferred VARCHAR groups, both for this program only. *data* itself is
        returned unchanged."""
        self._scope = ProgramScope(
            declarations=derive_cursors(data),
            varchar={
                name.upper(): meta for name, meta in derive_field_meta(data).items()
            },
        )
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
        stmt: object,
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """Lower one ``ExecSqlStatement``.

        WHENEVER is a compile-time directive: it updates per-condition state and
        emits no runtime IR. Every other kind lowers to a ``__exec_sql`` call,
        followed by the synthetic ``IF SQLCODE <cmp> <val> GO TO <target>`` for
        each active (non-CONTINUE) condition.
        """
        from squall.statements import ExecSqlStatement

        # The frontend only ever calls lower() for a stmt handles() accepted
        # (isinstance ExecSqlStatement) -- narrow the protocol's `object` back
        # to that concrete type; a cast, not a runtime check, since a mismatch
        # here is a frontend dispatch bug, not a condition to defend against.
        exec_sql_stmt = cast(ExecSqlStatement, stmt)

        if exec_sql_stmt.whenever_condition is not WheneverCondition.NONE:
            # Precompiler directive: record the (condition -> action) and emit no
            # IR. A Continue/NoOpAction simply overrides any active GoTo so the
            # emit loop stops branching for that condition. Already parsed at ASG
            # construction, so the grammar does not run again here.
            self._whenever[exec_sql_stmt.whenever_condition] = (
                exec_sql_stmt.whenever_action
            )
            return

        self._lower_statement(ctx, exec_sql_stmt.text, materialised)

    def _lower_statement(
        self, ctx: EmitContext, text: str, materialised: MaterialisedSectionedLayout
    ) -> None:
        """A DECLARE CURSOR is remembered for its OPENs and emits nothing; every
        other statement becomes a self-contained ``__exec_sql`` call."""
        from squall.parser.parse import parse_exec_sql

        plan = parse_exec_sql(text)
        match plan.kind, plan.cursor:
            case Kind.DECLARE_CURSOR, NamedCursor(name=declared):
                self._scope = self._scope.declaring(declared.upper(), text)
            case Kind.OPEN, NamedCursor(name=opened):
                self._emit_call(
                    ctx, self._open_values(text, plan, opened), materialised
                )
            case _:
                self._emit_call(
                    ctx,
                    (text, *self._shapes((*plan.in_vars, *plan.out_vars))),
                    materialised,
                )

    def _open_values(self, text: str, plan: ParsedSql, cursor: str) -> tuple[str, ...]:
        """An OPEN's call: its text, then -- when the program declares the cursor
        (names compare upper-cased, as Db2 folds them) -- its declaration and the
        shapes of the host variables it binds, its own USING list or else the
        declaration's."""
        from squall.parser.parse import parse_exec_sql

        match self._scope.declarations.get(cursor.upper()):
            case None:
                return (text,)
            case declaration:
                bound = plan.in_vars or parse_exec_sql(declaration).in_vars
                return (text, declaration, *self._shapes(bound))

    def _emit_call(
        self,
        ctx: EmitContext,
        values: tuple[str, ...],
        materialised: MaterialisedSectionedLayout,
    ) -> None:
        """The ``__exec_sql`` call, then the SQLCODE branch of each active WHENEVER."""
        self._emit_exec_sql_call(ctx, values)
        self._emit_whenever_checks(ctx, materialised)

    def _shapes(self, host_vars: Sequence[HostVar]) -> tuple[str, ...]:
        """(group, length child, text child) for each bound VARCHAR group."""
        return tuple(
            part
            for hv in host_vars
            if hv.name.upper() in self._scope.varchar
            for part in (
                hv.name,
                *varchar_children(self._scope.varchar[hv.name.upper()]),
            )
        )

    def _emit_exec_sql_call(self, ctx: EmitContext, values: tuple[str, ...]) -> None:
        """Emit one ``Const`` per call-site value, then ``__exec_sql`` over them."""
        from interpreter.func_name import FuncName
        from interpreter.instructions import CallFunction, Const
        from interpreter.types.type_expr import UNKNOWN

        regs = tuple(ctx.fresh_reg() for _ in values)
        for reg, value in zip(regs, values, strict=True):
            ctx.emit_inst(Const(result_reg=reg, value=value, type_expr=UNKNOWN))
        ctx.emit_inst(
            CallFunction(
                result_reg=ctx.fresh_reg(),
                func_name=FuncName(_BUILTIN_NAME),
                args=regs,
            )
        )

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
        for condition, target in self._active_goto_targets():
            ctx.lower_statement(_sqlcode_if_stmt(condition, target), materialised)

    def _active_goto_targets(self) -> tuple[tuple[WheneverCondition, str], ...]:
        """The (condition, target) pairs with an active ``GoTo`` whose
        condition has a synthesizable SQLCODE relation. SQLWARNING / custom
        conditions (deferred — slice 3) and ``Continue``/``NoOpAction``
        actions contribute none."""
        return tuple(
            (condition, action.target)
            for condition, action in self._whenever.items()
            if isinstance(action, GoTo) and condition in _WHENEVER_RELATION
        )


def _sqlcode_if_stmt(condition: WheneverCondition, target: str):
    """The synthetic ``IF SQLCODE <cmp> <val> GO TO <target>`` statement dict
    for one active WHENEVER GoTo, parsed via ``cobol_asg.parse_statement``."""
    from cobol_asg.cobol_statements import parse_statement

    op, value = _WHENEVER_RELATION[condition]
    return parse_statement(
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
            "children": [
                {
                    "type": "GOTO",
                    "form": "simple",
                    "target": {"paragraph": target, "section": ""},
                }
            ],
        }
    )
