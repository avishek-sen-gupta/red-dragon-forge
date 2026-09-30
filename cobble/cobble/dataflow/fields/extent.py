"""A structured ASG operand to the byte extents it denotes.

srccfg's Node carries operand names only, so this reads the typed ASG operand
instead: RefModOperand keeps subscripts and reference modification, and both are
what separate an EXACT extent from a CLAMPED one. Three quarters of the corpus's
subscripted MOVE operands compute their subscript, so CLAMPED is the common case
for a subscripted write, not a corner.

Two things here answer wider than the operand strictly denotes, because
``may_alias`` over-approximates and ``must_cover`` under-approximates, and a
spurious edge costs less than a lost one:

  * Records are laid end to end inside their section's region. layout gives each
    record a coordinate space starting at 0, which is right for one record but
    would put the first ten bytes of every WORKING-STORAGE 01 at one address --
    so a write to one record would ``must_cover``, and therefore KILL, a live
    definition in an unrelated one.

  * Reference modification narrows an EXACT extent only. Slicing inside a CLAMPED
    one would claim to know which occurrence the slice lands in, which is exactly
    what a computed subscript does not know.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from itertools import accumulate, groupby
from operator import add, attrgetter, floordiv, mul, sub
from types import MappingProxyType
from typing import TypeVar

from cobble.dataflow.layout import Cell, Record
from cobble.dataflow.srccfg.literals import FIGURATIVE_CONSTANTS
from cobol_asg.cobol_expression import BinOpNode, ExprNode, LiteralNode
from cobol_asg.ref_mod import (
    FunctionCallOperand,
    RefModBinOp,
    RefModExpr,
    RefModLiteral,
    RefModOperand,
)
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

NO_EXTENT_REASONS = frozenset({"unknown-name", "length-of", "function", "figurative"})

_REGIONS = MappingProxyType(
    {
        "WORKING-STORAGE": RegionId.WORKING_STORAGE,
        "LINKAGE": RegionId.LINKAGE,
        "LOCAL-STORAGE": RegionId.LOCAL_STORAGE,
        "FILE": RegionId.FILE,
    }
)

_ARITHMETIC = MappingProxyType({"+": add, "-": sub, "*": mul, "/": floordiv})

_DeclKey = tuple[str, int]
_Key = TypeVar("_Key", str, tuple[str, int])


@dataclass(frozen=True)
class _Folded:
    """What an integer expression folds to, and whether it folded at all."""

    value: int
    known: bool


_UNFOLDED = _Folded(value=0, known=False)

# A reference-modification length is at least 1 in COBOL, so 0 cannot be one:
# here it stands for the omitted length, which runs to the end of the base.
_TO_END = _Folded(value=0, known=True)


def _literal(text: str) -> _Folded:
    return _Folded(int(text), True) if text.lstrip("+-").isdigit() else _UNFOLDED


def _apply(op: str, left: int, right: int) -> _Folded:
    """A zero divisor abends at run time rather than folding to anything."""
    if op == "/" and right == 0:
        return _UNFOLDED
    return _Folded(_ARITHMETIC[op](left, right), True)


def _combine(op: str, left: _Folded, right: _Folded) -> _Folded:
    foldable = left.known and right.known and op in _ARITHMETIC
    return _apply(op, left.value, right.value) if foldable else _UNFOLDED


def _const(node: ExprNode | RefModExpr) -> _Folded:
    """The integer an expression folds to, when it needs no runtime state."""
    match node:
        case LiteralNode(value=text) | RefModLiteral(value=text):
            return _literal(text)
        case BinOpNode(op=op, left=left, right=right) | RefModBinOp(
            op=op, left=left, right=right
        ):
            return _combine(op, _const(left), _const(right))
        case _:
            return _UNFOLDED


@dataclass(frozen=True)
class _Placement:
    """Where one record sits in its section's region buffer."""

    region: RegionId
    base: int


def _decl_key(cell: Cell) -> _DeclKey:
    """A declaration is numbered per record, so the record name is part of it."""
    return (cell.record, cell.decl)


def _name_key(cell: Cell) -> str:
    return cell.name.upper()


def _in_path(qualifier: str, path: tuple[str, ...]) -> bool:
    return any(qualifier.upper() == name.upper() for name in path)


def _qualified(cell: Cell, qualifiers: tuple[str, ...]) -> bool:
    """Whether every qualifier of a reference names a group this cell sits under."""
    return all(_in_path(qualifier, cell.path) for qualifier in qualifiers)


def _spans(outer: FieldExtent, inner: FieldExtent) -> bool:
    return (
        outer.region is inner.region
        and outer.start <= inner.start
        and inner.end <= outer.end
    )


