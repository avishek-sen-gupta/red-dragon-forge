"""The values cobble's fixpoint gives storage, as rows: what WORKING-STORAGE holds before any statement runs, and what each CFG node's writes put in their bytes."""

from collections.abc import Mapping

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.transfer import Statement, carried_moves, writes_of
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.layout import Cell, Record
from cobble.experimental.codeql.label import Label
from cobble.experimental.codeql.schema.ast_rows import Rows
from cobble.experimental.codeql.scope import Scope
from cobble.experimental.codeql.trap_row import TrapRow
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

Placed = tuple[Label, int, int]


def initial_rows(records: tuple[Record, ...], scope: Scope) -> Rows:
    """Each cell's region, and the bytes the initial image gives it."""
    return (
        *(
            TrapRow("field_region", (label, scope.index.extent_of(cell).region.value))
            for cell, label in scope.cells.items()
        ),
        *_initial(records, scope),
    )


def _initial(records: tuple[Record, ...], scope: Scope) -> Rows:
    return tuple(
        TrapRow("initial_value", (*at, _text(value)))
        for extent, held in initial_image(records, scope.index).items()
        for at in _placed(extent, scope)
        for value in held.values
    )


def value_rows(
    statements: Mapping[str, Statement], nodes: Mapping[str, Label], scope: Scope
) -> Rows:
    """A write with a value of its own is a literal's, fitted to its bytes; one
    that carries its source's value says from where; any other says why it has
    none. A clamped write's bytes are not located, so it says nothing, and a clamped
    source's bytes are not either: it carries no value, only that a caller owns
    them when they are in LINKAGE."""
    return tuple(
        row
        for node, statement in statements.items()
        if node in nodes
        for row in _node_values(statement, node, nodes[node], scope)
    )


def _node_values(statement: Statement, node: str, label: Label, scope: Scope) -> Rows:
    carried = carried_moves(statement, scope.index)
    targets = frozenset(carry[0] for carry in carried)
    return (
        *(
            TrapRow("cfg_carries", (label, *at, *source, right))
            for target, sources, right in carried
            for at in _placed(target, scope)
            for extent in sources
            for source in _placed(extent, scope)
        ),
        *(
            TrapRow(
                "cfg_value_reason", (label, *at, UnresolvedReason.INBOUND_LINKAGE.value)
            )
            for target, sources, _ in carried
            if any(_unlocated_linkage(extent) for extent in sources)
            for at in _placed(target, scope)
        ),
        *(
            row
            for write in writes_of(statement, node, scope.index)
            if write.target not in targets
            for at in _placed(write.target, scope)
            for row in (
                *(
                    TrapRow("cfg_value", (label, *at, _text(value)))
                    for value in write.values.values
                ),
                *(
                    TrapRow("cfg_value_reason", (label, *at, reason.value))
                    for reason in write.values.reasons
                ),
            )
        ),
    )


def _placed(extent: FieldExtent, scope: Scope) -> tuple[Placed, ...]:
    """The innermost cell holding all of ``extent``, and where in it the bytes lie."""
    if extent.precision is Precision.CLAMPED:
        return ()
    return tuple(
        (scope.cells[cell], extent.start - whole.start, extent.length)
        for cell in _innermost(extent, scope.index)
        for whole in (scope.index.extent_of(cell),)
    )


def _unlocated_linkage(extent: FieldExtent) -> bool:
    return extent.precision is Precision.CLAMPED and extent.region is RegionId.LINKAGE


def _innermost(extent: FieldExtent, index: CellIndex) -> tuple[Cell, ...]:
    return index.containing(extent)[-1:]


def _text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")
