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
from types import MappingProxyType

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


State = Mapping[FieldExtent, frozenset[Source]]

EMPTY: State = MappingProxyType({})


def join(left: State, right: State) -> State:
    """Union of provenance, extent by extent. Order does not matter."""
    keys = (*left, *(extent for extent in right if extent not in left))
    return MappingProxyType(
        {
            extent: left.get(extent, frozenset()) | right.get(extent, frozenset())
            for extent in keys
        }
    )


def write(state: State, target: FieldExtent, sources: frozenset[Source]) -> State:
    """``sources`` reach ``target``, and whatever ``target`` must_covers stops doing.

    An EXACT target must_covers itself, so it drops its own prior provenance -- a
    strong update. A CLAMPED one covers nothing, so its prior provenance is kept
    and this is a weak update.
    """
    survivors = {
        extent: held for extent, held in state.items() if not target.must_cover(extent)
    }
    return MappingProxyType(
        {**survivors, target: survivors.get(target, frozenset()) | sources}
    )


def reaching(state: State, read: FieldExtent) -> frozenset[Source]:
    """Every source held at an extent this read might overlap."""
    return frozenset(
        source
        for extent, sources in state.items()
        if read.may_alias(extent)
        for source in sources
    )
