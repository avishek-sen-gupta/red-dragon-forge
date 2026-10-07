"""The lattice, and the one asymmetry the whole analysis rests on."""

from __future__ import annotations

from types import MappingProxyType

from cobble.dataflow.fields.state import (
    EMPTY,
    Source,
    State,
    exact_values,
    join,
    reaching,
    values_at,
    weak_write,
    write,
)
from cobble.dataflow.fields.values import UnresolvedReason, ValueSet, because, of_value
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


def _extent(start: int, length: int, precision=Precision.EXACT, name="WS-A"):
    return FieldExtent(
        region=RegionId.WORKING_STORAGE,
        start=start,
        length=length,
        precision=precision,
        field_name=name,
    )


def _source(name: str) -> Source:
    return Source(origin="", extent=_extent(100, 4, name=name), node="MAIN/0")


def _names(state, read) -> set[str]:
    return {source.extent.field_name for source in reaching(state, read)}


def test_an_exact_write_kills_the_definition_it_covers():
    first = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    second = write(first, _extent(0, 4), frozenset({_source("WS-NEW")}))
    assert _names(second, _extent(0, 4)) == {"WS-NEW"}


def test_a_clamped_write_never_kills():
    """Precision.CLAMPED cannot cover, so a computed subscript is a weak update."""
    first = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    second = write(
        first,
        _extent(0, 4, precision=Precision.CLAMPED),
        frozenset({_source("WS-NEW")}),
    )
    assert _names(second, _extent(0, 4)) == {"WS-OLD", "WS-NEW"}


def test_a_write_does_not_kill_a_definition_it_only_partly_covers():
    first = write(EMPTY, _extent(0, 8), frozenset({_source("WS-OLD")}))
    second = write(first, _extent(0, 4), frozenset({_source("WS-NEW")}))
    assert "WS-OLD" in _names(second, _extent(4, 4))


def test_a_wider_write_kills_the_narrower_definition_inside_it():
    first = write(EMPTY, _extent(4, 4), frozenset({_source("WS-OLD")}))
    second = write(first, _extent(0, 8), frozenset({_source("WS-NEW")}))
    assert _names(second, _extent(4, 4)) == {"WS-NEW"}


def test_a_read_matches_by_overlap_not_by_equality():
    state = write(EMPTY, _extent(0, 8), frozenset({_source("WS-OLD")}))
    assert reaching(state, _extent(6, 4))


def test_a_read_of_a_disjoint_range_sees_nothing():
    state = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    assert reaching(state, _extent(8, 4)) == frozenset()


def test_a_read_in_another_region_sees_nothing():
    """Regions are separate buffers, so an equal offset in each is not an overlap."""
    state = write(EMPTY, _extent(0, 4), frozenset({_source("WS-OLD")}))
    linkage = FieldExtent(
        region=RegionId.LINKAGE,
        start=0,
        length=4,
        precision=Precision.EXACT,
        field_name="LK-A",
    )
    assert reaching(state, linkage) == frozenset()


def test_join_is_union():
    left = write(EMPTY, _extent(0, 4), frozenset({_source("WS-L")}))
    right = write(EMPTY, _extent(0, 4), frozenset({_source("WS-R")}))
    assert _names(join(left, right), _extent(0, 4)) == {"WS-L", "WS-R"}


def test_join_keeps_an_extent_only_one_side_holds():
    left = write(EMPTY, _extent(0, 4), frozenset({_source("WS-L")}))
    right = write(EMPTY, _extent(8, 4), frozenset({_source("WS-R")}))
    joined = join(left, right)
    assert _names(joined, _extent(0, 4)) == {"WS-L"}
    assert _names(joined, _extent(8, 4)) == {"WS-R"}


