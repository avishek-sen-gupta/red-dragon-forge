"""Verify screen builtins are registered when the screen/input queues are provided."""

import queue

from tests.covers import covers, NotLanguageFeature
from cics.strategy import CicsLoweringStrategy
from cics.types import DispatchKind
from interpreter.func_name import FuncName
from interpreter.register import Register
from interpreter.vm.builtins import Builtins
from interpreter.vm.vm_types import BuiltinResult, VMState


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
        out = self.fresh_reg()
        self.emit_inst(("to_string", out, value_reg))
        return out


def _strategy():
    return CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_strategy_registers_screen_builtins():
    from interpreter.vm.builtins import Builtins

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        screen_queue=screen_q,
        input_queue=input_q,
        handler_source=[],
        unsupported_verbs=set(),
    )
    assert FuncName("__cics_send_map") in Builtins.TABLE
    assert FuncName("__cics_receive_map") in Builtins.TABLE
    assert FuncName("__cics_send_text") in Builtins.TABLE


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_strategy_without_bms_still_constructs():
    # No screen_queue/input_queue -> screen builtins simply not registered, no error.
    CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_lowers_to_call_function():
    from interpreter.instructions import CallFunction
    from cics.statements import ExecCicsStatement
    from cics.statements import CicsOperand

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
        },
    )
    _strategy().lower(ctx, stmt, materialised=None)
    calls = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    assert any(c.func_name == FuncName("__cics_send_map") for c in calls)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_lowering_passes_mapset_flags_and_cursor():
    from interpreter.instructions import CallFunction, Const
    from cics.statements import CicsOperand, ExecCicsStatement

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
            "ERASE": None,
            "CURSOR": None,
            "FREEKB": None,
        },
    )
    _strategy().lower(ctx, stmt, materialised=None)
    call = next(
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_send_map")
    )
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    assert len(call.args) == 5
    assert consts[call.args[2]] == "COSGN00"
    assert set(consts[call.args[3]]) == {"ERASE", "CURSOR", "FREEKB"}
    assert consts[call.args[4]] == ""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_lowering_passes_base_field_names():
    """SEND MAP resolves the FROM group's leaf fields, strips the O suffix,
    and passes the base names as a Const list arg (args[1])."""
    from interpreter.instructions import CallFunction, Const
    from cics.statements import ExecCicsStatement
    from cics.statements import CicsOperand
    from interpreter.cobol.data_layout import DataLayout, FieldLayout
    from cobol_asg.cobol_types import CobolDataCategory, CobolTypeDescriptor
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout
    from interpreter.register import Register

    def _alpha(n):
        return CobolTypeDescriptor(
            category=CobolDataCategory.ALPHANUMERIC, total_digits=n
        )

    grp = DataLayout(
        fields={
            "USERIDO": FieldLayout(
                name="USERIDO", type_descriptor=_alpha(8), offset=12, byte_length=8
            ),
            "ERRMSGO": FieldLayout(
                name="ERRMSGO", type_descriptor=_alpha(78), offset=20, byte_length=78
            ),
        },
        offset=0,
        total_bytes=98,
    )
    ws = DataLayout(groups={"COSGN0AO": grp}, offset=0, total_bytes=98)
    empty = DataLayout()
    materialised = MaterialisedSectionedLayout(
        working_storage=(ws, Register("%ws")),
        linkage=(empty, Register("%lk")),
        local_storage=(empty, Register("%ls")),
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
            return inst

        def group_leaf_names(self, group_name, mat):
            return mat.group_leaf_names(group_name)

        def has_field(self, name, materialised):
            return False

        def emit_to_string(self, value_reg, *, span=None):
            out = self.fresh_reg()
            self.emit_inst(("to_string", out, value_reg))
            return out

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
            "FROM": CicsOperand("COSGN0AO", False),
        },
    )
    strategy = CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
    strategy.lower(ctx, stmt, materialised=materialised)

    send_calls = [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_send_map")
    ]
    assert len(send_calls) == 1
    call = send_calls[0]
    names_reg = call.args[1]
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    assert consts[names_reg] == ["USERID", "ERRMSG"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_receive_map_without_into_derives_group_from_literal_map_name():
    """RECEIVE MAP('COSGN0A') with no INTO -> group COSGN0AI (map name + 'I')."""
    from interpreter.instructions import Const, CallFunction
    from cics.statements import ExecCicsStatement
    from cics.statements import CicsOperand
    from interpreter.cobol.data_layout import DataLayout, FieldLayout
    from cobol_asg.cobol_types import CobolDataCategory, CobolTypeDescriptor
    from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout
    from interpreter.register import Register

    def _alpha(n):
        return CobolTypeDescriptor(
            category=CobolDataCategory.ALPHANUMERIC, total_digits=n
        )

    grp = DataLayout(
        fields={
            "USERIDI": FieldLayout(
                name="USERIDI", type_descriptor=_alpha(8), offset=12, byte_length=8
            ),
            "PASSWDI": FieldLayout(
                name="PASSWDI", type_descriptor=_alpha(8), offset=20, byte_length=8
            ),
        },
        offset=0,
        total_bytes=28,
    )
    ws = DataLayout(groups={"COSGN0AI": grp}, offset=0, total_bytes=28)
    empty = DataLayout()
    materialised = MaterialisedSectionedLayout(
        working_storage=(ws, Register("%ws")),
        linkage=(empty, Register("%lk")),
        local_storage=(empty, Register("%ls")),
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
            return inst

        def group_leaf_names(self, group_name, mat):
            return mat.group_leaf_names(group_name)

        def has_field(self, name, materialised):
            return False

        def emit_to_string(self, value_reg, *, span=None):
            out = self.fresh_reg()
            self.emit_inst(("to_string", out, value_reg))
            return out

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="RECEIVE MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
        },  # no INTO -> derive COSGN0AI from the literal map name
    )
    strategy = CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
    strategy.lower(ctx, stmt, materialised=materialised)

    recv = [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_receive_map")
    ]
    assert len(recv) == 1
    names_reg = recv[0].args[1]
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    assert consts[names_reg] == ["USERID", "PASSWD"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_syncpoint_lowers_to_a_noop_call():
    """Plain SYNCPOINT no longer VSAM-only-no-ops: it must reach a composed
    SQL runtime's commit via __cics_syncpoint_hook (task-6 brief) and must
    not fall into the unsupported-verb abend path or end the task."""
    from interpreter.instructions import CallFunction, Return_
    from cics.statements import ExecCicsStatement

    ctx = _Ctx()
    stmt = ExecCicsStatement(verb="SYNCPOINT", options={})
    _strategy().lower(ctx, stmt, materialised=None)

    calls = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    assert any(c.func_name == FuncName("__cics_syncpoint_hook") for c in calls)
    assert not any(c.func_name == FuncName("__cics_abend_unsupported") for c in calls)
    assert not any(isinstance(i, Return_) for i in ctx.emitted)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_syncpoint_rollback_lowers_to_the_rollback_hook():
    """SYNCPOINT ROLLBACK is a distinct verb string from plain SYNCPOINT.
    It used to fall through to the unsupported-verb abend path
    (forge-1zu.15, unregistered); it must now lower to the dedicated
    rollback hook instead, without abending or ending the task."""
    from interpreter.instructions import CallFunction, Return_
    from cics.statements import ExecCicsStatement

    unsupported: set = set()
    strategy = CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=unsupported,
    )
    ctx = _Ctx()
    stmt = ExecCicsStatement(verb="SYNCPOINT ROLLBACK", options={})
    strategy.lower(ctx, stmt, materialised=None)

    calls = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    assert any(c.func_name == FuncName("__cics_rollback_hook") for c in calls)
    assert not any(c.func_name == FuncName("__cics_abend_unsupported") for c in calls)
    assert not any(isinstance(i, Return_) for i in ctx.emitted)
    assert unsupported == set()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_text_with_literal_text_still_works():
    from interpreter.instructions import CallFunction, Const
    from cics.statements import CicsOperand, ExecCicsStatement

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="SEND TEXT", options={"TEXT": CicsOperand("HELLO WORLD", True)}
    )
    _strategy().lower(ctx, stmt, materialised=None)

    call = next(
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_send_text")
    )
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    assert len(call.args) == 1
    assert consts[call.args[0]] == "HELLO WORLD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_text_from_resolves_the_named_field():
    """SEND TEXT FROM(WS-MESSAGE) must resolve WS-MESSAGE's runtime value, not
    paint the field name itself onto the screen (the FROM operand was
    previously dropped entirely, rendering a blank screen)."""
    from interpreter.instructions import CallFunction
    from cics.statements import CicsOperand, ExecCicsStatement
    from cobol_asg.cobol_types import CobolDataCategory, CobolTypeDescriptor
    from interpreter.cobol.data_layout import FieldLayout
    from interpreter.cobol.field_resolution import (
        ResolvedFieldRef,
        whole_field_extent,
    )
    from cobol_memory.region_id import RegionId

    class _FieldCtx:
        def __init__(self, fields):
            self._fields = fields
            self.emitted = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst, *, span=None):
            self.emitted.append(inst)
            return inst

        def has_field(self, name, materialised):
            return name in self._fields

        def resolve_field_ref(
            self, name, materialised, qualifiers=(), subscripts=(), *, span=None
        ):
            offset, byte_length = self._fields[name]
            fl = FieldLayout(
                name=name,
                type_descriptor=CobolTypeDescriptor(
                    category=CobolDataCategory.ALPHANUMERIC, total_digits=byte_length
                ),
                offset=offset,
                byte_length=byte_length,
            )
            offset_reg = self.fresh_reg()
            self.emit_inst(("const_offset", offset_reg, offset))
            return ResolvedFieldRef(
                fl=fl,
                offset_reg=offset_reg,
                extent=whole_field_extent(fl, RegionId.WORKING_STORAGE),
            ), Register("%ws")

        def emit_decode_field(
            self, region_reg, fl, offset_reg, *, extent=None, span=None
        ):
            out = self.fresh_reg()
            self.emit_inst(("decode", out, fl.name))
            return out

        def emit_to_string(self, value_reg, *, span=None):
            out = self.fresh_reg()
            self.emit_inst(("to_string", out, value_reg))
            return out

    ctx = _FieldCtx({"WS-MESSAGE": (0, 40)})
    stmt = ExecCicsStatement(
        verb="SEND TEXT", options={"FROM": CicsOperand("WS-MESSAGE", False)}
    )
    _strategy().lower(ctx, stmt, materialised=None)

    call = next(
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_send_text")
    )
    decode = next(i for i in ctx.emitted if isinstance(i, tuple) and i[0] == "decode")
    assert len(call.args) == 1
    assert call.args[0] == decode[1]
    assert decode[2] == "WS-MESSAGE"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_writeq_td_lowers_with_real_args():
    """WRITEQ TD QUEUE('JOBS') FROM('SOME-DATA') passes both operands as real
    args to __cics_writeq_td — not args=() (cicada-vcq)."""
    from interpreter.instructions import CallFunction, Const
    from cics.statements import ExecCicsStatement
    from cics.statements import CicsOperand
    from interpreter.register import Register

    class _Ctx:
        def __init__(self):
            self.emitted = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst, *, span=None):
            self.emitted.append(inst)
            return inst

        def has_field(self, name, materialised):
            return False

        def emit_to_string(self, value_reg, *, span=None):
            result = self.fresh_reg()
            self.emit_inst(
                CallFunction(
                    result_reg=result,
                    func_name=FuncName("str"),
                    args=(value_reg,),
                ),
            )
            return result

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="WRITEQ TD",
        options={
            "QUEUE": CicsOperand("JOBS", True),
            "FROM": CicsOperand("SOME-DATA", True),
        },
    )
    strategy = CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
    strategy.lower(ctx, stmt, materialised=None)

    calls = [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_writeq_td")
    ]
    assert len(calls) == 1
    call = calls[0]
    assert len(call.args) == 2, f"expected 2 real args, got {call.args!r}"
    consts = {i.result_reg: i.value for i in ctx.emitted if isinstance(i, Const)}
    # args[0] = FROM data, args[1] = QUEUE name (make_writeq_td_builtin's order).
    assert consts[call.args[0]] == "SOME-DATA"
    assert consts[call.args[1]] == "JOBS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_writeq_td_lowers_with_resp_writeback():
    """WRITEQ TD QUEUE('JOBS') FROM('SOME-DATA') RESP(WS-RC) writes both
    EIBRESP and the RESP(name) field — not silently dropped (cicada-y6l)."""
    from interpreter.instructions import CallFunction
    from cics.statements import ExecCicsStatement
    from cics.statements import CicsOperand
    from cobol_asg.cobol_types import CobolDataCategory, CobolTypeDescriptor
    from interpreter.cobol.data_layout import FieldLayout
    from interpreter.cobol.field_resolution import (
        ResolvedFieldRef,
        whole_field_extent,
    )
    from cobol_memory.region_id import RegionId
    from interpreter.register import Register

    class _RespCtx:
        """Faithful fake EmitContext supporting the emit_resp_writeback path —
        mirrors tests/unit/cics/test_field_ref_wiring.py's FakeCtx."""

        def __init__(self, fields):
            self._fields = fields
            self.emitted = []
            self.encode_writes = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst, *, span=None):
            self.emitted.append(inst)
            return inst

        def has_field(self, name, materialised):
            return name in self._fields

        def resolve_field_ref(
            self, name, materialised, qualifiers=(), subscripts=(), *, span=None
        ):
            offset, byte_length = self._fields[name]
            fl = FieldLayout(
                name=name,
                type_descriptor=CobolTypeDescriptor(
                    category=CobolDataCategory.ALPHANUMERIC,
                    total_digits=byte_length,
                ),
                offset=offset,
                byte_length=byte_length,
            )
            offset_reg = self.fresh_reg()
            self.emit_inst(("const_offset", offset_reg, offset))
            return ResolvedFieldRef(
                fl=fl,
                offset_reg=offset_reg,
                extent=whole_field_extent(fl, RegionId.WORKING_STORAGE),
            ), Register("%region")

        def emit_encode_and_write(
            self,
            region_reg,
            fl,
            value_str_reg,
            offset_reg=None,
            *,
            extent=None,
            span=None,
        ):
            self.encode_writes.append((region_reg, fl, value_str_reg, offset_reg))

        def emit_to_string(self, value_reg, *, span=None):
            out = self.fresh_reg()
            self.emit_inst(("to_string", out, value_reg))
            return out

    ctx = _RespCtx({"EIBRESP": (0, 4), "WS-RC": (16, 4)})
    stmt = ExecCicsStatement(
        verb="WRITEQ TD",
        options={
            "QUEUE": CicsOperand("JOBS", True),
            "FROM": CicsOperand("SOME-DATA", True),
            "RESP": CicsOperand("WS-RC", False),
        },
    )
    strategy = CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=[None],
        handler_source=[],
        unsupported_verbs=set(),
    )
    strategy.lower(ctx, stmt, materialised=None)

    calls = [
        i
        for i in ctx.emitted
        if isinstance(i, CallFunction) and i.func_name == FuncName("__cics_writeq_td")
    ]
    assert len(calls) == 1, "expected exactly one __cics_writeq_td call"

    assert (
        len(ctx.encode_writes) == 2
    ), f"expected EIBRESP + RESP(WS-RC) writes, got {ctx.encode_writes!r}"
    written_names = {fl.name for (_, fl, _, _) in ctx.encode_writes}
    assert written_names == {"EIBRESP", "WS-RC"}


