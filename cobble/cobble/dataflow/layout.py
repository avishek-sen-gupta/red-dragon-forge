"""Byte extents for every field in a program's records.

This is the substrate field-level dataflow runs on. A MOVE in COBOL does not
copy a *name*, it copies a byte range: ``MOVE REC1-NAME-PERSON(1:35) TO
WS-COMM-NAME-PERSON(WS-IDX)`` moves 35 of the 66 bytes at LAYOUT1 offset 48 into
35 bytes somewhere in REC2's user-summary table. Nothing about that is
recoverable from the two names, so every later analysis phase is stated over
``Cell`` -- (start, length) within one record -- and never over names.

Two things the bridge gives us are deliberately NOT used as-is:

  * ``CobolField.offset`` on a level-01 item is cumulative across the whole
    section (DFHBMSCA at 0, the next 01 at 16, the one after at 10016). That is
    an artefact of how the section is allocated and nothing a MOVE can observe,
    since no reference reaches from one 01 into an unrelated one. Each record
    therefore starts its own coordinate space at 0. The exception is an 01 that
    REDEFINES another: those two share storage, so they share one space and form
    a single ``Record`` between them -- see ``_cluster``.

  * ``CobolTypeDescriptor.char_positions`` is the width the value has when
    written in DISPLAY, so it is the storage width only for DISPLAY items --
    see ``_storage_bytes``.

OCCURS is expanded. Every occurrence gets its own cell at its own offset, so a
190-row table of 8 fields is 1520 cells and there is exactly one coordinate space
per record. Measured over 300 programs that costs 2.1x the declared field count --
701472 cells in all, the largest single record holding 10595 -- because nine
records in ten declare no table at all. Keeping one row and striding into it saves
nothing worth the second coordinate space it introduces: with one flat space,
REDEFINES needs no reconciling, since two names over one piece of storage are just
two cells with overlapping ranges.

A reference with a literal subscript then picks the cell whose ``index`` matches,
and one with a variable subscript -- ``WS-IDX`` above -- picks every cell sharing a
``decl``. No model can do better on the second: nothing here knows WS-IDX.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import reduce
from operator import attrgetter
from types import MappingProxyType

from cobol_asg.asg_types import CobolASG, CobolField
from cobol_asg.cobol_types import CobolDataCategory, CobolTypeDescriptor

# COMP is allocated by digit count, not by digit count in bytes: up to 4 digits
# is a halfword, up to 9 a fullword, up to 18 a doubleword, and beyond that only
# under ARITH(EXTEND).
_BINARY_BYTES = ((4, 2), (9, 4), (18, 8), (31, 16))

_FIXED_WIDTH = MappingProxyType(
    {CobolDataCategory.COMP1: 4, CobolDataCategory.COMP2: 8}
)

# Where a record can live, and the ASG attribute holding that section's roots.
_SECTIONS = (
    ("WORKING-STORAGE", attrgetter("data_fields")),
    ("LINKAGE", attrgetter("linkage_fields")),
    ("LOCAL-STORAGE", attrgetter("local_storage_fields")),
    ("FILE", attrgetter("file_fields")),
)


class UnsizeableFieldError(Exception):
    """A field whose storage width this module cannot compute."""


def _binary_bytes(digits: int) -> int:
    match [size for limit, size in _BINARY_BYTES if digits <= limit]:
        case [size, *_]:
            return size
        case _:
            raise UnsizeableFieldError(
                f"COMP with {digits} digits exceeds the 31-digit maximum"
            )


def _storage_bytes(descriptor: CobolTypeDescriptor) -> int:
    """Bytes the field occupies in the record, which is not its character count.

    A COMP-3 field packs two digits per byte plus a sign nibble, and a COMP
    field is sized by digit count; taking ``char_positions`` for either would
    mis-place every following field in the record. DISPLAY is the one case where
    the two coincide, and ``char_positions`` already carries the extra byte a
    SIGN IS SEPARATE clause adds.
    """
    match descriptor.category:
        case CobolDataCategory.COMP3:
            return (descriptor.total_digits + 2) // 2
        case CobolDataCategory.BINARY:
            return _binary_bytes(descriptor.total_digits)
        case _:
            return _FIXED_WIDTH.get(descriptor.category, descriptor.char_positions)


@dataclass(frozen=True)
class _Sized:
    """A field with its width and its resolved offset already worked out.

    A group's width depends on its children and a child's offset depends on its
    siblings, so both are settled in one bottom-up pass over this mirror of the
    field tree. Asking each cell for its own width instead re-walks that cell's
    whole subtree once per ancestor, which is quadratic in a deep record and made
    a 300-program measurement take minutes.

    ``unit`` is one occurrence, ``total`` all of them, and ``offset`` is relative
    to the parent with REDEFINES already collapsed. ``decl`` numbers the
    declaration, which every occurrence of it goes on to share.
    """

    field: CobolField
    unit: int
    total: int
    offset: int
    children: tuple[_Sized, ...]
    decl: int = -1


def _place(placed: tuple[_Sized, ...], node: _Sized) -> tuple[_Sized, ...]:
    """``node`` given the offset it really starts at among the siblings before it.

    REDEFINES allocates no storage: the redefining item begins where the item it
    redefines begins. The bridge resolves one hop of that, but places a
    redefinition OF a redefinition sequentially instead, as though it were a new
    field -- 28 of the 36 chained cases in a 300-program sample land at the wrong
    offset, one of them 3500 bytes past where the compiler puts it. Chains need no
    special handling here, because the item being redefined must precede this one
    and so has already been placed.

    The search runs backwards because REDEFINES names the *nearest* preceding item
    with that name, and a record may declare the same name more than once.
    """
    if not node.field.redefines:
        return (*placed, node)
    target = node.field.redefines.upper()
    base = next(
        (p.offset for p in reversed(placed) if p.field.name.upper() == target),
        node.offset,
    )
    return (*placed, replace(node, offset=base))


def _group_unit(field: CobolField, placed: tuple[_Sized, ...]) -> int:
    """Bytes one occurrence of a field spans.

    A group is as wide as its furthest-reaching child, redefinitions included: a
    redefinition may legally be longer than what it redefines (REC1-NUM-OUTPUT is
    7866 bytes over a 3966-byte target), and the compiler has to allocate for the
    longest view or a MOVE into it would write past the end of the record.
    """
    if not placed:
        return _storage_bytes(field.type_descriptor)
    return max(p.offset + p.total for p in placed)


def _sized(field: CobolField) -> _Sized:
    placed = reduce(_place, map(_sized, field.children), ())
    unit = _group_unit(field, placed)
    return _Sized(
        field=field,
        unit=unit,
        total=unit * max(field.occurs, 1),
        offset=field.offset,
        children=placed,
    )


def _declare(
    acc: tuple[tuple[_Sized, ...], int], node: _Sized
) -> tuple[tuple[_Sized, ...], int]:
    """Pre-order declaration numbers over a sized tree, and the next free number.

    Numbered on the declaration rather than the occurrence, because that is the
    handle a variable subscript needs: ``WS-ERR-MSG(WS-IND)`` is every cell sharing
    one ``decl``, and there is no way to narrow it further.
    """
    numbered, nid = acc
    kids, after = reduce(_declare, node.children, ((), nid + 1))
    return (*numbered, replace(node, decl=nid, children=kids)), after


def _declared(node: _Sized) -> _Sized:
    """``node``'s tree with every declaration numbered."""
    (numbered,), _ = _declare(((), 0), node)
    return numbered


