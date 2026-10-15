"""The CICS coprocessor's compile spec registers nothing; its runtime installs the builtins."""

from __future__ import annotations

import queue

import pytest

from cics.coprocessor import build_cics_spec
from cics.interval import StartQueue
from cics.runtime import install_cics_runtime
from cics.statements import CicsOperand, ExecCicsStatement
from cics.vsam.engine import VsamEngine
from interpreter.func_name import FuncName
from interpreter.instructions import Suspend
from interpreter.register import Register
from interpreter.vm.builtins import Builtins
from interpreter.vm.vm_types import BuiltinResult, VMState
from tests.covers import NotLanguageFeature, covers

_CONSTRUCTOR_BUILTINS = frozenset(
    FuncName(name)
    for name in (
        "__cics_abend",
        "__cics_abend_unhandled",
        "__cics_abend_unsupported",
        "__cics_apply_input",
        "__cics_asktime",
        "__cics_assign",
        "__cics_bif_deedit",
        "__cics_delete",
        "__cics_endbr",
        "__cics_formattime",
        "__cics_handle_abend",
        "__cics_handle_aid",
        "__cics_init_eib",
        "__cics_inquire",
        "__cics_link",
        "__cics_read",
        "__cics_readnext",
        "__cics_readprev",
        "__cics_receive_map",
        "__cics_retrieve",
        "__cics_rewrite",
        "__cics_rollback_hook",
        "__cics_send_map",
        "__cics_send_text",
        "__cics_set_return_context",
        "__cics_set_xctl_context",
        "__cics_start",
        "__cics_startbr",
        "__cics_syncpoint_hook",
        "__cics_task_end_hook",
        "__cics_unlock",
        "__cics_write",
        "__cics_writeq_td",
    )
)


@pytest.fixture(autouse=True)
def _restore_builtins_table():
    before = dict(Builtins.TABLE)
    yield
    Builtins.TABLE.clear()
    Builtins.TABLE.update(before)


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
        return self.fresh_reg()


def _suspends_lowered(conversational: bool) -> int:
    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="RECEIVE MAP",
        options={
            "MAP": CicsOperand("ASKMAP", True),
            "INTO": CicsOperand("ASKMAPI", False),
        },
    )
    build_cics_spec(conversational=conversational).make_strategy().lower(
        ctx, stmt, materialised=None
    )
    return sum(isinstance(inst, Suspend) for inst in ctx.emitted)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_compile_spec_registers_nothing():
    before = dict(Builtins.TABLE)

    blocking = build_cics_spec().make_strategy()
    conversational = build_cics_spec(conversational=True).make_strategy()

    assert dict(Builtins.TABLE) == before
    assert (blocking.name, conversational.name) == ("cics", "cics-conversational")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_registers_today_s_builtins():
    Builtins.TABLE.clear()

    start_queue = StartQueue()

    used = install_cics_runtime(
        [None],
        program_cache={},
        transid_to_program={},
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
        vsam_engine=VsamEngine({}),
        start_queue=start_queue,
    )

    assert {n for n in Builtins.TABLE if n in _CONSTRUCTOR_BUILTINS} == (
        _CONSTRUCTOR_BUILTINS
    )
    assert used is start_queue


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_conversational_lowering_survives_the_split():
    assert (_suspends_lowered(False), _suspends_lowered(True)) == (0, 1)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_install_without_the_regions_programs_and_transactions_is_refused():
    """Every EXEC CICS LINK resolves against the program cache and every START
    against the transaction map. Empty ones the runtime made for itself would
    make every LINK fail and every START be rejected, silently; a caller that
    forgets either is told so instead."""
    with pytest.raises(TypeError) as refused:
        install_cics_runtime([None])

    message = str(refused.value)
    assert (message.partition(" missing ")[0], message.rpartition(": ")[2]) == (
        "install_cics_runtime()",
        "'program_cache' and 'transid_to_program'",
    )


def _fire_abend() -> BuiltinResult:
    return Builtins.TABLE[FuncName("__cics_abend")]([], VMState())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_default_on_abend_is_a_noop():
    """A CICS-only region (no on_abend supplied) keeps its current
    behaviour exactly -- EXEC CICS ABEND must not raise."""
    install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
    )

    _fire_abend()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_threads_on_abend_to_the_abend_builtin():
    """install_cics_runtime's on_abend must reach EXEC CICS ABEND's own builtin,
    so a composed SQL runtime's rollback callable runs when the task abends."""
    calls: list[int] = []
    install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
        on_abend=lambda: calls.append(1),
    )

    _fire_abend()

    assert calls == [1]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_registers_screen_builtins_given_both_channels():
    install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
    )

    assert FuncName("__cics_send_map") in Builtins.TABLE
    assert FuncName("__cics_receive_map") in Builtins.TABLE
    assert FuncName("__cics_send_text") in Builtins.TABLE


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_without_channels_does_not_raise():
    install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_default_result_holder_does_not_crash():
    install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
    )

    result = _fire_abend()
    assert isinstance(result, BuiltinResult)
