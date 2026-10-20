"""The CICS coprocessor's compile spec builds no builtins; its runtime returns them, composed into the region's table."""

from __future__ import annotations

import queue

import pytest

from cics.coprocessor import build_cics_spec
from cics.interval import StartQueue
from cics.runtime import install_cics_runtime
from cics.statements import CicsOperand, ExecCicsStatement
from cics.types import DispatchKind, DispatchResult
from cics.vsam.engine import VsamEngine
from interpreter.func_name import FuncName
from interpreter.instructions import Suspend
from interpreter.register import Register
from cics.transaction_hooks import TransactionHooks
from interpreter.vm.builtins import core_builtins
from interpreter.vm.duplicate_builtin_error import DuplicateBuiltinError
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
        "__cics_key_length",
        "__cics_endbr",
        "__cics_formattime",
        "__cics_handle_abend",
        "__cics_handle_aid",
        "__cics_init_eib",
        "__cics_inquire",
        "__cics_link",
        "__cics_link_resolve",
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
def test_compile_spec_names_its_strategies():
    blocking = build_cics_spec().make_strategy()
    conversational = build_cics_spec(conversational=True).make_strategy()

    assert (blocking.name, conversational.name) == ("cics", "cics-conversational")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_returns_today_s_builtins_composed_over_the_core_table():
    start_queue = StartQueue()

    runtime = install_cics_runtime(
        [None],
        program_cache={},
        transid_to_program={},
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
        vsam_engine=VsamEngine({}),
        start_queue=start_queue,
    )

    assert set(runtime.entries) == _CONSTRUCTOR_BUILTINS
    assert set(runtime.builtins) == set(core_builtins()) | _CONSTRUCTOR_BUILTINS
    assert runtime.start_queue is start_queue


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


_SCREEN_BUILTINS = frozenset(
    FuncName(name)
    for name in ("__cics_send_map", "__cics_receive_map", "__cics_send_text")
)


def _fire_abend(runtime) -> BuiltinResult:
    return runtime.builtins[FuncName("__cics_abend")]([], VMState())


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_default_on_abend_is_a_noop():
    """A CICS-only region (no on_abend supplied) keeps its current
    behaviour exactly -- EXEC CICS ABEND must not raise."""
    holder: list[DispatchResult] = [None]
    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=holder,
    )

    _fire_abend(runtime)

    assert holder == [DispatchResult(kind=DispatchKind.ABEND, abcode="UNKN")]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_threads_on_abend_to_the_abend_builtin():
    """install_cics_runtime's on_abend must reach EXEC CICS ABEND's own builtin,
    so a composed SQL runtime's rollback callable runs when the task abends."""
    calls: list[int] = []
    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
        on_abend=lambda: calls.append(1),
    )

    _fire_abend(runtime)

    assert calls == [1]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_returns_screen_builtins_given_both_channels():
    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
        screen_queue=queue.Queue(),
        input_queue=queue.Queue(),
    )

    assert {n for n in runtime.builtins if n in _SCREEN_BUILTINS} == _SCREEN_BUILTINS


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_without_channels_returns_no_screen_builtins():
    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        result_holder=[None],
    )

    assert {n for n in runtime.builtins if n in _SCREEN_BUILTINS} == set()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_install_default_result_holder_does_not_crash():
    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
    )

    result = _fire_abend(runtime)
    assert isinstance(result, BuiltinResult)


def _named_hook(name: str):
    def hook(args, vm) -> BuiltinResult:
        return BuiltinResult(value=name)

    return hook


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_the_hooks_and_other_builtins_a_composer_passes_land_in_the_region_table():
    """The three unit-of-work hooks sit under the __cics_*_hook names, one entry
    each, and another coprocessor's entries are composed in beside cicada's;
    with no hooks passed, each is a no-op."""
    hooks = TransactionHooks(
        task_end=_named_hook("end"),
        syncpoint=_named_hook("sync"),
        rollback=_named_hook("back"),
    )
    other = _named_hook("sql")
    runtime = install_cics_runtime(
        [None],
        transid_to_program={},
        program_cache={},
        hooks=hooks,
        other_builtins={FuncName("__exec_sql"): other},
    )
    plain = install_cics_runtime([None], transid_to_program={}, program_cache={})
    names = ("__cics_task_end_hook", "__cics_syncpoint_hook", "__cics_rollback_hook")

    assert [runtime.builtins[FuncName(n)]([], VMState()).value for n in names] == [
        "end",
        "sync",
        "back",
    ]
    assert [plain.builtins[FuncName(n)]([], VMState()).value for n in names] == [
        None,
        None,
        None,
    ]
    assert runtime.builtins[FuncName("__exec_sql")] is other
    assert FuncName("__exec_sql") not in runtime.entries


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_another_coprocessor_claiming_a_cics_name_is_refused():
    with pytest.raises(DuplicateBuiltinError) as refused:
        install_cics_runtime(
            [None],
            transid_to_program={},
            program_cache={},
            other_builtins={FuncName("__cics_task_end_hook"): _named_hook("x")},
        )

    assert refused.value.name == FuncName("__cics_task_end_hook")
