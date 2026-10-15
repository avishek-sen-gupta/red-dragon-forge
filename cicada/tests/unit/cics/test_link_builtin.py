"""Unit tests for the __cics_link builtin and LINK lowering helpers (EXEC CICS LINK)."""

from __future__ import annotations

import pytest
from tests.covers import covers, NotLanguageFeature

from cics.builtins.flow import make_link_builtin
from cics.strategy import _resolve_cics_length_option
from cics.types import CicsContext, DispatchKind, DispatchResult
from cics.statements import CicsOperand
from interpreter.vm.vm_types import VMState, StackFrame, BuiltinResult
from interpreter.func_name import FuncName
from interpreter.var_name import VarName
from interpreter.address import Address
from interpreter.types.typed_value import typed
from interpreter.types.type_expr import UNKNOWN

# ── Helpers ───────────────────────────────────────────────────────────────────

_DFHENTER = "\x7d"


def _make_context(transid: str = "CC00", commarea: bytes = b"") -> CicsContext:
    return CicsContext(transid=transid, commarea=commarea, eibaid=_DFHENTER)


def _make_vm_with_ws(region_bytes: bytearray) -> tuple[VMState, Address]:
    """Return a VMState whose WS region is ``region_bytes``."""
    vm = VMState()
    addr = Address("rgn_ws_test")
    vm.region_set(addr, region_bytes)
    vm.call_stack.append(
        StackFrame(
            function_name=FuncName("main"),
            local_vars={VarName("__ws_region"): typed(str(addr), UNKNOWN)},
        )
    )
    return vm, addr


def _args(*vals) -> list:
    """Wrap raw values as minimal TypedValue-like objects."""

    class _TV:
        def __init__(self, v):
            self.value = v

    return [_TV(v) for v in vals]


def _make_stub_linked_program(ca_out: bytes):
    """Return a fake LinkedProgram whose execution writes ca_out to rgn_commarea."""
    from interpreter.address import Address as _Addr
    from interpreter.vm.vm_types import VMState as _VMState

    class _StubLinked:
        entry_func_label = None

    def _fake_run_linked(linked, entry_point, *, max_steps, initial_vm):
        addr = _Addr("rgn_commarea")
        buf = bytearray(initial_vm.region_get(addr) or b"")
        n = min(len(ca_out), len(buf))
        buf[:n] = ca_out[:n]
        initial_vm.region_set(addr, buf)
        return initial_vm

    return _StubLinked(), _fake_run_linked


