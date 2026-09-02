"""FirstSighting and Buffer — the streaming sinks' two pieces of state.

The knowledge-graph sinks are push-based: an extractor calls add_node once per
occurrence, and a node reached from three different extractors must be written
once. These tests pin the only two questions that state answers — "have I
written this already?" and "what have I set aside for later?" — so the mutation
behind them stays in one tested place.
"""

from __future__ import annotations

from cobble.knowledge_graph.graph_types import NodeKind
from cobble.sink_state import Buffer, FirstSighting


def test_a_key_is_new_the_first_time_and_never_again() -> None:
    sightings = FirstSighting()

    assert [sightings.first_time("PROGONE") for _ in range(3)] == [True, False, False]


def test_keys_are_remembered_independently_of_one_another() -> None:
    sightings = FirstSighting()

    assert [
        sightings.first_time("PROGONE"),
        sightings.first_time("COPYONE"),
        sightings.first_time("PROGONE"),
    ] == [True, True, False]


def test_equal_composite_keys_are_one_sighting() -> None:
    """Node identity is (kind, id) and edge identity a five-tuple, so equality
    of distinct-but-equal tuples is what the sinks actually rely on."""
    sightings = FirstSighting()

    assert [
        sightings.first_time((NodeKind.PROGRAM, "PROGONE")),
        sightings.first_time((NodeKind.PROGRAM, "PROGONE")),
        sightings.first_time((NodeKind.COPYBOOK, "PROGONE")),
    ] == [True, False, True]


def test_two_memos_do_not_share_what_they_have_seen() -> None:
    """Nodes and edges are deduped separately, and a GraphWriter per run must
    not inherit a previous run's sightings — so the state is per instance."""
    nodes = FirstSighting()
    edges = FirstSighting()

    assert (nodes.first_time("PROGONE"), edges.first_time("PROGONE")) == (True, True)


def test_a_buffer_hands_back_what_was_put_in_it_in_order() -> None:
    buffer: Buffer[str] = Buffer()

    buffer.add_all(["one", "two"])
    buffer.add_all(["three"])

    assert buffer.drain() == ["one", "two", "three"]


def test_draining_a_buffer_empties_it() -> None:
    """canonical_export drains the synthesized filesystem edges once, between
    the manifest's nodes section and its edges section — a second drain that
    replayed them would write every MADE_OF edge twice."""
    buffer: Buffer[str] = Buffer()
    buffer.add_all(["one"])

    assert (buffer.drain(), buffer.drain()) == (["one"], [])


def test_a_drained_list_is_not_a_live_view_of_the_buffer() -> None:
    """The drained list is the caller's; refilling the buffer afterwards must
    not append to what the caller is already writing out."""
    buffer: Buffer[str] = Buffer()
    buffer.add_all(["one"])

    drained = buffer.drain()
    buffer.add_all(["two"])

    assert drained == ["one"]
