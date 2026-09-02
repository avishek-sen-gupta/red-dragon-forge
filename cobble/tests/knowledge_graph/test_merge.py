"""merge_graph() — what the merged graph says about a node seen more than once.

Three extractors and GraphWriter's own endpoint synthesis can all produce the
same (kind, id). What survives that fold decides what nodes.jsonl claims, so
the precedence is pinned here rather than left to arrival order.
"""

from pathlib import Path

from cobble.file_location import NOT_ATTEMPTED, FileLocationReason, NoFileLocation
from cobble.knowledge_graph.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.knowledge_graph.merge import merge_graph

_UNRESOLVED = NoFileLocation(FileLocationReason.UNRESOLVED)


def _copies(source: str, target: str) -> GraphEdge:
    return GraphEdge(
        source=source,
        source_kind=NodeKind.PROGRAM,
        target=target,
        target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY,
    )


def test_a_node_carries_its_location_into_the_graph() -> None:
    graph = merge_graph(
        [
            GraphNode(
                id="PROGONE", kind=NodeKind.PROGRAM, location=Path("cbl/PROGONE.cbl")
            )
        ],
        [],
    )

    assert graph.nodes[(NodeKind.PROGRAM, "PROGONE")]["location"] == Path(
        "cbl/PROGONE.cbl"
    )


def test_a_located_occurrence_wins_over_an_unlocated_one_either_way_round() -> None:
    """Order independence: a fixture that names the file and one that does not
    must merge to the same node whichever arrives first."""
    located = GraphNode(
        id="PROGONE", kind=NodeKind.PROGRAM, location=Path("cbl/PROGONE.cbl")
    )
    unlocated = GraphNode(id="PROGONE", kind=NodeKind.PROGRAM, location=_UNRESOLVED)

    for nodes in ([located, unlocated], [unlocated, located]):
        graph = merge_graph(nodes, [])
        assert graph.nodes[(NodeKind.PROGRAM, "PROGONE")]["location"] == Path(
            "cbl/PROGONE.cbl"
        )


def test_a_stated_reason_wins_over_never_having_looked() -> None:
    """NOT_ATTEMPTED says only that nobody asked, so it never overwrites a
    resolver's answer — including when the never-asked occurrence is first."""
    graph = merge_graph(
        [
            GraphNode(id="TEST.DATA", kind=NodeKind.DATASET, location=NOT_ATTEMPTED),
            GraphNode(
                id="TEST.DATA",
                kind=NodeKind.DATASET,
                location=NoFileLocation(FileLocationReason.NOT_FILE_BASED),
            ),
        ],
        [],
    )

    assert graph.nodes[(NodeKind.DATASET, "TEST.DATA")]["location"] == NoFileLocation(
        FileLocationReason.NOT_FILE_BASED
    )


def test_an_endpoint_nobody_enumerated_says_it_was_never_looked_up() -> None:
    """merge_graph has no CorpusIndex, so a node it synthesises to keep an edge
    from dangling cannot claim the corpus was missing a file — it can only say
    that nothing resolved it."""
    graph = merge_graph([], [_copies("PROGONE", "COPYONE")])

    assert graph.nodes[(NodeKind.COPYBOOK, "COPYONE")]["location"] == NOT_ATTEMPTED


def test_an_enumerated_endpoint_keeps_its_own_location() -> None:
    graph = merge_graph(
        [GraphNode(id="COPYONE", kind=NodeKind.COPYBOOK, location=_UNRESOLVED)],
        [_copies("PROGONE", "COPYONE")],
    )

    assert graph.nodes[(NodeKind.COPYBOOK, "COPYONE")]["location"] == _UNRESOLVED


def test_attrs_of_repeated_occurrences_are_unioned_later_winning() -> None:
    graph = merge_graph(
        [
            GraphNode(
                id="PROGONE", kind=NodeKind.PROGRAM, attrs={"lang": "COBOL", "lines": 1}
            ),
            GraphNode(id="PROGONE", kind=NodeKind.PROGRAM, attrs={"lines": 2}),
        ],
        [],
    )

    assert graph.nodes[(NodeKind.PROGRAM, "PROGONE")]["attrs"] == {
        "lang": "COBOL",
        "lines": 2,
    }


def test_two_kinds_under_one_id_stay_two_nodes() -> None:
    graph = merge_graph(
        [
            GraphNode(id="COPYONE", kind=NodeKind.COPYBOOK),
            GraphNode(id="COPYONE", kind=NodeKind.COBOL_FILE),
        ],
        [],
    )

    assert graph.number_of_nodes() == 2


def test_two_edge_kinds_between_the_same_pair_both_survive() -> None:
    graph = merge_graph(
        [],
        [
            _copies("PROGONE", "COPYONE"),
            GraphEdge(
                source="PROGONE",
                source_kind=NodeKind.PROGRAM,
                target="COPYONE",
                target_kind=NodeKind.COPYBOOK,
                kind=EdgeKind.CALL,
            ),
        ],
    )

    assert graph.number_of_edges() == 2


def test_the_graph_records_id_and_kind_alongside_the_key() -> None:
    """layout and both renderers read these back out of the node data rather
    than unpacking the key, so they are part of the contract."""
    graph = merge_graph([], [_copies("PROGONE", "COPYONE")])

    data = graph.nodes[(NodeKind.PROGRAM, "PROGONE")]
    assert (data["id"], data["kind"], data["attrs"]) == (
        "PROGONE",
        NodeKind.PROGRAM,
        {},
    )
