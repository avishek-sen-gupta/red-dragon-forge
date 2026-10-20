"""EXEC CICS RETURN (with or without TRANSID) always emits a call to the
generic __cics_task_end_hook extension point; XCTL (which continues the same
task/unit of work) does not. Each hook defaults to a no-op so cicada is
correct standing alone; a composer passes another coprocessor's real
implementation (e.g. squall's) in TransactionHooks instead."""

from tests.covers import covers, NotLanguageFeature
from cics.statements import ExecCicsStatement, CicsOperand
from cics.strategy import CicsLoweringStrategy
from cics.runtime import install_cics_runtime
from cics.transaction_hooks import TransactionHooks

from interpreter.func_name import FuncName
from interpreter.instructions import CallFunction
from interpreter.register import Register
from interpreter.vm.vm_types import BuiltinResult

_HOOK_NAME = FuncName("__cics_task_end_hook")
_SYNCPOINT_HOOK_NAME = FuncName("__cics_syncpoint_hook")
_ROLLBACK_HOOK_NAME = FuncName("__cics_rollback_hook")


class _Ctx:
    def __init__(self):
        self.emitted = []
        self._n = 0

    def fresh_reg(self):
        self._n += 1
        return Register(f"%r{self._n}")

    def emit_inst(self, inst, *, span=None):
        self.emitted.append(inst)

    def group_leaf_names(self, group_name, materialised):
        return []

    def has_field(self, name, materialised):
        return False

    def emit_to_string(self, value_reg, *, span=None):
        return value_reg

    def const_to_reg(self, value):
        return self.fresh_reg()

    def fresh_label(self, prefix):
        return f"{prefix}_{self.fresh_reg()}"


def _install(hooks: TransactionHooks = TransactionHooks()):
    return install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
        hooks=hooks,
    ).builtins


def _strategy() -> CicsLoweringStrategy:
    return CicsLoweringStrategy(
        conversational=False, handler_source=[], unsupported_verbs=set()
    )


def _task_end_hook_calls(ctx: _Ctx) -> list[CallFunction]:
    return _hook_calls(ctx, _HOOK_NAME)


def _hook_calls(ctx: _Ctx, name: FuncName) -> list[CallFunction]:
    return [
        i for i in ctx.emitted if isinstance(i, CallFunction) and i.func_name == name
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_plain_return_emits_task_end_hook_call():
    strategy = _strategy()
    stmt = ExecCicsStatement(verb="RETURN", options={})
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert len(_task_end_hook_calls(ctx)) == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_return_transid_emits_task_end_hook_call():
    strategy = _strategy()
    stmt = ExecCicsStatement(
        verb="RETURN",
        options={"TRANSID": CicsOperand("CA00", True)},
    )
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert len(_task_end_hook_calls(ctx)) == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_xctl_does_not_emit_task_end_hook_call():
    """XCTL continues the same task (no new terminal input, same unit of
    work) — it must not fire the task-end hook."""
    strategy = _strategy()
    stmt = ExecCicsStatement(
        verb="XCTL",
        options={"PROGRAM": CicsOperand("COSGN00C", True)},
    )
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert _task_end_hook_calls(ctx) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_default_hook_is_in_the_table_and_is_a_noop():
    table = _install()

    assert _HOOK_NAME in table
    result = table[_HOOK_NAME]([], None)
    assert result.value is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_passed_task_end_hook_replaces_the_default():
    """Another coprocessor's real implementation (e.g. squall's session
    reset), passed in TransactionHooks, is the one under the hook name."""

    def _real_reset(args, vm):
        return BuiltinResult(value="already-registered")

    table = _install(TransactionHooks(task_end=_real_reset))

    assert table[_HOOK_NAME] is _real_reset


# ── SYNCPOINT / SYNCPOINT ROLLBACK ──────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_syncpoint_emits_the_syncpoint_hook():
    """EXEC CICS SYNCPOINT used to be a pure no-op that never touched SQL —
    it must now reach a composed SQL runtime's commit (task-6 brief)."""
    strategy = _strategy()
    stmt = ExecCicsStatement(verb="SYNCPOINT", options={})
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert len(_hook_calls(ctx, _SYNCPOINT_HOOK_NAME)) == 1
    # SYNCPOINT is not a task boundary -- it must not also fire task end.
    assert _task_end_hook_calls(ctx) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_syncpoint_rollback_emits_the_rollback_hook():
    """SYNCPOINT ROLLBACK was unregistered and fell through to
    _lower_unsupported's loud abend (forge-1zu.15) -- it must lower to the
    rollback hook instead, distinct from plain SYNCPOINT's commit hook."""
    strategy = _strategy()
    stmt = ExecCicsStatement(verb="SYNCPOINT ROLLBACK", options={})
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert len(_hook_calls(ctx, _ROLLBACK_HOOK_NAME)) == 1
    assert _hook_calls(ctx, _SYNCPOINT_HOOK_NAME) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_default_syncpoint_hook_is_in_the_table_and_is_a_noop():
    table = _install()

    assert _SYNCPOINT_HOOK_NAME in table
    result = table[_SYNCPOINT_HOOK_NAME]([], None)
    assert result.value is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_default_rollback_hook_is_in_the_table_and_is_a_noop():
    table = _install()

    assert _ROLLBACK_HOOK_NAME in table
    result = table[_ROLLBACK_HOOK_NAME]([], None)
    assert result.value is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_passed_syncpoint_hook_replaces_the_default():
    def _real_syncpoint(args, vm):
        return BuiltinResult(value="already-registered")

    table = _install(TransactionHooks(syncpoint=_real_syncpoint))

    assert table[_SYNCPOINT_HOOK_NAME] is _real_syncpoint