@dataclass(frozen=True)
class CellIndex:
    """Every cell a name can denote in one program, addressed within its region."""

    by_name: Mapping[str, tuple[Cell, ...]]
    by_decl: Mapping[_DeclKey, tuple[Cell, ...]]
    placements: Mapping[str, _Placement]
    ordered: tuple[Cell, ...]

    def region_of(self, cell: Cell) -> RegionId:
        return self.placements[cell.record].region

    def extent_of(self, cell: Cell) -> FieldExtent:
        """One cell as a byte range in its region, not in its own record."""
        placement = self.placements[cell.record]
        return FieldExtent(
            region=placement.region,
            start=placement.base + cell.start,
            length=cell.length,
            precision=Precision.EXACT,
            field_name=cell.name,
        )

    def cells_named(
        self, name: str, qualifiers: tuple[str, ...], arity: int
    ) -> tuple[Cell, ...]:
        """Every cell ``name`` can denote when written with ``arity`` subscripts."""
        return tuple(
            cell
            for cell in self.by_name.get(name.upper(), ())
            if len(cell.index) == arity and _qualified(cell, qualifiers)
        )

    def occurrences_of(self, cell: Cell) -> tuple[Cell, ...]:
        """Every occurrence of the declaration ``cell`` is one occurrence of."""
        return self.by_decl[_decl_key(cell)]

    def containing(self, extent: FieldExtent) -> tuple[Cell, ...]:
        """The cells that fully contain this extent, group or elementary."""
        return tuple(
            cell for cell in self.ordered if _spans(self.extent_of(cell), extent)
        )

    def within(self, extent: FieldExtent) -> tuple[Cell, ...]:
        """The cells this extent fully contains, in record order."""
        return tuple(
            cell for cell in self.ordered if _spans(extent, self.extent_of(cell))
        )

    def elementary_within(self, extent: FieldExtent) -> tuple[Cell, ...]:
        """The same, less the groups: the bytes' own owners, counted once each."""
        return tuple(cell for cell in self.within(extent) if not cell.is_group)


def _grouped(
    cells: tuple[Cell, ...], key: Callable[[Cell], _Key]
) -> Mapping[_Key, tuple[Cell, ...]]:
    ordered = sorted(cells, key=key)
    return MappingProxyType(
        {value: tuple(group) for value, group in groupby(ordered, key=key)}
    )


def _region_placements(
    records: tuple[Record, ...],
) -> tuple[tuple[str, _Placement], ...]:
    """One section's records laid end to end, each at its own base offset."""
    region = _REGIONS[records[0].origin]
    bases = accumulate((record.size for record in records), initial=0)
    return tuple(
        (record.name, _Placement(region, base))
        for record, base in zip(records, bases, strict=False)
    )


def _placements(records: tuple[Record, ...]) -> Mapping[str, _Placement]:
    """Every record's address, grouped by section because a region is a section."""
    return MappingProxyType(
        dict(
            entry
            for _, section in groupby(records, key=attrgetter("origin"))
            for entry in _region_placements(tuple(section))
        )
    )


def cell_index(records: tuple[Record, ...]) -> CellIndex:
    """Every cell in one program, under the two handles a reference gives us."""
    cells = tuple(cell for record in records for cell in record.cells)
    return CellIndex(
        by_name=_grouped(cells, _name_key),
        by_decl=_grouped(cells, _decl_key),
        placements=_placements(records),
        ordered=cells,
    )


@dataclass(frozen=True)
class OperandExtents:
    """The extents an operand denotes, or why it denotes none."""

    extents: tuple[FieldExtent, ...] = ()
    reason: str = ""


def _spanning(cells: tuple[Cell, ...], index: CellIndex, name: str) -> FieldExtent:
    extents = tuple(index.extent_of(cell) for cell in cells)
    start = min(extent.start for extent in extents)
    end = max(extent.end for extent in extents)
    return replace(
        extents[0],
        start=start,
        length=end - start,
        precision=Precision.CLAMPED,
        field_name=name,
    )


def _one_per_declaration(candidates: tuple[Cell, ...]) -> tuple[Cell, ...]:
    return tuple({_decl_key(cell): cell for cell in candidates}.values())


def _clamped(
    name: str, candidates: tuple[Cell, ...], index: CellIndex
) -> tuple[FieldExtent, ...]:
    """One extent per declaration, spanning every occurrence of it.

    A variable subscript picks some occurrence and nothing here knows which, so
    the extent covers all of them at CLAMPED -- which can never kill a definition.
    """
    return tuple(
        _spanning(index.occurrences_of(first), index, name)
        for first in _one_per_declaration(candidates)
    )


def _selected(
    subscripts: tuple[ExprNode, ...], candidates: tuple[Cell, ...], index: CellIndex
) -> tuple[FieldExtent, ...]:
    """The occurrence constant subscripts name, or nothing if they do not fold."""
    folded = tuple(_const(subscript) for subscript in subscripts)
    if not all(entry.known for entry in folded):
        return ()
    wanted = tuple(entry.value for entry in folded)
    return tuple(index.extent_of(c) for c in candidates if c.index == wanted)


