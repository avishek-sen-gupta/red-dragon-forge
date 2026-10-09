"""Unit tests for build_cics_spec's on_abend threading (task-6 brief).

The dispatcher-level abends (unknown XCTL/RETURN-TRANSID target, terminal
read timeout) are raised in Python at the routing layer, not IR, so they
cannot emit a CallFunction hook. build_cics_spec instead accepts a plain
``on_abend`` callable that reaches every IR-raised abend path (EXEC CICS
ABEND, an unhandled condition, an unsupported verb) through
CicsLoweringStrategy's abend builtins -- a forge composition supplies
squall's rollback here (Task 10) without cicada ever naming squall.
"""

from __future__ import annotations

import pytest

from interpreter.func_name import FuncName
from interpreter.instructions import CallFunction
from interpreter.register import Register
from interpreter.vm.builtins import Builtins

from cics.coprocessor import build_cics_spec
from cics.strategy import CicsLoweringStrategy
from cics.statements import ExecCicsStatement
from tests.covers import NotLanguageFeature, covers

_ABEND_BUILTIN = FuncName("__cics_abend")


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


def _lower_abend(strategy) -> None:
    stmt = ExecCicsStatement(verb="ABEND", options={})
    strategy.lower(_Ctx(), stmt, materialised=None)


def _fire_registered_abend_builtin() -> None:
    Builtins.TABLE[_ABEND_BUILTIN]([], vm=None)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_cics_spec_default_on_abend_is_a_noop():
    """A CICS-only region (no on_abend supplied) keeps its current
    behaviour exactly -- EXEC CICS ABEND must not raise."""
    spec = build_cics_spec(
        transid_to_program={},
        program_cache={},
        context_holder=[None],
        result_holder=[None],
    )
    strategy = spec.make_strategy()

    _lower_abend(strategy)
    _fire_registered_abend_builtin()  # must not raise


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_cics_spec_threads_on_abend_to_the_abend_builtin():
    """build_cics_spec's on_abend must reach EXEC CICS ABEND's own builtin,
    so a composed SQL runtime's rollback callable runs when the task abends."""
    calls: list[int] = []
    spec = build_cics_spec(
        transid_to_program={},
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        on_abend=lambda: calls.append(1),
    )
    strategy = spec.make_strategy()

    _lower_abend(strategy)
    _fire_registered_abend_builtin()

    assert calls == [1]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_spec_or_strategy_without_the_regions_programs_and_transactions_is_refused() -> (
    None
):
    """Every EXEC CICS LINK resolves against the program cache and every START
    against the transaction map. Empty ones the runtime made for itself would
    make every LINK fail and every START be rejected, silently; a caller that
    forgets either is told so instead."""
    with pytest.raises(TypeError) as spec_refused:
        build_cics_spec(context_holder=[None])
    with pytest.raises(TypeError) as strategy_refused:
        CicsLoweringStrategy(
            context_holder=[None],
            handler_source=[],
            unsupported_verbs=set(),
        )

    refusals = (str(spec_refused.value), str(strategy_refused.value))
    assert [
        (message.partition(" missing ")[0], message.rpartition(": ")[2])
        for message in refusals
    ] == [
        ("build_cics_spec()", "'program_cache' and 'transid_to_program'"),
        (
            "CicsLoweringStrategy.__init__()",
            "'program_cache' and 'transid_to_program'",
        ),
    ]