@dataclass(frozen=True)
class Cell:
    """One occurrence of one field, as a byte range in its record.

    ``start`` is absolute within the record and ``length`` covers this occurrence
    only, so WS-COMM-NAME-PERSON is 35 bytes at 92, and again at 144, and 188 more
    times after that -- each its own cell. A group's length spans all of its
    children including their occurrences, so WS-MSG-TAB is the whole 56784 bytes
    while the WS-MSG-DETAIL under it is 78.

    Identity is positional, not nominal. ``path`` is NOT unique: PROGA declares
    REC1-NUM-DATA-FLAT twice with different children, which COBOL permits so long
    as references qualify. What distinguishes cells:

      ``decl``     which declaration this came from, shared by every occurrence
      ``index``    which occurrence, 1-based, one entry per enclosing table
      ``ordinal``  position in the record's materialised cell sequence
      ``parent``   ``ordinal`` of the enclosing group's matching occurrence

    ``index`` is also the arity of a reference: its length is how many subscripts
    naming this cell requires, so WS-ERR-MSG has ``(47,)`` and RECA-NUM-AMT
    ``(3, 7)``.

    ``occurs`` keeps the declared count on every occurrence rather than dropping to
    1, so ``start + occurs * length`` on a first occurrence still recovers all the
    storage the declaration owns -- which is where the next sibling begins.
    """

    record: str
    name: str
    path: tuple[str, ...]
    start: int
    length: int
    level: int
    pic: str
    usage: str
    redefines: str
    occurs: int
    value: str = ""
    value_is_figurative: bool = False
    index: tuple[int, ...] = ()
    decl: int = -1
    ordinal: int = -1
    parent: int = -1

    @property
    def end(self) -> int:
        return self.start + self.length

    @property
    def is_group(self) -> bool:
        return not self.pic

    @property
    def is_first(self) -> bool:
        """Whether this is occurrence 1 at every level.

        One cell per declaration, which is what a check on the *declaration* -- a
        field's width, or whether siblings tile their group -- wants to run over.
        """
        return all(i == 1 for i in self.index)


@dataclass(frozen=True)
class Record:
    """One piece of storage and every field addressing it.

    Usually that is a single level-01 item. Where one 01 REDEFINES another they
    describe the same bytes, so both label sets land in the same record and
    ``name`` is the first of them; ``cells`` then holds more than one level-01
    entry, each still the root of its own qualification path.
    """

    name: str
    origin: str
    size: int
    cells: tuple[Cell, ...]


_Cells = tuple[Cell, ...]