def test_a_value_one_path_holds_keeps_the_doubt_of_a_path_that_lacks_it():
    """A missing entry is a path that never wrote the bytes, or wrote content the
    walk cannot name -- never a path that contributes nothing. So a value held on
    one side only reads back with the other side's reason, whichever side it is,
    and a value the other side holds inside a wider extent is sliced out of it
    into the joined entry."""
    pgm = _extent(0, 5, name="WS-PGM")
    literal = write(EMPTY, pgm, frozenset(), of_value(b"PROGA"))
    computed = write(EMPTY, pgm, frozenset(), because(UnresolvedReason.NOT_A_LITERAL))
    other = write(EMPTY, pgm, frozenset(), of_value(b"PROGB"))
    comm = FieldExtent(RegionId.LINKAGE, 0, 5, Precision.EXACT, "LK-PGM")
    linked = write(EMPTY, comm, frozenset(), of_value(b"PROGA"))
    record = _extent(0, 8, name="WS-REC")
    declared = State(values=MappingProxyType({record: of_value(b"PROGCXYZ")}))
    overlaid = write(declared, pgm, frozenset(), of_value(b"PROGD"))

    assert values_at(join(literal, EMPTY), pgm) == ValueSet(
        values=frozenset({b"PROGA"}),
        reasons=frozenset({UnresolvedReason.UNINITIALISED}),
    )
    assert values_at(join(EMPTY, literal), pgm) == values_at(join(literal, EMPTY), pgm)
    assert values_at(join(literal, computed), pgm) == ValueSet(
        values=frozenset({b"PROGA"}),
        reasons=frozenset({UnresolvedReason.NOT_A_LITERAL}),
    )
    assert values_at(join(computed, literal), pgm) == values_at(
        join(literal, computed), pgm
    )
    assert values_at(join(linked, EMPTY), comm) == ValueSet(
        values=frozenset({b"PROGA"}),
        reasons=frozenset({UnresolvedReason.INBOUND_LINKAGE}),
    )
    assert values_at(join(literal, other), pgm) == ValueSet(
        values=frozenset({b"PROGA", b"PROGB"})
    )
    assert exact_values(join(declared, overlaid), pgm) == ValueSet(
        values=frozenset({b"PROGC", b"PROGD"})
    )


def test_join_of_a_state_with_itself_is_that_state():
    left = write(EMPTY, _extent(0, 4), frozenset({_source("WS-L")}))
    assert join(left, left) == left


def test_a_strong_write_kills_both_components_and_a_clamped_one_kills_neither():
    exact = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-A")
    clamped = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.CLAMPED, "WS-A")
    first = write(EMPTY, exact, frozenset(), of_value(b"PGMOLD  "))

    assert values_at(
        write(first, exact, frozenset(), of_value(b"PGMNEW  ")), exact
    ) == (of_value(b"PGMNEW  "))
    assert values_at(
        write(first, clamped, frozenset(), of_value(b"PGMNEW  ")), exact
    ) == ValueSet(frozenset({b"PGMOLD  ", b"PGMNEW  "}), frozenset())


def test_a_value_is_found_by_byte_range_not_by_extent_identity():
    declared = FieldExtent(RegionId.WORKING_STORAGE, 39, 8, Precision.EXACT, "FILLER_3")
    read_as = FieldExtent(
        RegionId.WORKING_STORAGE, 39, 8, Precision.EXACT, "CDEMO-MENU-OPT-PGMNAME"
    )
    state = write(EMPTY, declared, frozenset(), of_value(b"COACTVWC"))

    assert declared != read_as
    assert values_at(state, read_as) == of_value(b"COACTVWC")


def test_a_read_inside_a_valued_extent_is_sliced_and_one_that_straddles_two_is_not():
    left = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-L")
    right = FieldExtent(RegionId.WORKING_STORAGE, 8, 8, Precision.EXACT, "WS-R")
    state = write(
        write(EMPTY, left, frozenset(), of_value(b"COACTVWC")),
        right,
        frozenset(),
        of_value(b"COCRDLIC"),
    )
    inside = FieldExtent(RegionId.WORKING_STORAGE, 2, 4, Precision.EXACT, "SLICE")
    straddling = FieldExtent(
        RegionId.WORKING_STORAGE, 4, 8, Precision.EXACT, "STRADDLE"
    )

    assert values_at(state, inside) == of_value(b"ACTV")
    assert values_at(state, straddling) == because(UnresolvedReason.NOT_A_LITERAL)


