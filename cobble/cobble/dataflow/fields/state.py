"""What reaches an extent, and how a write changes it.

The governing asymmetry is cobol_memory's: a read matches by ``may_alias``, which
over-approximates, so provenance survives when overlap is uncertain; a write kills
provenance only where ``must_cover`` holds, which under-approximates, so a CLAMPED
extent -- a computed subscript -- adds provenance without ever removing any. Getting
that round the wrong way would drop real edges rather than keep spurious ones, and a
dropped edge is invisible in the output.

An EXACT write into part of an EXACT entry splits it (``_split``): the untouched
pieces keep its sources and its values sliced to them, and the overwritten bytes are
the write's alone. Where either side is CLAMPED nothing can be cut, and the value
half is killed further instead: a write that changes part of a valued extent
invalidates the values there without covering the extent, so ``must_cover`` alone
leaves them standing (``_invalidated``). A value is an assertion about bytes and the
graph promotes a site to a proven edge on the strength of one, so a partly
overwritten value kept whole is not caution -- it is a call the program may never
make, asserted as a fact. Doubt is never killed that way: only the values go, and
the reasons stay, because a write says nothing about the bytes outside it.

A join rewrites the EXACT provenance entries of each field name it changed into one
canonical form (``_canonical``): cut at every boundary they have, each piece holding
the union of the sources over it, adjacent pieces with equal sources merged. Two
paths that cut one record differently then land on the same keys for the same
content. Keeping each path's cuts instead let the key set grow with the square of a
record's write boundaries, and large programs stopped settling. Entries of other
names, a child field or a REDEFINES, and CLAMPED entries are left as they are. The
value map is never rewritten so, because ``exact_values`` looks up exactly.

A state is keyed by extent rather than by field name because a name is not an
address: two names over one piece of storage are one key here, which is the whole
reason for working in bytes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache, reduce
from itertools import pairwise
from types import MappingProxyType
from typing import TypeVar

from cobble.dataflow.fields.spans import EVERY_BYTE, Spans, overlaps, union, without
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
_NO_SOURCE_SET: frozenset[Source] = frozenset()
_NO_VALUES: Mapping[FieldExtent, ValueSet] = MappingProxyType({})

# The value of an extent a state has no entry for, told apart by identity alone:
# no state ever stores this object, so ``get`` hands it back only on a miss.
_UNHELD = ValueSet()

# Reasons a missing entry already conveys, so storing them buys nothing.
_UNINFORMATIVE = frozenset(
    {UnresolvedReason.NOT_A_LITERAL, UnresolvedReason.UNINITIALISED}
)


@dataclass(frozen=True, slots=True)
class State:
    """What reaches each extent, and what each extent can hold.

    One object rather than two maps threaded side by side, because a value that
    outlived the provenance of the write that placed it would be a value the
    program cannot hold. Joining one and forgetting the other has to be
    impossible, not merely discouraged.

    The two halves are killed by related but different rules. Both drop what the
    write ``must_cover``s and split an EXACT entry an EXACT write partly
    overwrote. Past that, ``sources`` keeps whatever is left, so an
    over-approximated provenance survives, while ``values`` invalidates what a
    CLAMPED side only partly overwrote, because a value is a claim about bytes and
    a partly overwritten claim is false rather than merely uncertain. See
    ``_split`` and ``_invalidated``.
    """

    sources: Mapping[FieldExtent, frozenset[Source]] = _NO_SOURCES
    values: Mapping[FieldExtent, ValueSet] = _NO_VALUES
    unwritten: Spans = EVERY_BYTE


EMPTY = State()

# Every state the walk holds shares most of its sets, values and keys with its
# neighbours; built anew per join they ran to 200x their distinct count. Each of
# these hands back the first equal object it saw. Bounded, because a worker meets
# member after member and an unbounded table would keep them all.
_SHARED = 1 << 15


@lru_cache(maxsize=_SHARED)
def _shared_sources(held: frozenset[Source]) -> frozenset[Source]:
    return held


@lru_cache(maxsize=_SHARED)
def _shared_value(held: ValueSet) -> ValueSet:
    return held


@lru_cache(maxsize=_SHARED)
def _shared_extent(extent: FieldExtent) -> FieldExtent:
    return extent


def _covers(prior: ValueSet, held: ValueSet) -> bool:
    """Whether merging ``held`` into ``prior`` would add nothing to it."""
    return held.values <= prior.values and held.reasons <= prior.reasons


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
    grown = {
        extent: _shared_sources(held | prior)
        for extent, held in right.items()
        for prior in (left.get(extent, _NO_SOURCE_SET),)
        if (prior is not held and not held <= prior)
        or (not held and extent not in left)
    }
    return _with_grown(left, grown)


def _with_grown(
    left: Mapping[FieldExtent, frozenset[Source]],
    grown: Mapping[FieldExtent, frozenset[Source]],
) -> Mapping[FieldExtent, frozenset[Source]]:
    if not grown:
        return left
    return _canonical({**left, **grown}, grown)


def _canonical(
    joined: Mapping[FieldExtent, frozenset[Source]],
    grown: Mapping[FieldExtent, frozenset[Source]],
) -> Mapping[FieldExtent, frozenset[Source]]:
    names = {changed.field_name for changed in grown}
    near = tuple(
        extent
        for extent in joined
        if extent.field_name in names and extent.precision is Precision.EXACT
    )
    groups = tuple(
        tuple(extent for extent in near if (extent.field_name, extent.region) == one)
        for one in {(extent.field_name, extent.region) for extent in near}
    )
    rebuilt = tuple(
        (group, runs)
        for group in groups
        if len(group) > 1 and not _already_canonical(joined, group)
        for runs in (_runs(joined, group),)
        if set(runs) != set(group)
    )
    if not rebuilt:
        return MappingProxyType(joined)
    doomed = {extent for group, _ in rebuilt for extent in group}
    return MappingProxyType(
        {
            **{e: held for e, held in joined.items() if e not in doomed},
            **{e: held for _, runs in rebuilt for e, held in runs.items()},
        }
    )


def _already_canonical(
    joined: Mapping[FieldExtent, frozenset[Source]],
    group: tuple[FieldExtent, ...],
) -> bool:
    """Whether ``_runs`` would hand ``group`` back unchanged: no two pieces overlap,
    and no two that touch hold the same sources, so there is nothing to cut or merge.
    """
    ordered = sorted((one.start, one.end, one) for one in group)
    return all(
        left_end <= right_start
        and not (left_end == right_start and joined[left] == joined[right])
        for (_left_start, left_end, left), (right_start, _right_end, right) in pairwise(
            ordered
        )
    )


def _runs(
    joined: Mapping[FieldExtent, frozenset[Source]],
    group: tuple[FieldExtent, ...],
) -> Mapping[FieldExtent, frozenset[Source]]:
    marks = sorted({offset for one in group for offset in (one.start, one.end)})
    spans = tuple(
        (start, end, held)
        for start, end in pairwise(marks)
        for held in (_covering(joined, group, start, end),)
        if held
    )
    merged_spans = reduce(_extended, spans, ())
    return {_piece(group[0], start, end): held for start, end, held in merged_spans}


def _covering(
    joined: Mapping[FieldExtent, frozenset[Source]],
    group: tuple[FieldExtent, ...],
    start: int,
    end: int,
) -> frozenset[Source]:
    return _shared_sources(
        frozenset().union(
            *(joined[one] for one in group if one.start <= start and end <= one.end)
        )
    )


_Span = tuple[int, int, frozenset[Source]]


def _extended(spans: tuple[_Span, ...], span: _Span) -> tuple[_Span, ...]:
    if spans and spans[-1][1] == span[0] and spans[-1][2] == span[2]:
        return (*spans[:-1], (spans[-1][0], span[1], span[2]))
    return (*spans, span)


def _joined_values(left: State, right: State) -> Mapping[FieldExtent, ValueSet]:
    """Every extent from either side, merged with what the other side holds there.

    An extent one side has no entry for is not a side contributing nothing: that
    path either never wrote the bytes or wrote content the walk cannot name, and
    neither is stored. So the other side's view of those bytes -- a value sliced
    from a wider extent, or the reason its miss gives -- joins the entry. Taking
    the entry as it stood read a value set on one branch as certain after an IF
    whose other branch computed the field or left it unset.
    """
    if left.values is right.values:
        return left.values
    grown = {**_doubted(left, right), **_arrived(left, right)}
    return MappingProxyType({**left.values, **grown}) if grown else left.values


def _arrived(left: State, right: State) -> Mapping[FieldExtent, ValueSet]:
    """``right``'s entries that add to what ``left`` holds for the same bytes.

    One lookup per entry, and the identity test first: most of a join is the same
    ``ValueSet`` object on both sides, and a ``FieldExtent`` hash is expensive.
    """
    return {
        extent: _arriving_value(left, extent, prior, held)
        for extent, held in right.values.items()
        for prior in (left.values.get(extent, _UNHELD),)
        if prior is not held and (prior is _UNHELD or not _covers(prior, held))
    }


def _arriving_value(
    left: State, extent: FieldExtent, prior: ValueSet, held: ValueSet
) -> ValueSet:
    if prior is _UNHELD:
        return _shared_value(merged(values_at(left, extent), held))
    return _shared_value(merged(prior, held))


def _doubted(left: State, right: State) -> Mapping[FieldExtent, ValueSet]:
    """``left``'s entries ``right`` has none for, with ``right``'s view added."""
    return {
        extent: _shared_value(merged(held, other))
        for extent, held in left.values.items()
        if extent not in right.values
        for other in (values_at(right, extent),)
        if not _covers(held, other)
    }


def join(left: State, right: State) -> State:
    """Union of both components, extent by extent, one field name's EXACT provenance
    entries rewritten to their canonical pieces.

    ``left is right`` is the fixpoint's own common case -- a node joined against
    itself once its in-state has settled -- and short-circuits before either
    component is touched.
    """
    if left is right:
        return left
    return State(
        sources=_joined_sources(left.sources, right.sources),
        values=_joined_values(left, right),
        unwritten=union(left.unwritten, right.unwritten),
    )


def _disjoint(target: FieldExtent, extent: FieldExtent) -> bool:
    return (
        target.region is not extent.region
        or extent.start + extent.length <= target.start
        or target.start + target.length <= extent.start
    )


def _range_contains(target: FieldExtent, extent: FieldExtent) -> bool:
    return (
        target.region is extent.region
        and target.start <= extent.start
        and extent.start + extent.length <= target.start + target.length
    )


def _touching(target: FieldExtent) -> Callable[[FieldExtent], bool]:
    """Whether an entry shares a byte with ``target``: the cheap test every kill,
    split and invalidation implies, so the full predicate runs only on the few
    entries a write can touch rather than on the whole map."""
    region, start, end = target.region, target.start, target.start + target.length
    return lambda extent: (
        extent.region is region
        and extent.start < end
        and start < extent.start + extent.length
    )


def _partly_overwritten(target: FieldExtent, extent: FieldExtent) -> bool:
    """Whether a write to ``target`` changed some of ``extent``'s bytes and not all.

    A write that misses the extent entirely, and one whose range spans the whole of
    it -- where ``must_cover`` decides, and a CLAMPED span over a table is the weak
    update ``write`` documents -- are both false here. What is left is the partial
    write: narrower than the extent, or straddling its edge.

    Asked with the same region/start/end arithmetic ``values_at`` uses, not through
    ``may_alias``: the kill has to agree with the read that will ask, and
    ``may_alias`` answers the provenance half's question instead.
    """
    return not _disjoint(target, extent) and not _range_contains(target, extent)


_Held = TypeVar("_Held", frozenset[Source], ValueSet)


def _splits(target: FieldExtent, extent: FieldExtent) -> bool:
    return (
        target.precision is Precision.EXACT
        and extent.precision is Precision.EXACT
        and _partly_overwritten(target, extent)
    )


def _piece(extent: FieldExtent, start: int, end: int) -> FieldExtent:
    return _shared_extent(
        FieldExtent(
            region=extent.region,
            start=start,
            length=end - start,
            precision=extent.precision,
            field_name=extent.field_name,
        )
    )


def _remainders(target: FieldExtent, extent: FieldExtent) -> tuple[FieldExtent, ...]:
    return tuple(
        piece
        for piece in (
            _piece(extent, extent.start, target.start),
            _piece(extent, target.end, extent.end),
        )
        if piece.length > 0
    )


def _gathered(
    pieces: tuple[tuple[FieldExtent, _Held], ...],
    into: Mapping[FieldExtent, _Held],
    combine: Callable[[_Held, _Held], _Held],
) -> dict[FieldExtent, _Held]:
    touched: dict[FieldExtent, _Held] = reduce(
        lambda held, one: {**held, one[0]: _added(held, into, one, combine)},
        pieces,
        {},
    )
    return {**into, **touched}


def _added(
    held: Mapping[FieldExtent, _Held],
    into: Mapping[FieldExtent, _Held],
    one: tuple[FieldExtent, _Held],
    combine: Callable[[_Held, _Held], _Held],
) -> _Held:
    extent, piece = one
    if extent in held:
        return combine(held[extent], piece)
    if extent in into:
        return combine(into[extent], piece)
    return piece


def _split(
    target: FieldExtent,
    entries: Mapping[FieldExtent, _Held],
    cut: Callable[[_Held, FieldExtent, FieldExtent], _Held],
    combine: Callable[[_Held, _Held], _Held],
) -> Mapping[FieldExtent, _Held]:
    if target.precision is not Precision.EXACT:
        return entries
    touches = _touching(target)
    struck = frozenset(
        extent for extent in entries if touches(extent) and _splits(target, extent)
    )
    if not struck:
        return entries
    pieces = tuple(
        (piece, cut(entries[extent], extent, piece))
        for extent in struck
        for piece in _remainders(target, extent)
    )
    kept = {extent: held for extent, held in entries.items() if extent not in struck}
    return _gathered(pieces, kept, combine)


def _whole(
    held: frozenset[Source], extent: FieldExtent, piece: FieldExtent
) -> frozenset[Source]:
    return held


def _united(left: frozenset[Source], right: frozenset[Source]) -> frozenset[Source]:
    return _shared_sources(left | right)


def _invalidated(held: ValueSet) -> ValueSet:
    """What an entry still says once a write overwrote part of the bytes it claims.

    Only where ``_split`` could not cut the entry, because one side is CLAMPED. The
    values go. They named the content of a byte range the write has since
    changed, so keeping them reports a value the program cannot hold -- and with
    empty reasons, which is what promotes a dynamic call site to a proven edge:
    ``MOVE X TO WS-PGM(1:1)`` over a field declared ``VALUE 'COSGN00C'`` used to
    leave the whole field reading back as that literal, with nothing said. Splicing
    the new bytes into the old ones instead was rejected: the result would be a name
    assembled from two writes the fixpoint reached separately, the same fabrication
    ``values_at`` refuses for a read straddling two valued extents.

    The reasons stay, and NOT_A_LITERAL joins them, because a write cannot remove
    doubt about bytes it did not write. An entry claiming no values in the first
    place -- a callee write-back's doubt over a whole commarea, which is most of
    what this map holds at a call site -- has nothing to invalidate and stands as
    it is, so a narrow MOVE into that commarea does not quietly delete the reason
    the site is only a candidate.
    """
    if not held.values:
        return held
    return _shared_value(
        ValueSet(reasons=held.reasons | {UnresolvedReason.NOT_A_LITERAL})
    )


def _after_write(target: FieldExtent, extent: FieldExtent, held: ValueSet) -> ValueSet:
    if _partly_overwritten(target, extent):
        return _invalidated(held)
    return held


def _kept_values(
    state: State, target: FieldExtent, values: ValueSet
) -> Mapping[FieldExtent, ValueSet]:
    """The value map after ``target``'s kill, or the shared empty map.

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

    The kill runs unconditionally, whether or not anything gets stored: a stale
    value surviving a write that overwrote it would report a value the program
    cannot hold, and that is true whether the new write says "not a literal" or
    says nothing worth a map entry at all.
    """
    worth_storing = bool(values.values) or not values.reasons <= _UNINFORMATIVE
    if not state.values and not worth_storing:
        return _NO_VALUES
    touches = _touching(target)
    surviving = {
        extent: _after_write(target, extent, held) if touches(extent) else held
        for extent, held in _split(target, state.values, _sliced, merged).items()
        if not (touches(extent) and target.must_cover(extent))
    }
    if not worth_storing:
        return MappingProxyType(surviving) if surviving else _NO_VALUES
    return MappingProxyType(
        {
            **surviving,
            target: _shared_value(merged(surviving.get(target, VALUES_EMPTY), values)),
        }
    )


def write(
    state: State,
    target: FieldExtent,
    sources: frozenset[Source],
    values: ValueSet = VALUES_EMPTY,
) -> State:
    """``sources`` and ``values`` reach ``target``; whatever it overwrites stops.

    An EXACT target must_covers itself, so it drops its own prior entry in both maps
    -- a strong update. A CLAMPED one covers nothing, so both are kept and this is a
    weak update. An EXACT target narrower than an EXACT entry splits it in both
    maps (``_split``): the untouched bytes keep the entry's provenance and values,
    and the overwritten ones hold only this write. Where either side is CLAMPED the
    two halves part instead: the provenance is kept whole, because a read of the
    untouched bytes still depends on the write that placed them, while the values
    go, because ``_invalidated`` says a partly overwritten value is a false claim
    rather than an imprecise one.
    """
    return _stored(state, _shared_extent(target), sources, values)


def _stored(
    state: State, target: FieldExtent, sources: frozenset[Source], values: ValueSet
) -> State:
    touches = _touching(target)
    kept_sources = {
        extent: held
        for extent, held in _split(target, state.sources, _whole, _united).items()
        if not (touches(extent) and target.must_cover(extent))
    }
    return State(
        sources=MappingProxyType(
            {
                **kept_sources,
                target: _shared_sources(
                    kept_sources.get(target, frozenset()) | sources
                ),
            }
        ),
        values=_kept_values(state, target, values),
        unwritten=(
            without(state.unwritten, target)
            if target.precision is Precision.EXACT
            else state.unwritten
        ),
    )


def weak_write(
    state: State,
    target: FieldExtent,
    sources: frozenset[Source],
    doubt: ValueSet,
) -> State:
    """``sources`` may reach ``target``, which may or may not have changed.

    Nothing is killed: the write may leave the target as it was, so every definer
    already there stays, and so does every value. What changes is the doubt --
    ``doubt``'s reasons join every value the write overlaps, and the target's own
    entry is what it held merged with ``doubt``, so a value the walk can no longer
    vouch for is read back as a candidate rather than an answer.
    """
    marked = {
        extent: (
            _shared_value(
                ValueSet(values=held.values, reasons=held.reasons | doubt.reasons)
            )
            if extent.may_alias(target)
            else held
        )
        for extent, held in state.values.items()
    }
    return State(
        sources=MappingProxyType(
            {
                **state.sources,
                target: _shared_sources(
                    state.sources.get(target, frozenset()) | sources
                ),
            }
        ),
        values=MappingProxyType(
            {**marked, target: _shared_value(merged(values_at(state, target), doubt))}
        ),
        unwritten=state.unwritten,
    )


def _kept(
    entries: Mapping[FieldExtent, _Held], keep: Callable[[FieldExtent], bool]
) -> Mapping[FieldExtent, _Held]:
    if all(keep(extent) for extent in entries):
        return entries
    return MappingProxyType(
        {extent: held for extent, held in entries.items() if keep(extent)}
    )


def pruned(state: State, keep: Callable[[FieldExtent], bool]) -> State:
    """``state`` without the entries ``keep`` rejects, or ``state`` itself if none."""
    sources = _kept(state.sources, keep)
    values = _kept(state.values, keep)
    if sources is state.sources and values is state.values:
        return state
    return State(sources=sources, values=values, unwritten=state.unwritten)


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
    return _shared_value(
        ValueSet(
            values=frozenset(value[at : at + read.length] for value in held.values),
            reasons=held.reasons,
        )
    )


def _missing(state: State, read: FieldExtent) -> ValueSet:
    """Why a read found no value: what its region and its writers say.

    A LINKAGE miss is not an uninitialised field. LINKAGE declares storage the
    caller owns and this intra-program walk never sees written, so the reason is
    that the writer is outside the analysis -- which is what Unit 2's
    interprocedural pass will answer and ``UNINITIALISED`` would have hidden.

    Elsewhere the two reasons are facts in their own right, and a miss reports
    each that holds. ``not-a-literal``: some write reached the bytes with content
    the walk cannot name -- a numeric MOVE, any arithmetic -- which stores no value
    but does record its provenance. ``uninitialised``: some path reaches here with
    the bytes still in ``state.unwritten``, which only an exact write removes.
    Both only grow as paths join, so the walk's answer does not depend on the
    order it visits nodes; inferring ``uninitialised`` from the absence of a
    writer did, because a state joined before its writers arrived kept it.

    Answered at read time and never stored. Storing it would put an entry in
    ``state.values`` for every byte range any statement reads, which is the
    redundancy ``_UNINFORMATIVE`` exists to keep out of the map.
    """
    if read.region is RegionId.LINKAGE:
        return because(UnresolvedReason.INBOUND_LINKAGE)
    return _shared_value(
        ValueSet(
            reasons=frozenset(
                reason
                for reason, holds in (
                    (UnresolvedReason.NOT_A_LITERAL, _written(state, read)),
                    (UnresolvedReason.UNINITIALISED, overlaps(state.unwritten, read)),
                )
                if holds
            )
        )
    )


def _written(state: State, read: FieldExtent) -> bool:
    """``read.may_alias`` against every entry, with its arithmetic inlined: this runs
    on every read that finds no value, which is most of them."""
    if read in state.sources:
        return True
    if read.length <= 0:
        return False
    region, start, end = read.region, read.start, read.start + read.length
    return any(
        extent.region is region
        and extent.length > 0
        and extent.start < end
        and start < extent.start + extent.length
        for extent in state.sources
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
        return _missing(state, read)
    found = tuple(
        _sliced(held, extent, read)
        for extent, held in state.values.items()
        if extent.region is read.region
        and extent.start <= read.start
        and read.end <= extent.end
    )
    if not found:
        return _missing(state, read)
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
    reports ``_missing``'s reason rather than the value. That aliasing matters at a call
    site, not in a MOVE chain, and ``values_at`` keeps the scan for exactly that.
    """
    if read in state.values:
        return state.values[read]
    return _missing(state, read)
