"""Cross-checks that the byte extents in ``layout`` are the ones the compiler used.

Nothing downstream of ``layout`` can be trusted further than its offsets are, and
the offsets rest on two independent computations that have to agree:

  * the ProLeap bridge's, which assigns each field its ``offset`` within its
    parent, and
  * this package's ``_storage_bytes`` / ``_group_unit``, which says how wide each
    field is.

They are independent, so their agreement is evidence. Two adjacent siblings must
sit exactly ``width(left)`` apart; where they do not, one of the two is wrong and
``record_gaps`` names the pair. The same check doubles as the length-equality
assertion REDEFINES canonicalisation needs, because a redefinition shorter than
what it redefines leaves the field after it looking mis-placed.

The third oracle is external and lives in ``record_length_comment``: 337
layout members document their own size in a header comment, written by
whoever maintained the copybook and never derived from either computation above.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import reduce

from cobble.dataflow.layout import Cell, Record

# "*    RECORD LENGTH : 0120 CHARS", with the spacing and zero-padding varying
# across members.
_RECORD_LENGTH = re.compile(r"RECORD\s+LENGTH\s*:?\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Gap:
    """Two adjacent siblings the bridge and this package do not place identically."""

    record: str
    parent: str
    left: str
    right: str
    left_end: int
    right_start: int


def record_length_comment(source: str) -> int:
    """The size a copybook documents for itself, or 0 when it documents none."""
    match = _RECORD_LENGTH.search(source)
    return int(match.group(1)) if match else 0


def _parents(cells: tuple[Cell, ...]) -> tuple[int, ...]:
    """Every group that has children under it, in declaration order.

    Keyed on position rather than qualified name: a record may declare the same
    group name twice, and merging the two subtrees would compare a field against a
    sibling it has no storage relationship with.
    """
    return tuple(dict.fromkeys(c.parent for c in cells if c.parent >= 0))


def _extent(cell: Cell) -> int:
    """Where the next sibling starts: past *all* of this field's occurrences.

    A cell measures one occurrence, so an OCCURS 190 item of 52 bytes ends at 137
    while the field after it starts at 9965. Only ever asked of a first occurrence,
    where start + every row is the field's own storage.
    """
    return cell.start + max(cell.occurs, 1) * cell.length


def _pair_gap(left: Cell, right: Cell) -> tuple[Gap, ...]:
    """The disagreement between a field and the plain sibling before it."""
    left_end, right_start = _extent(left), right.start
    if left_end == right_start:
        return ()
    return (
        Gap(
            record=left.record,
            parent=".".join(left.path[:-1]),
            left=left.name,
            right=right.name,
            left_end=left_end,
            right_start=right_start,
        ),
    )


def _step(
    acc: tuple[tuple[Cell, ...], tuple[Gap, ...]], right: Cell
) -> tuple[tuple[Cell, ...], tuple[Gap, ...]]:
    """One step along a group's children: the last plain sibling, and the gaps.

    A REDEFINES item is skipped on both sides of the comparison. Its own offset is
    derived by ``layout._place`` rather than read from the bridge, so it is no
    longer independent evidence; and the field after it follows the item it
    redefines, not the redefinition, so it must be measured against the last
    sibling that allocated storage.
    """
    previous, gaps = acc
    if right.redefines:
        return previous, gaps
    return (right,), gaps + tuple(
        g for left in previous for g in _pair_gap(left, right)
    )


def _group_gaps(group: tuple[Cell, ...]) -> tuple[Gap, ...]:
    _, gaps = reduce(_step, group, ((), ()))
    return gaps


def record_gaps(record: Record) -> tuple[Gap, ...]:
    """Every field in ``record`` the bridge did not place where its width implies.

    Only first occurrences are compared. Whether siblings tile their group is a fact
    about the declaration, and layout materialises every occurrence, so checking all
    of them would do 728x the work to report each disagreement 728 times.
    """
    cells = tuple(c for c in record.cells if c.is_first)
    groups = (
        tuple(c for c in cells if c.parent == parent) for parent in _parents(cells)
    )
    return tuple(gap for group in groups for gap in _group_gaps(group))
