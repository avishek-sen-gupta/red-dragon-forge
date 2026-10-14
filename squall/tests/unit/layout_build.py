"""A fake VM's declarations: field positions written as the COBOL lowering writes its layout Data."""

from __future__ import annotations

from collections.abc import Mapping

from cobol_asg.cobol_types import CobolDataCategory, CobolTypeDescriptor
from interpreter.cobol.data_layout import FieldLayout
from interpreter.cobol.field_position import FieldPosition
from interpreter.cobol.layout_data import layout_data
from interpreter.instructions import Data


def _field(name: str, position: FieldPosition) -> FieldLayout:
    return FieldLayout(
        name=name,
        type_descriptor=CobolTypeDescriptor(
            category=CobolDataCategory(position.category),
            total_digits=position.total_digits,
            decimal_digits=position.decimal_digits,
            signed=position.signed,
        ),
        offset=position.offset,
        byte_length=position.length,
    )


def declarations(positions: Mapping[str, FieldPosition]) -> tuple[Data, ...]:
    return (layout_data(_field(n, p) for n, p in positions.items()),)
