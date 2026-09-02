"""FirstSighting — the streaming sinks' one piece of state.

The knowledge-graph sinks are push-based: an extractor calls add_node once per
occurrence, and a node reached from three different extractors must be written
once. These tests pin the only question that state answers — "have I written
this already?" — so the mutation behind it stays in one tested place.
"""

from __future__ import annotations

from cobble.knowledge_graph.graph_types import NodeKind
from cobble.sink_state import FirstSighting


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