class _MinimalHolder:
    """A ``Holder`` (the ``_Slot`` protocol: ``__getitem__``/``__setitem__`` only)
    that is type-legal for the ``result_holder`` parameter without being a
    ``list`` or any ``MutableSequence``."""

    def __init__(self, values):
        self._values = list(values)

    def __getitem__(self, index):
        return self._values[index]

    def __setitem__(self, index, value):
        self._values[index] = value


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_non_list_result_holder_still_receives_dispatch_results():
    holder = _MinimalHolder([None])
    CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=holder,
        handler_source=[],
        unsupported_verbs=set(),
    )

    abend = Builtins.TABLE[FuncName("__cics_abend")]
    abend([], VMState())

    assert holder[0] is not None
    assert holder[0].kind == DispatchKind.ABEND


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_none_result_holder_falls_back_without_crashing():
    """``result_holder=None`` is the legacy pre-fp-gate Absent value
    (see ``Absent``'s docstring in strategy.py) — the same as omitting it.
    A caller passing it must still get a working internal holder, not a
    bare ``None`` the builtins try to subscript."""
    CicsLoweringStrategy(
        program_cache={},
        context_holder=[None],
        result_holder=None,
        handler_source=[],
        unsupported_verbs=set(),
    )

    abend = Builtins.TABLE[FuncName("__cics_abend")]
    result = abend([], VMState())
    assert isinstance(result, BuiltinResult)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_build_cics_spec_default_result_holder_does_not_crash():
    from cics.coprocessor import build_cics_spec

    spec = build_cics_spec(program_cache={}, context_holder=[None])
    spec.make_strategy()

    abend = Builtins.TABLE[FuncName("__cics_abend")]
    result = abend([], VMState())
    assert isinstance(result, BuiltinResult)