def test_an_extent_nothing_has_written_reports_uninitialised():
    unwritten = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-A")

    assert values_at(EMPTY, unwritten) == because(UnresolvedReason.UNINITIALISED)


def test_exact_values_hits_its_own_extent_and_misses_an_aliased_one():
    """exact_values is the transfer's hot-path lookup, one dict hit and no scan of
    the value map.

    The trade is deliberate: a source read through a different name than the one
    that declared its value -- a REDEFINES read as CDEMO-MENU-OPT-PGMNAME over the
    FILLER that actually holds it -- misses exact_values and reports the miss's
    reason, not-a-literal here since a write reached those bytes, while values_at's
    containment scan still finds it through the byte range. That aliasing gap only
    matters at a call site, not in a MOVE chain.
    """
    declared = FieldExtent(RegionId.WORKING_STORAGE, 39, 8, Precision.EXACT, "FILLER_3")
    read_as = FieldExtent(
        RegionId.WORKING_STORAGE, 39, 8, Precision.EXACT, "CDEMO-MENU-OPT-PGMNAME"
    )
    state = write(EMPTY, declared, frozenset(), of_value(b"COACTVWC"))

    assert exact_values(state, declared) == of_value(b"COACTVWC")
    assert exact_values(state, read_as) == because(UnresolvedReason.NOT_A_LITERAL)
    assert values_at(state, read_as) == of_value(b"COACTVWC")


def test_a_write_with_no_known_value_still_erases_the_value_it_overwrites():
    """Mutation (c): skipping the map entry must never skip the must_cover kill.

    An EXACT write with nothing known erases what was there -- the extent reads
    back as unknown -- because it was KILLED, not because anything was stored for
    it. A CLAMPED write does not erase, since a computed subscript may not have
    hit this cell.
    """
    extent = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.EXACT, "WS-PGM")
    known = write(EMPTY, extent, frozenset(), of_value(b"COSGN00C"))
    overwritten = write(
        known, extent, frozenset(), because(UnresolvedReason.NOT_A_LITERAL)
    )
    clamped = FieldExtent(RegionId.WORKING_STORAGE, 0, 8, Precision.CLAMPED, "WS-PGM")
    weakly = write(known, clamped, frozenset(), because(UnresolvedReason.NOT_A_LITERAL))

    assert values_at(known, extent) == of_value(b"COSGN00C")
    assert values_at(overwritten, extent) == because(UnresolvedReason.NOT_A_LITERAL)
    assert values_at(weakly, extent) == of_value(b"COSGN00C")


def test_a_partial_write_invalidates_the_value_it_overwrote_part_of():
    """A write narrower than a valued extent cannot leave that value standing.

    The kill used to be must_cover alone, which asks whether the writer CONTAINS the
    victim -- so a reference-modified write into a field declared VALUE 'COSGN00C'
    changed nothing, and the whole field still read back as that literal with EMPTY
    reasons: a proven graph edge to a program the site may never reach. Whatever the
    partial write knew, and whatever its precision -- a CLAMPED slice lands somewhere
    inside the bytes the value claims, which is enough to make the claim false -- the
    values go and NOT_A_LITERAL says so.

    The reasons of the entry survive, and an entry holding no values at all is left
    alone: a write cannot cancel doubt about bytes outside it, and the doubt a callee
    write-back puts over a whole commarea is what keeps a dynamic site a candidate.
    """
    whole = _extent(0, 8, name="WS-PGM")
    part = _extent(0, 1, name="WS-PGM")
    clamped_part = _extent(0, 1, precision=Precision.CLAMPED, name="WS-PGM")
    declared = write(EMPTY, whole, frozenset(), of_value(b"COSGN00C"))
    from_callee = write(
        EMPTY, whole, frozenset(), because(UnresolvedReason.FROM_CALLEE)
    )

    with_literal = write(declared, part, frozenset(), of_value(b"X"))
    with_unknown = write(
        declared, part, frozenset(), because(UnresolvedReason.NOT_A_LITERAL)
    )
    weakly = write(declared, clamped_part, frozenset(), of_value(b"X"))

    assert values_at(declared, whole) == of_value(b"COSGN00C")
    assert values_at(with_literal, whole) == because(UnresolvedReason.NOT_A_LITERAL)
    assert values_at(with_literal, part) == ValueSet(
        frozenset({b"X"}), frozenset({UnresolvedReason.NOT_A_LITERAL})
    )
    assert values_at(with_unknown, whole) == because(UnresolvedReason.NOT_A_LITERAL)
    assert values_at(weakly, whole) == because(UnresolvedReason.NOT_A_LITERAL)
    assert values_at(
        write(from_callee, part, frozenset(), of_value(b"X")), whole
    ) == because(UnresolvedReason.FROM_CALLEE)


