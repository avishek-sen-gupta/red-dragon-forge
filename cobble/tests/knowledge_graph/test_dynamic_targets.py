"""The three-way rule: targets.jsonl rows become graph nodes and edges, and a
dynamic site the artifact never covered is marked not-attempted rather than
silently dropped."""

from __future__ import annotations

from cobble.build_graph import dynamic_target_graph
from cobble.build_graph import _not_attempted_graph
from cobble.cics.flow_observer import DynamicSite
from cobble.corpus_index import CorpusIndex
from cobble.knowledge_graph.graph_types import EdgeKind, NodeKind


def test_the_three_edge_forms_and_ids_that_do_not_fuse_across_members() -> None:
    rows = (
        {
            "caller": "PROGA",
            "node": "MAIN/1",
            "transfer": "CICS_XCTL",
            "expression": "WS-PGM",
            "candidates": ["COSGN00C"],
            "reasons": [],
            "dropped": [],
        },
        {
            "caller": "PROGB",
            "node": "MAIN/2",
            "transfer": "CICS_XCTL",
            "expression": "WS-TAB",
            "candidates": ["COACTVWC", "COCRDLIC"],
            "reasons": ["uninitialised"],
            "dropped": [],
        },
        {
            "caller": "PROGC",
            "node": "MAIN/3",
            "transfer": "CICS_LINK",
            "expression": "CDEMO-TO-PROGRAM",
            "candidates": [],
            "reasons": ["inbound-linkage"],
            "dropped": [],
        },
        {
            "caller": "PROGD",
            "node": "MAIN/4",
            "transfer": "CICS_LINK",
            "expression": "CDEMO-TO-PROGRAM",
            "candidates": [],
            "reasons": ["inbound-linkage"],
            "dropped": [],
        },
    )
    nodes, edges = dynamic_target_graph(rows, CorpusIndex())

    assert [(e.source, e.kind, e.target, e.target_kind) for e in edges] == [
        ("PROGA", EdgeKind.XCTL, "COSGN00C", NodeKind.PROGRAM),
        ("PROGB", EdgeKind.XCTL_CANDIDATE, "COACTVWC", NodeKind.PROGRAM),
        ("PROGB", EdgeKind.XCTL_CANDIDATE, "COCRDLIC", NodeKind.PROGRAM),
        ("PROGC", EdgeKind.LINK, "PROGC.CDEMO-TO-PROGRAM", NodeKind.DYNAMIC_TARGET),
        ("PROGD", EdgeKind.LINK, "PROGD.CDEMO-TO-PROGRAM", NodeKind.DYNAMIC_TARGET),
    ]
    assert {n.id for n in nodes if n.kind is NodeKind.DYNAMIC_TARGET} == {
        "PROGC.CDEMO-TO-PROGRAM",
        "PROGD.CDEMO-TO-PROGRAM",
    }
    dynamic_targets = {n.id: n for n in nodes if n.kind is NodeKind.DYNAMIC_TARGET}
    assert dynamic_targets["PROGC.CDEMO-TO-PROGRAM"].attrs == {
        "reason": "inbound-linkage",
        "dropped": [],
    }


def test_a_single_candidate_with_any_reason_is_a_candidate_not_a_fact() -> None:
    rows = (
        {
            "caller": "PROGA",
            "node": "MAIN/1",
            "transfer": "CICS_XCTL",
            "expression": "WS-PGM",
            "candidates": ["COSGN00C"],
            "reasons": ["incomplete-walk"],
            "dropped": [],
        },
    )
    _, edges = dynamic_target_graph(rows, CorpusIndex())

    assert [e.kind for e in edges] == [EdgeKind.XCTL_CANDIDATE]


def test_no_candidates_and_no_reasons_lets_the_dropped_values_explain() -> None:
    """candidates empty with dropped non-empty and reasons empty is a meaningful
    combination, not a gap: every value the site can hold resolved, and none of
    them is a program name -- so the node's reason is blank and its dropped
    values are the whole explanation."""
    rows = (
        {
            "caller": "PROGA",
            "node": "MAIN/1",
            "transfer": "CALL",
            "expression": "WS-PGM",
            "candidates": [],
            "reasons": [],
            "dropped": ["    "],
        },
    )
    nodes, edges = dynamic_target_graph(rows, CorpusIndex())

    assert [e.kind for e in edges] == [EdgeKind.CALL]
    assert nodes[0].attrs == {"reason": "", "dropped": ["    "]}


def test_a_dynamic_site_with_no_artifact_at_all_is_not_attempted() -> None:
    """With no targets.jsonl configured, cobble-build still has to say a dynamic
    site exists -- CicsVerb.program_operand is all it knows, so the node it
    produces names that and nothing more."""
    sites = (
        DynamicSite(program="COACTUPC", transfer="XCTL", expression="CDEMO-TO-PROGRAM"),
    )
    nodes, edges = _not_attempted_graph(sites, CorpusIndex())

    assert [(e.source, e.kind, e.target, e.target_kind) for e in edges] == [
        (
            "COACTUPC",
            EdgeKind.XCTL,
            "COACTUPC.CDEMO-TO-PROGRAM",
            NodeKind.DYNAMIC_TARGET,
        )
    ]
    assert [(n.id, n.attrs) for n in nodes] == [
        ("COACTUPC.CDEMO-TO-PROGRAM", {"reason": "not-attempted", "dropped": []})
    ]
