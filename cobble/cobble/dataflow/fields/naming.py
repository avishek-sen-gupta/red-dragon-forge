"""An extent back to the field a reader recognises.

The smallest covering field, so an edge reads a member's name rather than the
whole record's. The tie-break is total on purpose: a group and its only child
span identical bytes, and so do a record and its REDEFINES view, so without a
total order the same extent gets two names between runs.

Naming is deliberately separate from the lattice. This module and ``extent.py``
are the only places cells are touched; the corpus expands to roughly 5.6M of them
(worst member 121,001), and keeping that expansion out of a state keyed on
extents is why the analysis does not pay for OCCURS. Nothing here may be cached
onto a state or an edge.
"""

from __future__ import annotations

from cobble.dataflow.fields.extent import CellIndex
from cobble.dataflow.layout import Cell
from cobol_memory.field_extent import FieldExtent


def _rank(cell: Cell, named: str) -> tuple[int, int, int, int, str]:
    """Smallest first, then the word the statement used, then deepest, then
    most-qualified, then by name.

    Every component after the length exists to break a tie that real layouts
    produce, and the name is last so the order is total even between two cells
    that agree on all of it.

    ``named`` ranks below the length rather than above it. A whole-field reference
    puts the referenced cell in the minimum-length group automatically -- nothing
    containing an extent is shorter than it -- so it wins its tie without being
    promoted. A reference-modified operand is why promoting it would be wrong:
    ``SRC-REC(2:3)`` names an eight-byte record for three bytes, and a smaller
    field covering those three should still be preferred.
    """
    return (
        cell.length,
        0 if cell.name.upper() == named.upper() else 1,
        -cell.level,
        -len(cell.path),
        cell.name,
    )


def smallest_covering(extent: FieldExtent, index: CellIndex) -> str:
    """The narrowest declared field whose bytes contain ``extent``.

    An extent no field covers -- one straddling two members, say -- keeps the name
    it arrived with rather than being widened to whatever group does contain it.

    Where several declared names own identical bytes, the one the statement itself
    wrote wins. A record and a same-sized REDEFINES child of it tie on length, and
    without this the deeper alias took the name, so an edge's endpoint id spelled a
    field the statement being described never mentioned. Consumers join on that id.
    ``fields.query.overlapping`` is how a reader recovers the other names over the
    same bytes; this decides only which of them the artefact keys on.
    """
    covering = index.containing(extent)
    if not covering:
        return extent.field_name
    return min(covering, key=lambda cell: _rank(cell, extent.field_name)).name
