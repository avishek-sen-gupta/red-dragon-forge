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

# Reasons a missing entry already conveys, so storing them buys nothing.
_UNINFORMATIVE = frozenset(
    {UnresolvedReason.NOT_A_LITERAL, UnresolvedReason.UNINITIALISED}
)


@dataclass(frozen=True, slots=True)
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
    """Every extent from either side, its sources unioned where both hold one.

    Short-circuits on an empty or identical ``right`` return ``left`` itself
    rather than a rebuilt copy, and likewise for an empty ``left`` -- every one
    of these maps is a read-only ``MappingProxyType`` nothing mutates, so handing
    back the same object is safe. ``FieldExtent``'s hash is expensive (two Enum
    fields going through ``Enum.__hash__``), and the old union-then-lookup shape
    hashed every extent three times over the whole union; ``{**left, **right}``
    walks only ``right``'s entries once each.
    """
    if left is right or not right:
        return left
    if not left:
        return right
    return MappingProxyType(
        {
            **left,
            **{
                extent: (left[extent] | held) if extent in left else held
                for extent, held in right.items()
            },
        }
    )


def _joined_values(
    left: Mapping[FieldExtent, ValueSet], right: Mapping[FieldExtent, ValueSet]
) -> Mapping[FieldExtent, ValueSet]:
    """Every extent from either side, its values merged where both hold one.

    Same short-circuits and the same reason as ``_joined_sources``.
    """
    if left is right or not right:
        return left
    if not left:
        return right
    return MappingProxyType(
        {
            **left,
            **{
                extent: merged(left[extent], held) if extent in left else held
                for extent, held in right.items()
            },
        }
    )


def join(left: State, right: State) -> State:
    """Union of both components, extent by extent. Order does not matter.

    ``left is right`` is the fixpoint's own common case -- a node joined against
    itself once its in-state has settled -- and short-circuits before either
    component is touched.
    """
    if left is right:
        return left
    return State(
        sources=_joined_sources(left.sources, right.sources),
        values=_joined_values(left.values, right.values),
    )


def _kept_values(
    state: State, target: FieldExtent, values: ValueSet
) -> Mapping[FieldExtent, ValueSet]:
    """The value map after ``target``'s must_cover kill, or the shared empty map.

    Nothing to store and nothing already held means nothing to build: most
    programs declare no ``VALUE`` clause, and a fresh proxy over an empty
    comprehension on every write would allocate for a map that only ever holds
    nothing.

    The map holds only what a lookup could not otherwise infer. A ``ValueSet``
    with no values whose reasons are all in ``_UNINFORMATIVE`` carries nothing an
    absent entry does not already say: both ``values_at`` and ``exact_values``
    return exactly ``because(NOT_A_LITERAL)``-or-``UNINITIALISED`` on a miss, so a
    non-literal MOVE target and a field-to-field MOVE whose source has no known
    value each restate, at a real map entry, what the absence of that entry would
    already have told the caller. That redundancy is what grew ``state.values``
    to the size of ``state.sources`` and made ``_joined_values`` cost as much as
    ``_joined_sources``. ``FROM_FILE``, ``FROM_CALLEE`` and the rest are not in
    the set, because a miss does not convey any of them -- they are still stored.

    The ``must_cover`` kill runs unconditionally, whether or not anything gets
    stored: a stale value surviving a write that overwrote it would report a
    value the program cannot hold, and that is true whether the new write says
    "not a literal" or says nothing worth a map entry at all.
    """
    worth_storing = bool(values.values) or not values.reasons <= _UNINFORMATIVE
    if not state.values and not worth_storing:
        return _NO_VALUES
    surviving = {
        extent: held
        for extent, held in state.values.items()
        if not target.must_cover(extent)
    }
    if not worth_storing:
        return MappingProxyType(surviving) if surviving else _NO_VALUES
    return MappingProxyType(
        {**surviving, target: merged(surviving.get(target, VALUES_EMPTY), values)}
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
    return State(
        sources=MappingProxyType(
            {
                **kept_sources,
                target: kept_sources.get(target, frozenset()) | sources,
            }
        ),
        values=_kept_values(state, target, values),
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
    if not state.values:
        return because(UnresolvedReason.UNINITIALISED)
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


def exact_values(state: State, read: FieldExtent) -> ValueSet:
    """The values held at exactly ``read``'s own extent, or why there are none.

    One dict hit, for the transfer's hot path: a MOVE asks this once per source
    extent on every statement, and ``values_at``'s containment scan costs
    O(|state.values|) per call, which over a large member's writes is what makes
    the walk quadratic.

    The trade is deliberate. A source read through a different name than the one
    that declared its value -- a redefined table read as CDEMO-MENU-OPT-PGMNAME
    where the value was declared on the FILLER beneath it -- misses here and
    reports UNINITIALISED rather than the value. That aliasing matters at a call
    site, not in a MOVE chain, and ``values_at`` keeps the scan for exactly that.
    """
    return state.values.get(read, because(UnresolvedReason.UNINITIALISED))
