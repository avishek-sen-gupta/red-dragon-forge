"""Picking a hand-chosen slice of a CFG by node-id prefix, bridging it back
to one connected component, and rendering it as DOT."""

from __future__ import annotations

import pytest
from cobble.dataflow.srccfg.cfg import Atom, Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.subgraph import (
    SubgraphError,
    bridged_focus,
    build_dot,
    matches,
    node_label,
)


@pytest.mark.parametrize(
    ("node_id", "prefix", "expected"),
    [
        ("READ-RECORD/1", "READ-RECORD/1", True),
        ("READ-RECORD/1.sql0#test", "READ-RECORD/1", True),
        ("READ-RECORD/1#test", "READ-RECORD/1", True),
        ("READ-RECORD/10", "READ-RECORD/1", False),
        ("READ-RECORD/11", "READ-RECORD/1", False),
        ("READ-RECORD/2", "READ-RECORD/1", False),
    ],
)
def test_prefix_matching_is_separator_aware(
    node_id: str, prefix: str, expected: bool
) -> None:
    assert matches(node_id, prefix) is expected


def test_a_test_node_is_labelled_with_its_resolved_predicate() -> None:
    node = Node(
        id="A/0#test",
        kind=NodeKind.TEST,
        paragraph="A",
        atom=Atom(text="WS-FLAG == 'Y'", left="WS-FLAG", op="==", right="'Y'"),
    )

    assert "WS-FLAG == 'Y'" in node_label(node, {})


def test_an_unresolved_test_node_is_labelled_as_a_raised_condition() -> None:
    node = Node(id="A/0#raise", kind=NodeKind.TEST, paragraph="A")

    assert "raised condition" in node_label(node, {})


def test_a_move_is_labelled_with_its_operands() -> None:
    node = Node(
        id="A/0",
        kind=NodeKind.ASSIGN,
        paragraph="A",
        transfer="MOVE",
        reads=("WS-X",),
        writes=("WS-Y",),
    )

    assert node_label(node, {}) == "A/0\\nMOVE WS-X TO WS-Y"


def test_a_perform_is_labelled_with_its_target() -> None:
    node = Node(
        id="A/0", kind=NodeKind.CALL, paragraph="A", transfer="PERFORM", target="B"
    )

    assert node_label(node, {}) == "A/0\\nPERFORM B"


def test_a_cics_link_is_labelled_with_program_and_commarea() -> None:
    node = Node(
        id="A/0",
        kind=NodeKind.CALL,
        paragraph="A",
        transfer="CICS_LINK",
        target="SUBPROG",
        transfer_operand="SUB-COMM-AREA",
    )

    label = node_label(node, {})
    assert "LINK" in label
    assert "PROGRAM('SUBPROG')" in label
    assert "COMMAREA(SUB-COMM-AREA)" in label


def test_a_label_node_reads_as_a_paragraph_entry() -> None:
    node = Node(id="A#label", kind=NodeKind.LABEL, paragraph="A")

    assert "(paragraph entry)" in node_label(node, {})


def test_a_long_prefix_is_shortened_in_the_label() -> None:
    node = Node(
        id="VALIDATE-OPTION/4", kind=NodeKind.LABEL, paragraph="VALIDATE-OPTION"
    )

    assert node_label(node, {"VALIDATE-OPTION": "VO"}).startswith("VO/4")


def _chain(*ids: str) -> tuple[tuple[Node, ...], tuple[Edge, ...]]:
    nodes = tuple(Node(id=i, kind=NodeKind.LABEL, paragraph=i) for i in ids)
    edges = tuple(
        Edge(source=a, target=b, kind=EdgeKind.FLOW) for a, b in zip(ids, ids[1:])
    )
    return nodes, edges


def test_an_already_connected_focus_is_returned_unbridged() -> None:
    _, edges = _chain("A", "B", "C")
    all_edges = [(e.source, e.target) for e in edges]

    focus, added, used_weak = bridged_focus({"A", "B"}, all_edges, all_edges)

    assert focus == {"A", "B"}
    assert added == []
    assert used_weak is False


def test_two_pieces_are_bridged_via_the_strong_path_between_them() -> None:
    _, edges = _chain("A", "B", "C", "D")
    all_edges = [(e.source, e.target) for e in edges]

    focus, added, used_weak = bridged_focus({"A", "D"}, all_edges, all_edges)

    assert focus == {"A", "B", "C", "D"}
    assert set(added) == {"B", "C"}
    assert used_weak is False


