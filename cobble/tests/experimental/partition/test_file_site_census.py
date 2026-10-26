"""File sites counted by the route that resolved each, and unresolved ones by the first gap that explains them."""

from __future__ import annotations

from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.file_site_census import file_site_census
from cobble.experimental.partition.file_site_census_result import FileSiteCensus
from cobble.experimental.partition.file_site_gap import FileSiteGap
from cobble.experimental.partition.knowledge_graph_view import KnowledgeGraph
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, NodeKind


def _site(program: str, node: str, file: str) -> FileSite:
    record = ByteRange(program=program, region="file", start=0, end=4, known=True)
    return FileSite(program, f"{program}/{node}", file, record, False)


def _select(program: str, name: str) -> GraphEdge:
    return GraphEdge(
        source=program,
        source_kind=NodeKind.PROGRAM,
        target=name,
        target_kind=NodeKind.COBOL_FILE,
        kind=EdgeKind.READS,
        attrs={"select_name": name},
    )


def _target(caller: str, node: str, kind: TargetKind) -> TargetSite:
    return TargetSite(caller=caller, node=node, kind=kind, candidates=("NAME",))


def test_unresolved_file_sites_are_counted_by_the_first_gap_that_explains_them() -> (
    None
):
    sites = (
        _site("A", "1", "ACCT"),
        _site("B", "1", "IN-FILE"),
        _site("C", "1", "X"),
        _site("D", "2", "Y"),
        _site("E", "1", "Z"),
        _site("F", "1", "W"),
        _site("G", "1", "V"),
        _site("G", "2", "V"),
    )
    graph = KnowledgeGraph(
        edges=(_select("A", "ACCT"), _select("B", "IN-FILE"), _select("E", "OTHER"))
    )
    targets = (
        _target("A", "1", TargetKind.FILE),
        _target("C", "1", TargetKind.PROGRAM),
        _target("D", "1", TargetKind.FILE),
        _target("F", "9", TargetKind.PROGRAM),
    )

    assert file_site_census(sites, graph, targets) == FileSiteCensus(
        sites=8,
        cics=1,
        batch=1,
        gaps=(
            (FileSiteGap.TARGET_NOT_FILE, (sites[2],)),
            (FileSiteGap.FILE_TARGETS_AT_OTHER_NODES, (sites[3],)),
            (FileSiteGap.SELECTS_UNDER_OTHER_NAMES, (sites[4],)),
            (FileSiteGap.ONLY_NON_FILE_TARGETS, (sites[5],)),
            (FileSiteGap.PROGRAM_UNKNOWN, (sites[6], sites[7])),
        ),
    )