def test_a_miss_reports_what_explains_it():
    """LINKAGE is storage the caller owns, so a miss there is not an uninitialised
    field: the writer is outside an intra-program walk. In WORKING-STORAGE a miss is
    uninitialised only if nothing wrote the bytes; a write whose content the walk
    cannot name stores no value, so a miss on written bytes is not-a-literal.
    Answered on the miss and never stored, so state.values does not grow an entry
    per read."""
    linkage = FieldExtent(RegionId.LINKAGE, 0, 8, Precision.EXACT, "DFHCOMMAREA-PGM")
    working = _extent(0, 8, name="WS-PGM")
    state = write(EMPTY, working, frozenset(), of_value(b"COSGN00C"))

    assert values_at(state, linkage) == because(UnresolvedReason.INBOUND_LINKAGE)
    assert exact_values(state, linkage) == because(UnresolvedReason.INBOUND_LINKAGE)
    assert values_at(EMPTY, linkage) == because(UnresolvedReason.INBOUND_LINKAGE)
    assert values_at(state, _extent(8, 8, name="WS-OTHER")) == because(
        UnresolvedReason.UNINITIALISED
    )
    assert exact_values(state, working) == of_value(b"COSGN00C")
    computed = write(
        state,
        _extent(16, 8, name="WS-SUM"),
        frozenset(),
        because(UnresolvedReason.NOT_A_LITERAL),
    )
    assert values_at(computed, _extent(16, 8, name="WS-SUM")) == because(
        UnresolvedReason.NOT_A_LITERAL
    )
    assert exact_values(computed, _extent(16, 8, name="WS-SUM")) == because(
        UnresolvedReason.NOT_A_LITERAL
    )
    assert exact_values(computed, _extent(16, 4, name="WS-SUM-HI")) == because(
        UnresolvedReason.NOT_A_LITERAL
    )
    assert exact_values(computed, _extent(24, 4, name="WS-NEXT")) == because(
        UnresolvedReason.UNINITIALISED
    )


def test_a_weak_write_kills_nothing_and_says_the_old_value_may_have_changed():
    """An unmodelled statement may overwrite its target fully, partly or not at all:
    every old definer stays, the old value stays possible, and the doubt is named."""
    held = _extent(0, 8, name="WS-P")
    unwritten = _extent(8, 8, name="WS-Q")
    first = write(EMPTY, held, frozenset({_source("WS-OLD")}), of_value(b"PROGA   "))
    doubt = because(UnresolvedReason.UNMODELLED)

    after = weak_write(
        weak_write(first, held, frozenset({_source("WS-NEW")}), doubt),
        unwritten,
        frozenset(),
        doubt,
    )

    assert _names(after, held) == {"WS-OLD", "WS-NEW"}
    assert values_at(after, held) == ValueSet(
        frozenset({b"PROGA   "}), frozenset({UnresolvedReason.UNMODELLED})
    )
    assert values_at(after, unwritten) == ValueSet(
        frozenset(),
        frozenset({UnresolvedReason.UNINITIALISED, UnresolvedReason.UNMODELLED}),
    )