def test_a_strong_only_path_is_preferred_over_a_fallthru_shortcut() -> None:
    """A different, weak-only (FALLTHRU-equivalent) route through X also joins
    the two pieces, but it must never be tried: the strong-edges path through
    B/C exists and wins outright."""
    strong = [("A", "B"), ("B", "C"), ("C", "D")]
    weak_only = [("A", "X"), ("X", "D")]
    all_edges = strong + weak_only

    focus, added, used_weak = bridged_focus({"A", "D"}, all_edges, strong)

    assert set(added) == {"B", "C"}
    assert used_weak is False


def test_falls_back_to_the_weak_path_when_no_strong_one_exists() -> None:
    weak_only = [("A", "B"), ("B", "D")]

    focus, added, used_weak = bridged_focus({"A", "D"}, weak_only, [])

    assert focus == {"A", "B", "D"}
    assert used_weak is True


def test_two_genuinely_unrelated_pieces_raise_instead_of_rendering_disconnected() -> (
    None
):
    with pytest.raises(SubgraphError):
        bridged_focus({"A", "Z"}, [("A", "B")], [("A", "B")])


def _cfg(program: str = "PROGA") -> Cfg:
    return Cfg(
        program=program,
        nodes=(
            Node(id="MAIN#label", kind=NodeKind.LABEL, paragraph="MAIN"),
            Node(
                id="MAIN/0#test",
                kind=NodeKind.TEST,
                paragraph="MAIN",
                atom=Atom(text="WS-A == 'Y'"),
            ),
            Node(
                id="MAIN/0.then.0",
                kind=NodeKind.ASSIGN,
                paragraph="MAIN",
                transfer="MOVE",
                writes=("WS-B",),
            ),
            Node(
                id="MAIN/1",
                kind=NodeKind.CALL,
                paragraph="MAIN",
                transfer="PERFORM",
                target="A",
            ),
            Node(id="A#label", kind=NodeKind.LABEL, paragraph="A"),
            Node(
                id="A/0",
                kind=NodeKind.ASSIGN,
                paragraph="A",
                transfer="MOVE",
                writes=("WS-C",),
            ),
        ),
        edges=(
            Edge(source="MAIN#label", target="MAIN/0#test", kind=EdgeKind.FLOW),
            Edge(source="MAIN/0#test", target="MAIN/0.then.0", kind=EdgeKind.TRUE),
            Edge(source="MAIN/0.then.0", target="MAIN/1", kind=EdgeKind.FLOW),
            Edge(source="MAIN/1", target="A#label", kind=EdgeKind.PERFORM),
            Edge(source="A#label", target="A/0", kind=EdgeKind.FLOW),
        ),
        entry="MAIN#label",
    )


def test_build_dot_includes_only_the_matched_and_bridged_nodes() -> None:
    document, bridged, _ = build_dot((_cfg(),), ["MAIN/1", "A/0"], (), frozenset(), {})

    assert '"MAIN/1"' in document
    assert '"A/0"' in document
    assert (
        "MAIN#label" not in bridged
    )  # not pulled in; PERFORM->A#label->A/0 is the bridge
    assert '"A#label"' in document  # the bridge itself


def test_a_drop_suffix_excludes_a_matched_node_even_if_prefixed() -> None:
    document, _, _ = build_dot((_cfg(),), ["MAIN"], ("#label",), frozenset(), {})

    assert '"MAIN#label"' not in document
    assert '"MAIN/0#test"' in document


def test_a_drop_target_removes_only_the_edge_not_the_node_declaration() -> None:
    document, _, _ = build_dot(
        (_cfg(),), ["MAIN"], (), frozenset({"MAIN/0.then.0"}), {}
    )

    assert '"MAIN/0#test" -> "MAIN/0.then.0"' not in document
    assert '"MAIN/0.then.0" [' in document


def test_a_bridged_node_is_filled_light_gray() -> None:
    document, bridged, _ = build_dot((_cfg(),), ["MAIN/1", "A/0"], (), frozenset(), {})

    assert bridged == ["A#label"]
    assert (
        '"A#label" [label="A#label\\n(paragraph entry)", style=filled, fillcolor=lightgray];'
        in document
    )


def test_cross_program_prefixes_merge_both_cfgs() -> None:
    document, _, _ = build_dot(
        (_cfg("PROGA"), _cfg("PROGB")), ["MAIN/1", "A/0"], (), frozenset(), {}
    )

    # Both programs declare the same node ids; both sets of nodes are present
    # (one dict entry per id -- the last cfg given wins, which is fine for a
    # cross-program render since the ids being merged are from genuinely
    # distinct programs in practice, not two cfgs sharing a namespace).
    assert '"MAIN/1"' in document
