"""The three-way rule: targets.jsonl rows become graph nodes and edges, and a
dynamic site the artifact never covered is marked not-attempted rather than
silently dropped."""

from __future__ import annotations

import json
from pathlib import Path

from cobble.build_graph import dynamic_target_graph
from cobble.build_graph import (
    NO_DYNAMIC_CALL_TARGETS,
    _covered_sites,
    _dynamic_call_targets,
    _not_attempted_graph,
    _unanswered_sites,
)
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


def test_a_table_covering_one_member_leaves_the_others_not_attempted(
    tmp_path: Path,
) -> None:
    """A partial table must subtract only the sites it answers.

    The fallback used to test whether targets.jsonl existed at all, so a table
    written for a subset of members -- a fields config with a ``members`` filter,
    or a member whose walk the dequeue cap gave up on -- removed every other
    member's dynamic site from the graph outright: no edge, no DYNAMIC_TARGET, and
    nothing saying the site was there.

    A subscripted row answers the site the CICS walk spells without its subscript:
    the two front ends render the operand differently, and matching the rendered
    text marks a resolved menu site not-attempted on top of its candidates.
    """
    table = tmp_path / "targets.jsonl"
    table.write_text(
        "".join(
            json.dumps(
                {
                    "caller": "COMEN01C",
                    "node": node,
                    "transfer": "CICS_XCTL",
                    "expression": expression,
                    "candidates": ["COSGN00C"],
                    "reasons": [],
                    "dropped": [],
                }
            )
            + "\n"
            for node, expression in (
                ("MAIN/1", "CDEMO-TO-PROGRAM"),
                ("MAIN/2", "CDEMO-MENU-OPT-PGMNAME(WS-OPTION)"),
            )
        ),
        encoding="utf-8",
    )
    sites = (
        DynamicSite(program="COMEN01C", transfer="XCTL", expression="CDEMO-TO-PROGRAM"),
        DynamicSite(program="COACTUPC", transfer="XCTL", expression="CDEMO-TO-PROGRAM"),
        DynamicSite(program="COMEN01C", transfer="LINK", expression="CCARD-NEXT-PROG"),
        DynamicSite(
            program="COMEN01C", transfer="XCTL", expression="CDEMO-MENU-OPT-PGMNAME"
        ),
    )

    covered = _covered_sites(_dynamic_call_targets(str(table)))
    unanswered = _unanswered_sites(sites, covered)

    assert covered == frozenset(
        {
            ("COMEN01C", "CDEMO-TO-PROGRAM"),
            ("COMEN01C", "CDEMO-MENU-OPT-PGMNAME"),
        }
    )
    assert unanswered == (sites[1], sites[2])
    assert _unanswered_sites(sites, _covered_sites(NO_DYNAMIC_CALL_TARGETS)) == sites
    nodes, edges = _not_attempted_graph(unanswered, CorpusIndex())
    assert [(n.id, n.attrs["reason"]) for n in nodes] == [
        ("COACTUPC.CDEMO-TO-PROGRAM", "not-attempted"),
        ("COMEN01C.CCARD-NEXT-PROG", "not-attempted"),
    ]
    assert [(e.source, e.kind, e.target) for e in edges] == [
        ("COACTUPC", EdgeKind.XCTL, "COACTUPC.CDEMO-TO-PROGRAM"),
        ("COMEN01C", EdgeKind.LINK, "COMEN01C.CCARD-NEXT-PROG"),
    ]
