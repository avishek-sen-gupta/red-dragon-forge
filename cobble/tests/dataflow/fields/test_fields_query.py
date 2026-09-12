"""The query surface: byte-interval answers over the four artefacts.

The four-way join is the graph with the extents, edges, defs, and aliases tables.

Rows are written in the artefact's own shape rather than produced by a run, so
these are assertions about what a consumer of the published files can recover --
including the things the emitter deliberately stopped writing.

The layout under test, all in working storage:

    01 REC          [0:8]     01 REC-B        [8:20]     01 ALIAS  [0:8] REDEFINES
       05 WS-A      [0:4]        05 WS-C      [8:12]        05 WHOLE [0:8]
       05 WS-B      [4:8]        05 WS-D      [12:16]
                                 05 WS-TAIL   [16:20]
"""

from __future__ import annotations

import pytest
from cobble.dataflow.fields.extent_text import NO_RANGE, byte_range
from cobble.dataflow.fixpoint.query import Side, contributed, reaches, store_of

GROUP_MOVE = "MAIN/0"
CHILD_MOVE = "MAIN/1"


def _declared(
    name: str,
    level: int,
    ranges: tuple[tuple[int, int], ...],
    usage: str = "DISPLAY",
    program: str = "PROGA",
) -> dict:
    return {
        "id": f"{program}.{name}",
        "level": level,
        "usage": usage,
        "extents": [f"{name}@working_storage[{low}:{high}]" for low, high in ranges],
    }


def _range(name: str, low: int, high: int, clamped: str = "") -> str:
    return f"{name}@working_storage[{low}:{high}]{clamped}"


def _edge(
    source: str,
    target: str,
    node: str,
    source_extent: str,
    target_extent: str,
    program: str = "PROGA",
) -> dict:
    return {
        "source": f"{program}.{source}",
        "target": f"{program}.{target}",
        "kind": "FLOWS_TO",
        "attrs": {
            "node": node,
            "source_extent": source_extent,
            "target_extent": target_extent,
        },
    }


@pytest.fixture
def declared() -> tuple[dict, ...]:
    return (
        _declared("REC", 1, ((0, 8),)),
        _declared("WS-A", 5, ((0, 4),)),
        _declared("WS-B", 5, ((4, 8),)),
        _declared("REC-B", 1, ((8, 20),)),
        _declared("WS-C", 5, ((8, 12),)),
        _declared("WS-D", 5, ((12, 16),)),
        _declared("WS-TAIL", 5, ((16, 20),)),
        _declared("ALIAS", 1, ((0, 8),)),
        _declared("WHOLE", 5, ((0, 8),)),
    )


@pytest.fixture
def group_write() -> dict:
    """MOVE REC TO REC-B: eight bytes into a twelve-byte record."""
    return _edge(
        "REC", "REC-B", GROUP_MOVE, _range("REC", 0, 8), _range("REC-B", 8, 20)
    )


@pytest.fixture
def store(declared, group_write):
    def build(edges=(), defs=()):
        return store_of(declared, (group_write, *edges), defs)

    return build


def _one(store, name: str):
    (found,) = store.field(name)
    return found


def test_a_bare_name_resolves_to_every_program_declaring_it():
    """Field names are only unique within a program, and a reader asks by name."""
    store = store_of(
        (
            _declared("WS-A", 5, ((0, 4),)),
            _declared("WS-A", 5, ((0, 4),), program="PROGB"),
        ),
        (),
        (),
    )
    assert {field.program for field in store.field("WS-A")} == {"PROGA", "PROGB"}
    assert [field.id for field in store.field("PROGB.WS-A")] == ["PROGB.WS-A"]


def test_a_child_filled_by_a_group_write_has_that_write_as_a_writer(store):
    """The case an id join cannot answer, and the reason every predicate is byte-wise.

    The edge names REC-B, the smallest declared field covering the bytes moved. A
    consumer joining on node ids therefore finds no writer at all for WS-C -- on
    the corpus member measured, twenty-one readers of one field resolved to zero.
    """
    found = store()
    writers = found.touching(_one(found, "WS-C").ranges, Side.TARGET)

    assert [flow.node for flow in writers] == [GROUP_MOVE]
    assert not [
        flow for flow in found.flows if flow.target.endswith(".WS-C")
    ], "no edge names the child; that is the point"


def test_a_group_write_is_not_a_writer_of_a_field_outside_its_bytes(store):
    """The group write's target is REC-B, so WS-A -- which shares no byte with it --
    has no writer, even though the same statement reads WS-A's own record."""
    found = store()
    assert found.touching(_one(found, "WS-A").ranges, Side.TARGET) == ()