def _base_extents(
    operand: RefModOperand, candidates: tuple[Cell, ...], index: CellIndex
) -> tuple[FieldExtent, ...]:
    """The extents before reference modification narrows them.

    Constant subscripts that select no cell fall back to the clamped whole table
    rather than to nothing: the subscript is out of range for what this program
    declares, and answering "no extent" there would drop a real dependency.
    """
    if not operand.subscripts:
        return tuple(index.extent_of(cell) for cell in candidates)
    selected = _selected(operand.subscripts, candidates, index)
    return selected if selected else _clamped(operand.name, candidates, index)


def _narrowed(extent: FieldExtent, start: int, size: int) -> FieldExtent:
    absolute = extent.start + start - 1
    remainder = extent.end - absolute
    return replace(extent, start=absolute, length=remainder if size == 0 else size)


def _slice_length(operand: RefModOperand) -> _Folded:
    match operand.ref_mod_length:
        case None:
            return _TO_END
        case length:
            return _const(length)


def _ref_modified(
    extent: FieldExtent, start_of: RefModExpr, size: _Folded
) -> FieldExtent:
    """COBOL reference modification is 1-based: WS-F(2:3) starts one byte in.

    Only an EXACT extent narrows. A CLAMPED base already stands for every
    occurrence a computed subscript could reach, and slicing inside it would
    claim to know which one; a non-constant start or length knows even less. Both
    therefore keep the whole base extent, at CLAMPED.
    """
    match (extent.precision, _const(start_of), size):
        case (Precision.EXACT, _Folded(known=True) as start, _Folded(known=True)):
            return _narrowed(extent, start.value, size.value)
        case _:
            return replace(extent, precision=Precision.CLAMPED)


def _sliced(
    extents: tuple[FieldExtent, ...], operand: RefModOperand
) -> tuple[FieldExtent, ...]:
    match operand.ref_mod_start:
        case None:
            return extents
        case start_of:
            size = _slice_length(operand)
            return tuple(_ref_modified(extent, start_of, size) for extent in extents)


def _unresolved_reason(name: str) -> str:
    """A figurative constant resolves to no field, and that is not a defect."""
    return "figurative" if name.upper() in FIGURATIVE_CONSTANTS else "unknown-name"


def _field_extents(operand: RefModOperand, index: CellIndex) -> OperandExtents:
    if operand.length_of:
        return OperandExtents(reason="length-of")
    candidates = index.cells_named(
        operand.name, operand.qualifiers, len(operand.subscripts)
    )
    if not candidates:
        return OperandExtents(reason=_unresolved_reason(operand.name))
    base = _base_extents(operand, candidates, index)
    return OperandExtents(extents=_sliced(base, operand))


def _every_occurrence(
    candidates: tuple[Cell, ...], index: CellIndex
) -> tuple[FieldExtent, ...]:
    return tuple(
        index.extent_of(occurrence)
        for cell in _one_per_declaration(candidates)
        for occurrence in index.occurrences_of(cell)
    )


def operand_occurrence_extents(
    operand: RefModOperand, index: CellIndex
) -> tuple[FieldExtent, ...]:
    """One EXACT extent per occurrence an operand could denote.

    Deliberately not ``operand_extents``. A computed subscript there yields one
    CLAMPED extent spanning every occurrence -- ``_spanning``'s min(start) to
    max(end) -- which for CDEMO-MENU-OPT-PGMNAME(WS-OPTION) is 11*46+8 bytes and
    covers every row's 35-byte caption and 1-byte user type as well. That span
    exists so a computed subscript can never *kill* a definition, which is a
    write-side concern; reading a value through it would answer 'Account View'
    where a program name was asked for.

    Constant subscripts still select their one occurrence, via the same ``_selected``
    the clamped path falls back from, so a literal index loses no precision here.
    """
    candidates = index.cells_named(
        operand.name, operand.qualifiers, len(operand.subscripts)
    )
    if not candidates:
        return ()
    if not operand.subscripts:
        return _sliced(tuple(index.extent_of(cell) for cell in candidates), operand)
    selected = _selected(operand.subscripts, candidates, index)
    return _sliced(selected or _every_occurrence(candidates, index), operand)


def operand_extents(
    operand: RefModOperand | FunctionCallOperand, index: CellIndex
) -> OperandExtents:
    """The byte extents one MOVE-style operand reads or writes.

    ``LENGTH OF X`` is a compile-time constant rather than a read of X, and an
    intrinsic FUNCTION's result lives nowhere addressable, so both denote no
    extent and say which of ``NO_EXTENT_REASONS`` applies.
    """
    match operand:
        case FunctionCallOperand():
            return OperandExtents(reason="function")
        case _:
            return _field_extents(operand, index)
