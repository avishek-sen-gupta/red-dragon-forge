"""One fixed element of a WORKING-STORAGE table, read or written by a constant subscript."""

from __future__ import annotations

from cobol_asg.cobol_expression import LiteralNode
from interpreter.cobol.emit_context import EmitContext
from interpreter.cobol.sectioned_layout import MaterialisedSectionedLayout
from interpreter.register import Register


def emit_indexed_write(
    ctx: EmitContext,
    name: str,
    index: int,
    value_str_reg: Register,
    materialised: MaterialisedSectionedLayout,
) -> None:
    """emit_copy_back_str deliberately does not thread subscripts, so a handler
    table needs its own path."""
    if not ctx.has_field(name, materialised):
        return
    ref, region_reg = ctx.resolve_field_ref(
        name, materialised, subscripts=(LiteralNode(str(index)),)
    )
    ctx.emit_encode_and_write(
        region_reg, ref.fl, value_str_reg, ref.offset_reg, extent=ref.extent
    )


def emit_indexed_read(
    ctx: EmitContext, name: str, index: int, materialised: MaterialisedSectionedLayout
) -> Register:
    ref, region_reg = ctx.resolve_field_ref(
        name, materialised, subscripts=(LiteralNode(str(index)),)
    )
    return ctx.emit_decode_field(region_reg, ref.fl, ref.offset_reg, extent=ref.extent)