def test_a_reader_of_a_group_is_a_reader_of_every_field_inside_it(store):
    found = store()
    assert [
        flow.node for flow in found.touching(_one(found, "WS-B").ranges, Side.SOURCE)
    ] == [GROUP_MOVE]


def test_which_bytes_a_child_received_is_recovered_from_the_two_ranges(store):
    """The per-child fan-out the emitter stopped writing, derived instead.

    Either operand being a group makes the MOVE an alphanumeric byte copy, so byte
    k of the target came from byte k of the source: WS-C sits at REC-B's offset 0
    and takes REC's first four bytes, WS-D the next four.
    """
    found = store()
    (flow,) = found.flows

    assert contributed(flow, _one(found, "WS-C").ranges[0]) == byte_range(
        _range("REC", 0, 4), "PROGA"
    )
    assert contributed(flow, _one(found, "WS-D").ranges[0]) == byte_range(
        _range("REC", 4, 8), "PROGA"
    )


def test_a_child_past_the_sources_end_took_no_bytes_from_it(store):
    """WS-TAIL is REC-B's bytes 8 to 12 and REC has only eight: spaces, not a flow."""
    found = store()
    (flow,) = found.flows

    assert contributed(flow, _one(found, "WS-TAIL").ranges[0]) == NO_RANGE


def test_a_whole_elementary_target_takes_the_whole_source(declared):
    """Not byte k from byte k: a numeric elementary move aligns on the decimal
    point, so the only honest answer for a target written whole is the whole
    source."""
    store = store_of(
        declared,
        (
            _edge(
                "WS-A", "WS-C", CHILD_MOVE, _range("WS-A", 0, 4), _range("WS-C", 8, 12)
            ),
        ),
        (),
    )
    (flow,) = store.flows

    assert contributed(flow, _one(store, "WS-C").ranges[0]) == flow.source_range


def test_a_clamped_target_yields_no_byte_correspondence(declared):
    """A computed subscript lands somewhere in the range and nothing knows where,
    so the whole source is reported rather than an offset nobody can justify."""
    store = store_of(
        declared,
        (
            _edge(
                "REC",
                "REC-B",
                GROUP_MOVE,
                _range("REC", 0, 8),
                _range("REC-B", 8, 20, clamped="~"),
            ),
        ),
        (),
    )
    (flow,) = store.flows

    assert contributed(flow, _one(store, "WS-C").ranges[0]) == flow.source_range


def test_a_record_contains_the_names_inside_its_bytes_but_not_its_equal_level_alias(
    store,
):
    """ALIAS owns exactly REC's bytes, so ranges alone make each contain the other.

    The declared level is the only thing that separates them, which is why it is a
    column of the extents table rather than something a consumer infers.

    WHOLE is reported, and belongs there: it is a level 05 name owning bytes REC
    also owns, which is what a redefinition is. Containment here is over bytes, so
    an overlay of a record is inside it -- the answer to "what does this record
    contain" is every name that reads those bytes, not one declaration path.
    """
    found = store()
    assert [field.id for field in found.contains(_one(found, "REC"))] == [
        "PROGA.WHOLE",
        "PROGA.WS-A",
        "PROGA.WS-B",
    ]


def test_a_child_names_the_records_holding_it(store):
    """Both records, ordered by where they start and how deep they are declared."""
    found = store()
    assert [field.id for field in found.containers(_one(found, "WHOLE"))] == [
        "PROGA.ALIAS",
        "PROGA.REC",
    ]


def test_every_name_over_a_range_is_recoverable_including_the_equal_level_alias(store):
    """What neither direction of containment answers.

    ALIAS ties with REC on both bytes and level, so ``contains`` and ``containers``
    report it from neither end -- see the two tests above. An endpoint id names one
    of these five; this is how a reader gets the other four, which is what makes
    that id a label rather than a claim about which name the bytes are.
    """
    found = store()
    assert [field.id for field in found.overlapping(_one(found, "REC").ranges)] == [
        "PROGA.ALIAS",
        "PROGA.REC",
        "PROGA.WHOLE",
        "PROGA.WS-A",
        "PROGA.WS-B",
    ]


def test_a_range_straddling_two_records_names_both_and_the_members_it_clips(store):
    """Bytes 6-10 lie inside no single declared field, so containment answers
    nothing about them in either direction, and ``smallest_covering`` has no
    covering name to pick. Partial overlap is the only relation that holds."""
    found = store()
    assert [
        field.id
        for field in found.overlapping((byte_range(_range("?", 6, 10), "PROGA"),))
    ] == [
        "PROGA.ALIAS",
        "PROGA.REC",
        "PROGA.WHOLE",
        "PROGA.WS-B",
        "PROGA.REC-B",
        "PROGA.WS-C",
    ]