# ── Tests ─────────────────────────────────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_link_unknown_program_is_noop():
    """LINK to a program not in program_cache logs a warning and returns 0."""
    result_holder = [None]
    context_holder = [_make_context()]
    builtin = make_link_builtin({}, result_holder, context_holder, max_steps=10_000)

    ws = bytearray(b"INIT")
    vm, ws_addr = _make_vm_with_ws(ws)
    result = builtin(_args("UNKNOWN", b"INIT", 0, 4), vm)

    assert result.value == 0
    assert bytes(vm.region_get(ws_addr)) == b"INIT"  # WS unchanged


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_link_writes_modified_commarea_back_to_ws():
    """LINK runs the target and writes its modified CA back into the caller's WS."""
    stub, fake_run = _make_stub_linked_program(ca_out=b"DONE")

    program_cache = {"MUTATOR": stub}
    result_holder = [None]
    context_holder = [_make_context()]
    builtin = make_link_builtin(
        program_cache, result_holder, context_holder, max_steps=10_000, _run_fn=fake_run
    )

    ws = bytearray(b"INIT")
    vm, ws_addr = _make_vm_with_ws(ws)
    result = builtin(_args("MUTATOR", b"INIT", 0, 4), vm)

    assert result.value == 0
    assert bytes(vm.region_get(ws_addr)) == b"DONE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_link_restores_result_holder():
    """result_holder is restored to its pre-LINK value after the inner program returns."""
    stub, fake_run = _make_stub_linked_program(ca_out=b"XXXX")

    outer_result = DispatchResult(kind=DispatchKind.RETURN_TRANSID, transid="CM00")
    result_holder = [outer_result]
    context_holder = [_make_context()]
    builtin = make_link_builtin(
        {"MUTATOR": stub},
        result_holder,
        context_holder,
        max_steps=10_000,
        _run_fn=fake_run,
    )

    ws = bytearray(b"INIT")
    vm, _ = _make_vm_with_ws(ws)
    builtin(_args("MUTATOR", b"INIT", 0, 4), vm)

    # Outer result must be exactly what it was before the LINK call
    assert result_holder[0] is outer_result


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_link_suppresses_task_end_hook_during_inner_program():
    """A LINKed program's own RETURN must not fire the caller's task-end
    hook (e.g. squall's commit + cursor-close) -- that would end the
    caller's still-open unit of work mid-task, not the LINK's."""
    from interpreter.vm.builtins import Builtins

    hook_name = FuncName("__cics_task_end_hook")
    calls: list[str] = []

    def _outer_hook(args, vm):
        calls.append("outer")
        return BuiltinResult(value=None)

    previous = Builtins.TABLE.get(hook_name)
    Builtins.TABLE[hook_name] = _outer_hook
    try:
        stub, _ = _make_stub_linked_program(ca_out=b"DONE")

        def _fake_run_linked(linked, entry_point, *, max_steps, initial_vm):
            # Simulate the inner program's own RETURN firing whatever is
            # currently registered under the hook name.
            Builtins.TABLE[hook_name]([], initial_vm)
            addr = Address("rgn_commarea")
            buf = bytearray(initial_vm.region_get(addr) or b"")
            n = min(len(b"DONE"), len(buf))
            buf[:n] = b"DONE"[:n]
            initial_vm.region_set(addr, buf)
            return initial_vm

        program_cache = {"MUTATOR": stub}
        result_holder = [None]
        context_holder = [_make_context()]
        builtin = make_link_builtin(
            program_cache,
            result_holder,
            context_holder,
            max_steps=10_000,
            _run_fn=_fake_run_linked,
        )
        ws = bytearray(b"INIT")
        vm, _ws_addr = _make_vm_with_ws(ws)

        builtin(_args("MUTATOR", b"INIT", 0, 4), vm)

        assert calls == []  # suppressed during the LINK
        assert Builtins.TABLE[hook_name] is _outer_hook  # restored after
    finally:
        if previous is None:
            Builtins.TABLE.pop(hook_name, None)
        else:
            Builtins.TABLE[hook_name] = previous


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_link_restores_task_end_hook_even_on_exception():
    """The task-end-hook suppression must unwind even when run_linked raises,
    mirroring result_holder's own exception-safe restore."""
    from interpreter.vm.builtins import Builtins

    hook_name = FuncName("__cics_task_end_hook")

    def _outer_hook(args, vm):
        return BuiltinResult(value=None)

    previous = Builtins.TABLE.get(hook_name)
    Builtins.TABLE[hook_name] = _outer_hook
    try:

        class _BadLinked:
            entry_func_label = None

        def _exploding_run(linked, ep, *, max_steps, initial_vm):
            raise RuntimeError("boom")

        result_holder = [None]
        context_holder = [_make_context()]
        builtin = make_link_builtin(
            {"BAD": _BadLinked()},
            result_holder,
            context_holder,
            max_steps=10_000,
            _run_fn=_exploding_run,
        )
        ws = bytearray(b"INIT")
        vm, _ = _make_vm_with_ws(ws)

        with pytest.raises(RuntimeError, match="boom"):
            builtin(_args("BAD", b"INIT", 0, 4), vm)

        assert Builtins.TABLE[hook_name] is _outer_hook
    finally:
        if previous is None:
            Builtins.TABLE.pop(hook_name, None)
        else:
            Builtins.TABLE[hook_name] = previous


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_link_result_holder_restored_even_on_exception():
    """result_holder is restored even if run_linked raises."""

    class _BadLinked:
        entry_func_label = None

    def _exploding_run(linked, ep, *, max_steps, initial_vm):
        raise RuntimeError("boom")

    outer_result = DispatchResult(kind=DispatchKind.RETURN)
    result_holder = [outer_result]
    context_holder = [_make_context()]
    builtin = make_link_builtin(
        {"BAD": _BadLinked()},
        result_holder,
        context_holder,
        max_steps=10_000,
        _run_fn=_exploding_run,
    )

    ws = bytearray(b"INIT")
    vm, _ = _make_vm_with_ws(ws)

    with pytest.raises(RuntimeError, match="boom"):
        builtin(_args("BAD", b"INIT", 0, 4), vm)

    assert result_holder[0] is outer_result


# ── _resolve_cics_length_option ───────────────────────────────────────────────


def _op(text: str) -> CicsOperand:
    return CicsOperand(text=text, is_literal=False)


class _FakeCtx:
    """Minimal EmitContext stub for _resolve_cics_length_option."""

    def __init__(self, field_lengths: dict) -> None:
        self._fields = field_lengths

    def has_field(self, name, _mat) -> bool:
        return name in self._fields

    def resolve_field_ref(self, name, _mat, subscripts=(), *, span=None):
        class _FL:
            byte_length = None

        fl = _FL()
        fl.byte_length = self._fields[name]

        class _Ref:
            pass

        ref = _Ref()
        ref.fl = fl
        return ref, None


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_length_option_absent_returns_fallback():
    ctx = _FakeCtx({})
    assert _resolve_cics_length_option(None, 99, ctx, None) == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_length_option_digit_literal():
    ctx = _FakeCtx({})
    assert _resolve_cics_length_option(_op("160"), 99, ctx, None) == 160


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_length_option_length_of_known_field():
    ctx = _FakeCtx({"WS-CA": 36})
    assert _resolve_cics_length_option(_op("LENGTH OF WS-CA"), 99, ctx, None) == 36


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_length_option_length_of_unknown_field_returns_fallback():
    ctx = _FakeCtx({})
    assert _resolve_cics_length_option(_op("LENGTH OF MISSING"), 99, ctx, None) == 99


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_length_option_unresolvable_text_returns_fallback():
    ctx = _FakeCtx({})
    assert _resolve_cics_length_option(_op("WS-DYN-LEN"), 99, ctx, None) == 99
