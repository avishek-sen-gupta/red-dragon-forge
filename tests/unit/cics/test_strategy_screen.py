"""Verify screen builtins are registered when the screen/input queues are provided."""

import queue

from tests.covers import covers, NotLanguageFeature
from cics.strategy import CicsLoweringStrategy
from interpreter.func_name import FuncName


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_strategy_registers_screen_builtins():
    from interpreter.vm.builtins import Builtins

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    CicsLoweringStrategy(
        context_holder=[None],
        result_holder=[None],
        screen_queue=screen_q,
        input_queue=input_q,
    )
    assert FuncName("__cics_send_map") in Builtins.TABLE
    assert FuncName("__cics_receive_map") in Builtins.TABLE
    assert FuncName("__cics_send_text") in Builtins.TABLE


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_strategy_without_bms_still_constructs():
    # No screen_queue/input_queue -> screen builtins simply not registered, no error.
    CicsLoweringStrategy(context_holder=[None], result_holder=[None])


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_lowers_to_call_function():
    from interpreter.instructions import CallFunction
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.register import Register

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

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
        },
    )
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
    strategy.lower(ctx, stmt, materialised=None)
    calls = [i for i in ctx.emitted if isinstance(i, CallFunction)]
    assert any(c.func_name == FuncName("__cics_send_map") for c in calls)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_map_lowering_passes_base_field_names():
    """SEND MAP resolves the FROM group's leaf fields, strips the O suffix,
    and passes the base names as a Const list arg (args[1])."""
    from interpreter.instructions import CallFunction, Const
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.cobol.data_layout import DataLayout, FieldLayout
    from interpreter.cobol.cobol_types import CobolDataCategory, CobolTypeDescriptor
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

        def emit_inst(self, inst):
            self.emitted.append(inst)
            return inst

        def group_leaf_names(self, group_name, mat):
            return mat.group_leaf_names(group_name)

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="SEND MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
            "FROM": CicsOperand("COSGN0AO", False),
        },
    )
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
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
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.cobol.data_layout import DataLayout, FieldLayout
    from interpreter.cobol.cobol_types import CobolDataCategory, CobolTypeDescriptor
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

        def emit_inst(self, inst):
            self.emitted.append(inst)
            return inst

        def group_leaf_names(self, group_name, mat):
            return mat.group_leaf_names(group_name)

    ctx = _Ctx()
    stmt = ExecCicsStatement(
        verb="RECEIVE MAP",
        options={
            "MAP": CicsOperand("COSGN0A", True),
            "MAPSET": CicsOperand("COSGN00", True),
        },  # no INTO -> derive COSGN0AI from the literal map name
    )
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
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
def test_writeq_td_lowers_with_real_args():
    """WRITEQ TD QUEUE('JOBS') FROM('SOME-DATA') passes both operands as real
    args to __cics_writeq_td — not args=() (cicada-vcq)."""
    from interpreter.instructions import CallFunction, Const
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.register import Register

    class _Ctx:
        def __init__(self):
            self.emitted = []
            self._n = 0

        def fresh_reg(self):
            self._n += 1
            return Register(f"%r{self._n}")

        def emit_inst(self, inst):
            self.emitted.append(inst)
            return inst

        def has_field(self, name, materialised):
            return False

        def emit_to_string(self, value_reg):
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
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
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
    from interpreter.cobol.cobol_statements import ExecCicsStatement
    from interpreter.cobol.cobol_statements import CicsOperand
    from interpreter.cobol.cobol_types import CobolDataCategory, CobolTypeDescriptor
    from interpreter.cobol.data_layout import FieldLayout
    from interpreter.cobol.field_resolution import ResolvedFieldRef
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

        def emit_inst(self, inst):
            self.emitted.append(inst)
            return inst

        def has_field(self, name, materialised):
            return name in self._fields

        def resolve_field_ref(self, name, materialised, qualifiers=(), subscripts=()):
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
            return ResolvedFieldRef(fl=fl, offset_reg=offset_reg), Register("%region")

        def emit_encode_and_write(self, region_reg, fl, value_str_reg, offset_reg=None):
            self.encode_writes.append((region_reg, fl, value_str_reg, offset_reg))

        def emit_to_string(self, value_reg):
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
    strategy = CicsLoweringStrategy(context_holder=[None], result_holder=[None])
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
