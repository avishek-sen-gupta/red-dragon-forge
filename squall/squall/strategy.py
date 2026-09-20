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
* ``on_procedure_entry`` is a no-op. ``preprocess_program_dict`` derives
  DCLGEN VARCHAR ``field_meta`` from the raw bridge JSON (see
  ``squall.dclgen_meta``) and merges it into the live ``field_meta`` view
  already handed to the ``__exec_sql`` builtin at construction time.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from squall.backend import SqlBackend
from squall.builtins.exec_sql import make_exec_sql_builtin
from squall.connector import DbConnector, NullDbConnector
from squall.data_division_exec_sql import derive_cursors
from squall.dclgen_meta import derive_field_meta
from squall.parser.sql_model import (
    FieldMeta,
    GoTo,
    Kind,
    ParsedSql,
    WheneverAction,
    WheneverCondition,
)
from squall.strategy_stores import (
    ABSENT,
    Absent,
    SharedSqlStores,
    merge_cursors,
    merge_field_meta,
    register,
)
from squall.strategy_stores import absorb_field_meta as _absorb_field_meta
from squall.strategy_stores import append as _append_plan

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

    def __init__(
        self,
        connections: Mapping[str, SqlBackend],
        field_meta: Mapping[str, FieldMeta],
        initial_connector: DbConnector = _NO_CONNECTOR,
        *,
        tolerant: bool = False,
        stores: SharedSqlStores | Absent = ABSENT,
    ) -> None:
        # The connection registry (name → backend). A run starts disconnected;
        # the program's EXEC SQL CONNECT selects from this registry at run time.
        # Unless initial_connector resolves an entry that is already current —
        # modelling a CICS Db2-attached program, which is handed a live thread
        # by the attachment facility and never issues EXEC SQL CONNECT itself.
        self._connections = connections
        # The three stores below belong to *stores*, not to this instance: a
        # spec serving several SQL programs passes the same SharedSqlStores to
        # every strategy it builds, so the one surviving __exec_sql builtin can
        # still reach every program's plans, cursors and field metadata (see
        # SharedSqlStores for why only one builtin survives). Omitting it gives
        # this strategy private stores -- the single-program behaviour every
        # direct caller has always had.
        self._stores: SharedSqlStores = (
            SharedSqlStores() if isinstance(stores, Absent) else stores
        )
        # dclgen host-var metadata: sidecar entries loaded by the prepass, held
        # in a *mutable* private store wrapped in an immutable, LIVE view. The
        # store starts as a copy of the sidecar-declared *field_meta* passed
        # in -- via the same ``absorb_field_meta`` helper ``build_sql_spec``
        # (coprocessor.py) uses for the shared-store case, so the two paths
        # cannot drift on sidecar-vs-inference precedence. ``preprocess_program_dict``
        # (below) later merges in metadata derived from the raw bridge JSON —
        # a program's own DCLGEN copybooks carry no sidecar at all, so that's
        # often the *only* metadata a VARCHAR host var gets. The builtin is
        # constructed with ``self._field_meta`` (this same view, not a bare
        # copy of *field_meta*) further down, so a later in-place store update
        # reaches it — the builtin is registered before preprocess_program_dict
        # is ever called (see CoprocessorSpec's ordering guarantee), so
        # nothing but a live, shared view can work.
        self._field_meta_store: dict[str, FieldMeta] = self._stores.field_meta
        _absorb_field_meta(
            self._field_meta_store, field_meta, self._stores.sidecar_field_names
        )
        self._field_meta: Mapping[str, FieldMeta] = MappingProxyType(
            self._field_meta_store
        )
        # WHENEVER directive state: condition -> action. Updated in textual order
        # as `lower` sees each WHENEVER statement (precompiler scoping). A stored
        # Continue/NoOpAction disables a previously-active branch (the emit loop
        # no-ops on them).
        self._whenever: dict[WheneverCondition, WheneverAction] = {}
        # Constant pool of plans parsed at lowering time. Each EXEC SQL site is
        # lowered to a Const carrying its index here; the builtin closes over the
        # same list and looks the plan up at run time. Plans never travel through
        # the IR as objects (the VM's Const handling only round-trips primitives).
        self._plans: list[ParsedSql] = self._stores.plans
        # DECLARE CURSOR plans recovered from outside PROCEDURE DIVISION (see
        # squall.data_division_exec_sql) -- a mutable store handed to the
        # builtin below by the SAME object, not a copy, exactly like
        # self._field_meta_store above: preprocess_program_dict populates it
        # after construction, and only a live shared dict lets OPEN see that
        # update (CoprocessorSpec's ordering guarantee: the builtin is built
        # before preprocess_program_dict ever runs).
        self._cursors_store: dict[str, ParsedSql] = self._stores.cursors
        exec_sql_fn, reset_session_fn, syncpoint_fn, rollback_fn = (
            make_exec_sql_builtin(
                connections,
                self._plans,
                self._field_meta,
                initial_connector=initial_connector,
                tolerant=tolerant,
                cursors=self._cursors_store,
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
        """Derive DCLGEN VARCHAR ``field_meta`` and WORKING-STORAGE
        ``DECLARE CURSOR`` plans from *data* (the raw bridge JSON) and merge
        both into their live stores. Sidecar field_meta entries win on
        conflict, since a sidecar is an explicit statement and shape
        recognition is only an inference. *data* itself is returned
        unchanged; this method's effect is entirely the two store side
        effects (see ``squall.strategy_stores`` for why ``merge_field_meta``
        must mutate in place rather than rebind, and the constructor's own
        comment on ``self._cursors_store`` for cursors).
        """
        merge_field_meta(
            self._field_meta_store,
            derive_field_meta(data),
            self._stores.sidecar_field_names,
        )
        merge_cursors(self._cursors_store, derive_cursors(data))
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
        from squall.parser.parse import parse_exec_sql
        from squall.statements import ExecSqlStatement

        # The frontend only ever calls lower() for a stmt handles() accepted
        # (isinstance ExecSqlStatement) -- narrow the protocol's `object` back
        # to that concrete type; a cast, not a runtime check, since a mismatch
        # here is a frontend dispatch bug, not a condition to defend against.
        exec_sql_stmt = cast(ExecSqlStatement, stmt)

        # Parse the directive ONCE, here at lowering time. The statement is
        # static, so the Lark parse must not run at execution time (it would
        # re-parse on every pass through a PERFORM loop). The runtime builtin
        # receives the already-parsed ParsedSql plan and only binds + executes.
        plan = parse_exec_sql(exec_sql_stmt.text)

        if plan.kind is Kind.WHENEVER:
            # Precompiler directive: record the (condition -> action) and emit no
            # IR. A Continue/NoOpAction simply overrides any active GoTo so the
            # emit loop stops branching for that condition.
            self._whenever[plan.whenever_condition] = plan.whenever_action
            return

        # append() (squall.strategy_stores) is the __exec_sql builtin's own
        # closed-over plan pool -- this is the one place lowering writes to it.
        plan_index = _append_plan(self._plans, plan)
        self._emit_exec_sql_call(ctx, plan_index)

        # Automatic SQLCODE branching for each active WHENEVER condition.
        self._emit_whenever_checks(ctx, materialised)

    def _emit_exec_sql_call(self, ctx: EmitContext, plan_index: int) -> None:
        """Emit the ``Const(plan_index)`` + ``CallFunction(__exec_sql)`` pair
        every non-WHENEVER EXEC SQL statement lowers to.

        Carries only the plan's pool index through the IR (a primitive the
        VM's ``Const`` handling round-trips cleanly); the builtin resolves it
        back to the parsed plan at run time.
        """
        from interpreter.func_name import FuncName
        from interpreter.instructions import CallFunction, Const
        from interpreter.types.type_expr import UNKNOWN

        index_reg = ctx.fresh_reg()
        ctx.emit_inst(Const(result_reg=index_reg, value=plan_index, type_expr=UNKNOWN))

        result_reg = ctx.fresh_reg()
        ctx.emit_inst(
            CallFunction(
                result_reg=result_reg,
                func_name=FuncName(_BUILTIN_NAME),
                args=(index_reg,),
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
