"""EXEC CICS RETURN (with or without TRANSID) always emits a call to the
generic __cics_task_end_hook extension point; XCTL (which continues the same
task/unit of work) does not. A no-op default is registered so cicada is
correct standing alone; another composed coprocessor (e.g. squall) may
independently register its own real implementation over that default."""

import pytest

from tests.covers import covers, NotLanguageFeature
from cics.statements import ExecCicsStatement, CicsOperand
from cics.strategy import CicsLoweringStrategy

from interpreter.func_name import FuncName
from interpreter.instructions import CallFunction
from interpreter.register import Register
from interpreter.vm.builtins import Builtins
from interpreter.vm.vm_types import BuiltinResult

_HOOK_NAME = FuncName("__cics_task_end_hook")


@pytest.fixture(autouse=True)
def _restore_hook_registration():
    """Builtins.TABLE is a shared global that outlives this test file (it's
    read by real CICS programs in other tests running in the same process,
    e.g. under pytest-xdist) — snapshot and restore whatever was registered
    under _HOOK_NAME so a test mutating it can never leak into another test.
    """
    previous = Builtins.TABLE.get(_HOOK_NAME)
    yield
    if previous is None:
        Builtins.TABLE.pop(_HOOK_NAME, None)
    else:
        Builtins.TABLE[_HOOK_NAME] = previous


class _Ctx:
    def __init__(self):
        self.emitted = []
        self._n = 0

    def fresh_reg(self):
        self._n += 1
        return Register(f"%r{self._n}")

    def emit_inst(self, inst):
        self.emitted.append(inst)

    def group_leaf_names(self, group_name, materialised):
        return []

    def has_field(self, name, materialised):
        return False


def _task_end_hook_calls(ctx: _Ctx) -> list[CallFunction]:
    return [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == _HOOK_NAME
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_plain_return_emits_task_end_hook_call():
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
    stmt = ExecCicsStatement(verb="RETURN", options={})
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert len(_task_end_hook_calls(ctx)) == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_return_transid_emits_task_end_hook_call():
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
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
    strategy = CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
    stmt = ExecCicsStatement(
        verb="XCTL",
        options={"PROGRAM": CicsOperand("COSGN00C", True)},
    )
    ctx = _Ctx()

    strategy.lower(ctx, stmt, materialised=None)

    assert _task_end_hook_calls(ctx) == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_default_hook_is_registered_and_is_a_noop():
    Builtins.TABLE.pop(_HOOK_NAME, None)

    CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )

    assert _HOOK_NAME in Builtins.TABLE
    result = Builtins.TABLE[_HOOK_NAME]([], vm=None)
    assert result.value is None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_default_hook_does_not_overwrite_an_existing_registration():
    """Order-independence: if another coprocessor (e.g. squall) already
    registered its real implementation before CicsLoweringStrategy
    constructs, the default must not clobber it."""

    def _real_reset(args, vm):
        return BuiltinResult(value="already-registered")

    Builtins.TABLE[_HOOK_NAME] = _real_reset

    CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )

    assert Builtins.TABLE[_HOOK_NAME] is _real_reset