def test_a_range_from_another_program_matches_none_of_this_ones_declarations(store):
    """Offsets are region coordinates, so two members' working_storage[0:8] name
    different bytes. Scanning by program is an optimisation; ``overlaps`` rejecting
    a foreign program is what makes it correct."""
    found = store()
    assert not found.overlapping((byte_range(_range("REC", 0, 8), "PROGB"),))


def test_a_range_that_is_not_storage_at_all_owns_no_declared_name(store):
    """A literal or a callee parses to NO_RANGE, which is not comparable to
    anything -- including another NO_RANGE."""
    found = store()
    assert not found.overlapping((NO_RANGE,))


def test_a_group_holding_only_some_occurrences_of_a_table_entry_does_not_contain_it():
    """One range per occurrence, and every one of them has to be inside.

    A group covering the first occurrence only would otherwise report as
    containing the field, and a write to it as covering every occurrence.
    """
    store = store_of(
        (
            _declared("HALF", 1, ((0, 4),)),
            _declared("WHOLE-TAB", 1, ((0, 8),)),
            _declared("ENTRY", 5, ((0, 4), (4, 8))),
        ),
        (),
        (),
    )
    assert not store.contains(_one(store, "HALF"))
    assert [field.id for field in store.containers(_one(store, "ENTRY"))] == [
        "PROGA.WHOLE-TAB"
    ]


def test_a_transitive_walk_hops_through_a_group_write(store):
    """WS-A flows into REC-B by the group move, and on out of WS-C by the next one.

    Following ids would stop at REC-B: nothing names WS-C as a target, so the
    second hop is only reachable because the frontier is a byte range.
    """
    found = store(
        edges=(
            _edge(
                "WS-C",
                "WS-TAIL",
                CHILD_MOVE,
                _range("WS-C", 8, 12),
                _range("WS-TAIL", 16, 20),
            ),
        )
    )
    reached = reaches(found, _one(found, "WS-A").ranges, Side.SOURCE, 4)

    assert reached == {"PROGA.REC-B": 1, "PROGA.WS-TAIL": 2}


def test_a_transitive_walk_stops_at_the_depth_it_was_given(store):
    found = store(
        edges=(
            _edge(
                "WS-C",
                "WS-TAIL",
                CHILD_MOVE,
                _range("WS-C", 8, 12),
                _range("WS-TAIL", 16, 20),
            ),
        )
    )
    assert reaches(found, _one(found, "WS-A").ranges, Side.SOURCE, 1) == {
        "PROGA.REC-B": 1
    }


def test_a_walk_backwards_asks_the_same_question_of_the_other_end(store):
    found = store()
    assert reaches(found, _one(found, "WS-C").ranges, Side.TARGET, 4) == {
        "PROGA.REC": 1
    }


def test_a_cycle_over_the_same_bytes_terminates(declared):
    """Two fields moved into each other: without a seen set this never returns."""
    store = store_of(
        declared,
        (
            _edge("WS-A", "WS-B", "MAIN/0", _range("WS-A", 0, 4), _range("WS-B", 4, 8)),
            _edge("WS-B", "WS-A", "MAIN/1", _range("WS-B", 4, 8), _range("WS-A", 0, 4)),
        ),
        (),
    )
    assert reaches(store, _one(store, "WS-A").ranges, Side.SOURCE, 20) == {
        "PROGA.WS-B": 1,
        "PROGA.WS-A": 2,
    }


def test_the_definers_of_a_flow_come_off_the_defs_table(store):
    """Keyed by the node that moved the value and the source range as written."""
    found = store(
        defs=(
            {
                "node": GROUP_MOVE,
                "extent": _range("REC", 0, 8),
                "definers": ["MAIN/A", "MAIN/B"],
            },
        )
    )
    (flow,) = found.flows

    assert found.definers_of(flow) == ("MAIN/A", "MAIN/B")


def test_a_flow_with_no_defs_row_reports_no_definers_rather_than_failing(store):
    """A synthetic source has no reaching definition: the value came from outside
    storage, so the statement holding it is the only one that could have made it."""
    found = store()
    (flow,) = found.flows

    assert found.definers_of(flow) == ()


def test_an_artefact_without_the_defs_table_still_answers_every_other_question(
    tmp_path,
):
    """A directory written by an older build is worth querying, not refusing."""
    from cobble.dataflow.fixpoint.query import load

    (tmp_path / "extents.jsonl").write_text(
        '{"id": "PROGA.WS-A", "level": 5, "usage": "DISPLAY", '
        '"extents": ["WS-A@working_storage[0:4]"]}\n',
        encoding="utf-8",
    )
    store = load(tmp_path)

    assert [field.id for field in store.field("WS-A")] == ["PROGA.WS-A"]
    assert store.flows == ()
