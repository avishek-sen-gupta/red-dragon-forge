"""What reaches an extent, and how a write changes it.

The governing asymmetry is cobol_memory's: a read matches by ``may_alias``, which
over-approximates, so provenance survives when overlap is uncertain; a write kills
only where ``must_cover`` holds, which under-approximates, so a CLAMPED extent --
a computed subscript -- adds provenance without ever removing any. Getting that
round the wrong way would drop real edges rather than keep spurious ones, and a
dropped edge is invisible in the output.

A state is keyed by extent rather than by field name because a name is not an
address: two names over one piece of storage are one key here, which is the whole
reason for working in bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import reduce
from types import MappingProxyType

from cobble.dataflow.fields.values import (
    EMPTY as VALUES_EMPTY,
)
from cobble.dataflow.fields.values import (
    UnresolvedReason,
    ValueSet,
    because,
    merged,
)
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

LITERAL = "LITERAL"
CICS_STATE = "%CICS-STATE"

# A value that came from outside the program's storage -- a literal, a file, a
# callee -- has an origin instead of an extent. Zero length is what makes this
# safe to carry in an extent-shaped slot: both may_alias and must_cover reject a
# non-positive length, so it can never alias real storage or kill a definition.
NOWHERE = FieldExtent(
    region=RegionId.SPECIAL_REGISTERS,
    start=0,
    length=0,
    precision=Precision.CLAMPED,
    field_name="",
)


@dataclass(frozen=True)
class Source:
    """Where a value came from: another extent, or a synthetic origin.

    ``origin`` is empty exactly when ``extent`` is real storage, and ``extent`` is
    ``NOWHERE`` exactly when ``origin`` names one. ``node`` is the CFG node id that
    wrote it, which is how a reader recovers the guard conditions this lattice
    deliberately does not carry.
    """

    origin: str
    extent: FieldExtent
    node: str


_NO_SOURCES: Mapping[FieldExtent, frozenset[Source]] = MappingProxyType({})
_NO_VALUES: Mapping[FieldExtent, ValueSet] = MappingProxyType({})


@dataclass(frozen=True)
class State:
    """What reaches each extent, and what each extent can hold.

    One object rather than two maps threaded side by side, because both are killed
    by the same ``must_cover`` rule and a value that outlived the provenance of the
    write that placed it would be a value the program cannot hold. Joining one and
    forgetting the other has to be impossible, not merely discouraged.
    """

    sources: Mapping[FieldExtent, frozenset[Source]] = _NO_SOURCES
    values: Mapping[FieldExtent, ValueSet] = _NO_VALUES


EMPTY = State()


def _joined_sources(
    left: Mapping[FieldExtent, frozenset[Source]],
    right: Mapping[FieldExtent, frozenset[Source]],
) -> Mapping[FieldExtent, frozenset[Source]]:
    union_extents = (*left, *(extent for extent in right if extent not in left))
    return MappingProxyType(
        {
            extent: left.get(extent, frozenset()) | right.get(extent, frozenset())
            for extent in union_extents
        }
    )


def _joined_values(
    left: Mapping[FieldExtent, ValueSet], right: Mapping[FieldExtent, ValueSet]
) -> Mapping[FieldExtent, ValueSet]:
    union_extents = (*left, *(extent for extent in right if extent not in left))
    return MappingProxyType(
        {
            extent: merged(
                left.get(extent, VALUES_EMPTY), right.get(extent, VALUES_EMPTY)
            )
            for extent in union_extents
        }
    )


def join(left: State, right: State) -> State:
    """Union of both components, extent by extent. Order does not matter."""
    return State(
        sources=_joined_sources(left.sources, right.sources),
        values=_joined_values(left.values, right.values),
    )


def write(
    state: State,
    target: FieldExtent,
    sources: frozenset[Source],
    values: ValueSet = VALUES_EMPTY,
) -> State:
    """``sources`` and ``values`` reach ``target``; whatever it must_covers stops.

    An EXACT target must_covers itself, so it drops its own prior entry in both maps
    -- a strong update. A CLAMPED one covers nothing, so both are kept and this is a
    weak update. The two components are filtered by one predicate on purpose.
    """
    kept_sources = {
        extent: held
        for extent, held in state.sources.items()
        if not target.must_cover(extent)
    }
    kept_values = {
        extent: held
        for extent, held in state.values.items()
        if not target.must_cover(extent)
    }
    return State(
        sources=MappingProxyType(
            {
                **kept_sources,
                target: kept_sources.get(target, frozenset()) | sources,
            }
        ),
        values=MappingProxyType(
            {
                **kept_values,
                target: merged(kept_values.get(target, VALUES_EMPTY), values),
            }
        ),
    )


def reaching(state: State, read: FieldExtent) -> frozenset[Source]:
    """Every source held at an extent this read might overlap."""
    return frozenset(
        source
        for extent, sources in state.sources.items()
        if read.may_alias(extent)
        for source in sources
    )


def _sliced(held: ValueSet, extent: FieldExtent, read: FieldExtent) -> ValueSet:
    at = read.start - extent.start
    return ValueSet(
        values=frozenset(value[at : at + read.length] for value in held.values),
        reasons=held.reasons,
    )


def values_at(state: State, read: FieldExtent) -> ValueSet:
    """Every value the bytes at ``read`` can hold, sliced out of what holds them.

    Matched by byte range and not by extent identity, because two names over one
    piece of storage are two extents differing only in ``field_name`` -- the image
    files a value under the FILLER that declares it and a program reads it through
    the REDEFINES, and those are not equal extents.

    A read wholly inside a wider valued extent is sliced out of it, which is what
    makes a reference-modified read resolvable. A read straddling two valued extents
    is inside neither and yields no value at all: composing bytes from two unrelated
    literals would produce a plausible name the program can never hold, and a wrong
    answer here becomes a wrong edge in the graph.
    """
    found = tuple(
        _sliced(held, extent, read)
        for extent, held in state.values.items()
        if extent.region is read.region
        and extent.start <= read.start
        and read.end <= extent.end
    )
    if not found:
        return because(UnresolvedReason.UNINITIALISED)
    return reduce(merged, found, VALUES_EMPTY)
