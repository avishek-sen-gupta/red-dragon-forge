"""Unit tests for CICS flow control builtins."""

from tests.covers import covers, NotLanguageFeature
from cics.builtins.flow import (
    make_set_return_context_builtin,
    make_set_xctl_context_builtin,
)
from cics.types import DispatchKind, DispatchResult
from interpreter.vm.vm_types import VMState
from interpreter.types.typed_value import typed
from interpreter.types.type_expr import UNKNOWN

_LINKED = object()


def _vm() -> VMState:
    return VMState()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_return_context_plain_return():
    holder: list[DispatchResult | None] = [None]
    builtin = make_set_return_context_builtin(holder)
    builtin([], _vm())
    assert holder[0] is not None
    assert holder[0].kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_return_context_with_transid():
    holder: list[DispatchResult | None] = [None]
    builtin = make_set_return_context_builtin(holder)
    args = [
        typed("CC01", UNKNOWN),
        typed(b"\x00" * 16, UNKNOWN),
    ]
    builtin(args, _vm())
    assert holder[0] is not None
    assert holder[0].kind == DispatchKind.RETURN_TRANSID
    assert holder[0].transid == "CC01"
    assert holder[0].commarea == b"\x00" * 16


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_xctl_context():
    holder: list[DispatchResult | None] = [None]
    builtin = make_set_xctl_context_builtin(holder, {"COCRDLIC": _LINKED})
    args = [
        typed("COCRDLIC", UNKNOWN),
        typed(b"", UNKNOWN),
    ]
    resp = builtin(args, _vm()).value
    assert holder[0] is not None
    assert (resp, holder[0].kind, holder[0].program) == (
        0,
        DispatchKind.XCTL,
        "COCRDLIC",
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_set_xctl_context_to_an_unknown_program_answers_pgmiderr():
    """A program the region lacks is CICS's PGMIDERR (27); nothing is held, so
    the issuing program keeps control."""
    holder: list[DispatchResult | None] = [None]
    builtin = make_set_xctl_context_builtin(holder, {})
    resp = builtin([typed("NOSUCH", UNKNOWN), typed(b"", UNKNOWN)], _vm()).value
    assert (resp, holder[0]) == (27, None)
