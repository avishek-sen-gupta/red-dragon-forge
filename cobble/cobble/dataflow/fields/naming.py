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


def _rank(cell: Cell) -> tuple[int, int, int, str]:
    """Smallest first, then deepest, then most-qualified, then by name.

    Every component after the length exists to break a tie that real layouts
    produce, and the name is last so the order is total even between two cells
    that agree on all of it.
    """
    return (cell.length, -cell.level, -len(cell.path), cell.name)


def smallest_covering(extent: FieldExtent, index: CellIndex) -> str:
    """The narrowest declared field whose bytes contain ``extent``.

    An extent no field covers -- one straddling two members, say -- keeps the name
    it arrived with rather than being widened to whatever group does contain it.
    """
    covering = index.containing(extent)
    if not covering:
        return extent.field_name
    return min(covering, key=_rank).name


def covering_fields(extent: FieldExtent, index: CellIndex) -> tuple[str, ...]:
    """Every field the extent touches, smallest first, REDEFINES views included.

    Overlap, not containment: a partial touch is still a touch, which is what
    makes this the answer when alias information is the question rather than a
    single label. Opt-in, because it is one name per aliasing view.
    """
    touched = tuple(
        cell for cell in index.ordered if index.extent_of(cell).may_alias(extent)
    )
    return tuple(dict.fromkeys(cell.name for cell in sorted(touched, key=_rank)))
