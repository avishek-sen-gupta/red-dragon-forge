"""HANDLE AID as IR: a label index per attention key, and the branch a RECEIVE takes on the key that ended it."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from cics.aid_keys import AID_BYTES, AID_SLOTS, ANYKEY, ENTER
from cics.table_cells import emit_indexed_read, emit_indexed_write
from interpreter.cobol.cobol_constants import BuiltinName
from interpreter.cobol.emit_context import EmitContext
from interpreter.cobol.ir_emitter import IrEmitter
from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout
from interpreter.instructions import Label_, LoadRegion, Return_
from interpreter.ir import CodeLabel
from interpreter.register import Register
from interpreter.var_name import VarName

AID_DISPATCH = CodeLabel("__cics_aid_dispatch")
IGNORED = -1

_TABLE = "DFH-AID-HANDLER"
_PENDING = "DFH-AID-PENDING"
_EIBAID = "EIBAID"

HandlerMatch = Callable[[EmitContext, Register, tuple[CodeLabel, int]], None]


def has_aid_tables(ctx: EmitContext, materialised: MaterialisedSectionedLayout) -> bool:
    return all(
        ctx.has_field(name, materialised) for name in (_TABLE, _PENDING, _EIBAID)
    )


def emit_aid_registration(
    ctx: EmitContext, key: str, index: int, materialised: MaterialisedSectionedLayout
) -> None:
    r_index = ctx.emit_to_string(ctx.const_to_reg(index))
    emit_indexed_write(ctx, _TABLE, AID_SLOTS[key], r_index, materialised)


def _emit_eibaid(
    ctx: EmitContext, materialised: MaterialisedSectionedLayout
) -> Register:
    ref, region_reg = ctx.resolve_field_ref(_EIBAID, materialised)
    raw = ctx.fresh_reg()
    ctx.emit_inst(
        LoadRegion(
            result_reg=raw, region_reg=region_reg, offset_reg=ref.offset_reg, length=1
        )
    )
    return IrEmitter(ctx, None).call(BuiltinName.LIST_GET, raw, ctx.const_to_reg(0))


def _emit_key_check(
    e: IrEmitter,
    aid: Register,
    key: str,
    chosen: tuple[VarName, CodeLabel],
    materialised: MaterialisedSectionedLayout,
) -> None:
    handler, matched = chosen
    take, after = e.label("aid_take"), e.label("aid_next")
    e.branch_if(e.binop("==", aid, e.int_(AID_BYTES[key])), take, after)
    e.place(take)
    e.store(handler, emit_indexed_read(e.ctx, _TABLE, AID_SLOTS[key], materialised))
    e.jump(matched)
    e.place(after)


def _emit_anykey(
    e: IrEmitter,
    aid: Register,
    handler: VarName,
    materialised: MaterialisedSectionedLayout,
) -> None:
    done = e.label("aid_anykey_done")
    settled = e.binop("!=", e.load(handler), e.int_(0))
    entered = e.binop("==", aid, e.int_(AID_BYTES[ENTER]))
    e.skip_if(e.binop("or", settled, entered), done)
    e.store(handler, emit_indexed_read(e.ctx, _TABLE, AID_SLOTS[ANYKEY], materialised))
    e.place(done)


def _emit_chosen_handler(
    e: IrEmitter,
    aid: Register,
    keys: frozenset[str],
    materialised: MaterialisedSectionedLayout,
) -> Register:
    handler = e.var("aid_handler", e.int_(0))
    matched = e.label("aid_matched")
    for key in sorted(keys - {ANYKEY}):
        _emit_key_check(e, aid, key, (handler, matched), materialised)
    e.place(matched)
    if ANYKEY in keys:
        _emit_anykey(e, aid, handler, materialised)
    return e.load(handler)


def emit_aid_tail(
    ctx: EmitContext, keys: frozenset[str], materialised: MaterialisedSectionedLayout
) -> None:
    """After a RECEIVE: branch to the handler of the key that ended it, a named key
    before ANYKEY, which never takes ENTER. No handler, or an ignored key, runs on."""
    e = IrEmitter(ctx, None)
    r_index = _emit_chosen_handler(
        e, _emit_eibaid(ctx, materialised), keys, materialised
    )
    proceed = e.label("aid_none")
    e.skip_if(e.binop("<=", r_index, e.int_(0)), proceed)
    _emit_pending(ctx, r_index, materialised)
    e.jump(AID_DISPATCH)
    e.place(proceed)


def _emit_pending(
    ctx: EmitContext, r_index: Register, materialised: MaterialisedSectionedLayout
) -> None:
    ref, region_reg = ctx.resolve_field_ref(_PENDING, materialised)
    ctx.emit_encode_and_write(
        region_reg,
        ref.fl,
        ctx.emit_to_string(r_index),
        ref.offset_reg,
        extent=ref.extent,
    )


def emit_aid_dispatcher(
    ctx: EmitContext,
    handlers: Iterable[tuple[CodeLabel, int]],
    match: HandlerMatch,
    materialised: MaterialisedSectionedLayout,
) -> None:
    """One per program, entered only by an AID tail's branch with DFH-AID-PENDING
    holding a registered handler's index."""
    ctx.emit_inst(Label_(label=AID_DISPATCH))
    ref, region_reg = ctx.resolve_field_ref(_PENDING, materialised)
    r_index = ctx.emit_decode_field(
        region_reg, ref.fl, ref.offset_reg, extent=ref.extent
    )
    for handler in handlers:
        match(ctx, r_index, handler)
    ctx.emit_inst(Return_())