def _occurrence(
    cells: _Cells,
    node: _Sized,
    record: str,
    path: tuple[str, ...],
    start: int,
    index: tuple[int, ...],
    parent: int,
) -> _Cells:
    """One occurrence of ``node``, followed by its children under that occurrence.

    The children have to be walked per occurrence rather than once, because each
    occurrence puts them at different offsets -- that is the whole content of
    OCCURS.
    """
    ordinal = len(cells)
    here = (
        *cells,
        Cell(
            record=record,
            name=node.field.name,
            path=path,
            start=start,
            length=node.unit,
            level=node.field.level,
            pic=node.field.pic,
            usage=node.field.usage,
            redefines=node.field.redefines,
            occurs=node.field.occurs,
            value=node.field.value,
            value_is_figurative=node.field.value_is_figurative,
            index=index,
            decl=node.decl,
            ordinal=ordinal,
            parent=parent,
        ),
    )
    return reduce(
        lambda seen, kid: _walk(
            seen, kid, record, path, start + kid.offset, index, ordinal
        ),
        node.children,
        here,
    )


def _walk(
    cells: _Cells,
    node: _Sized,
    record: str,
    path: tuple[str, ...],
    base: int,
    index: tuple[int, ...],
    parent: int,
) -> _Cells:
    """``node`` materialised: one cell per occurrence, each with its own subtree.

    Occurrence ``i`` starts ``i * unit`` past the first, one row's width and the
    distance to the next row being the same number. (They would diverge under
    SYNCHRONIZED, which inserts slack between occurrences; the bridge does not
    report slack and the measured corpus declares no SYNC item.)

    A field that does not OCCURS is one occurrence that adds nothing to ``index``,
    so it needs no separate path through here.
    """
    here = (*path, node.field.name)
    return reduce(
        lambda seen, i: _occurrence(
            seen,
            node,
            record,
            here,
            base + i * node.unit,
            (*index, i + 1) if node.field.occurs else index,
            parent,
        ),
        range(max(node.field.occurs, 1)),
        cells,
    )


def record_cells(root: CobolField) -> _Cells:
    """Every field under one level-01 item, one cell per occurrence.

    In declaration order, depth first, with each occurrence's subtree following it,
    so a cell's ``parent`` is always already present when it is emitted.
    """
    return _walk((), _declared(_sized(root)), root.name, (), 0, (), -1)


_Cluster = tuple[CobolField, ...]


def _cluster(clusters: tuple[_Cluster, ...], root: CobolField) -> tuple[_Cluster, ...]:
    """The section's level-01 items grouped by the storage they share.

    An 01 REDEFINES makes two 01s describe one piece of memory, so they cannot be
    two records: a MOVE through either name has to be visible to a read through the
    other, and separate coordinate spaces lose that. Every 01 in a chain joins the
    cluster of the item it names, since REDEFINES is transitive over storage.
    """
    target = root.redefines.upper()
    at = next(
        (
            i
            for i in reversed(range(len(clusters)))
            if any(r.name.upper() == target for r in clusters[i])
        ),
        -1,
    )
    if at < 0:
        return (*clusters, (root,))
    return (*clusters[:at], (*clusters[at], root), *clusters[at + 1 :])


def _absorb(cells: _Cells, more: _Cells) -> _Cells:
    """Another 01's fields, added to the coordinate space they redefine.

    Both label sets start at offset 0 -- REDEFINES means "begins where that item
    begins", and the item it names begins at 0 of its own space -- so nothing has to
    be shifted, only renumbered.

    The head widens to the longer view. ERRMSG spells 414 PIC X(78) literals but
    declares OCCURS 518 over them, so the compiler allocates 40404 bytes while the
    literal side measures 32292; leaving the head at 32292 would put a write to row
    500 past the end of its own record.
    """
    first, decls = len(cells), max(c.decl for c in cells) + 1
    joined = tuple(
        replace(
            c,
            record=cells[0].record,
            decl=c.decl + decls,
            ordinal=c.ordinal + first,
            parent=c.parent + first if c.parent >= 0 else -1,
        )
        for c in more
    )
    widest = replace(cells[0], length=max(cells[0].length, more[0].length))
    return (widest, *cells[1:], *joined)


def _record(cluster: _Cluster, origin: str) -> Record:
    cells = reduce(_absorb, map(record_cells, cluster[1:]), record_cells(cluster[0]))
    return Record(
        name=cluster[0].name,
        origin=origin,
        size=cells[0].length,
        cells=cells,
    )


def section_records(origin: str, roots: tuple[CobolField, ...]) -> tuple[Record, ...]:
    """The records one data section declares, its 01 REDEFINES folded together.

    Fewer records than level-01 items whenever the section uses that clause.
    """
    return tuple(_record(cluster, origin) for cluster in reduce(_cluster, roots, ()))


def program_records(asg: CobolASG) -> tuple[Record, ...]:
    """Every record the program declares, across all four data sections."""
    return tuple(
        record
        for origin, roots in _SECTIONS
        for record in section_records(origin, tuple(roots(asg)))
    )
