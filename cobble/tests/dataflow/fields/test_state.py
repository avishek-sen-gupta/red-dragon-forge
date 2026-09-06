"""The lattice, and the one asymmetry the whole analysis rests on."""

from __future__ import annotations

from cobble.dataflow.fields.state import EMPTY, Source, join, reaching, write
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


def test_join_of_a_state_with_itself_is_that_state():
    left = write(EMPTY, _extent(0, 4), frozenset({_source("WS-L")}))
    assert join(left, left) == left
