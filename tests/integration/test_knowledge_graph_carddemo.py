"""End-to-end test: merge red-dragon's CALL/COPY graph, cicada's CICS flow
graph, and jackal's JCL graph over a small, real, cross-linked slice of
CardDemo, proving the three sources actually connect through a shared
node — not just that each extractor works in isolation. See this module's
plan task (docs/superpowers/plans/2026-07-07-cobol-knowledge-graph.md,
Task 9) for why the CICS side is a synthetic program while JCL/CALL/COPY
use real, unmodified CardDemo source.

Also generates this design's first-cut visualization deliverable:
tests/integration/output/carddemo_knowledge_graph.html.
"""

from __future__ import annotations

from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser, make_cobol_parser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.project.cobol_connections import extract_cobol_connections
from interpreter.project.graph_types import GraphEdge, GraphNode, NodeKind

from cics.flow_map import extract_transaction_flow_graph
from cics.statements import CicsDialectParser

from jackal.jcl_graph import extract_jcl_graph

from knowledge_graph.merge import merge_graph
from knowledge_graph.query import reachable_from
from knowledge_graph.render import render_html


class _ListSink:
    def __init__(self) -> None:
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []

    def add_node(self, node: GraphNode) -> None:
        self.nodes.append(node)

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

_SYNTHETIC_CICS_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNACCT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CVACT01Y.
       01 DFHCOMMAREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS RETURN TRANSID('CAVW') END-EXEC.
           STOP RUN.
"""

_SYNTHETIC_CSD = "DEFINE TRANSACTION(CAVW) GROUP(CARDDEMO) PROGRAM(SYNACCT)\n"

# IBM CICS system copybooks (DFHEIBLK etc.) that cics.preprocessor injects
# into every CICS-strategy program — required alongside the CardDemo cpy/
# dir when parsing the synthetic CICS program.
_CICS_COPYBOOKS = Path(__file__).parents[2] / "cicada" / "cics" / "copybooks"


def test_readaccount_job_and_synthetic_cics_program_share_a_copybook_node(
    carddemo_home: Path, bridge_jar: str, jcl_bridge_jar: str
):
    cpy_dir = carddemo_home / "cpy"
    cbl_dir = carddemo_home / "cbl"

    # 1. JCL graph: real READACCT.jcl (STEP05 runs CBACT01C).
    jcl_text = (carddemo_home / "jcl" / "READACCT.jcl").read_text()
    jcl_nodes, jcl_edges = extract_jcl_graph(jcl_text)

    # 2. CALL/COPY graph: real CBACT01C.cbl (COPYs CVACT01Y, CODATECN;
    #    CALLs COBDATFT, CEE3ABD).
    cobol_parser = make_cobol_parser(copybook_dirs=[cpy_dir])
    call_nodes, call_edges = extract_cobol_connections(
        (cbl_dir / "CBACT01C.cbl").read_bytes(),
        copybook_dirs=[cpy_dir],
        program_source_dirs=[cbl_dir],
        parser=cobol_parser,
    )

    # 3. CICS flow graph: a synthetic program that also COPYs CVACT01Y — the
    #    deliberate cross-source link (see module docstring).
    cics_parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[cpy_dir, _CICS_COPYBOOKS]
    )
    sink = _ListSink()
    extract_transaction_flow_graph(
        csd_source=_SYNTHETIC_CSD,
        bms_mapsets={},
        cobol_sources={"SYNACCT": _SYNTHETIC_CICS_PROGRAM},
        parser=cics_parser,
        sink=sink,
    )
    cics_nodes, cics_edges = sink.nodes, sink.edges

    # extract_transaction_flow_graph only captures CICS-verb flow edges
    # (STARTS/XCTL/LINK/RETURN_TRANSID/SENDS_MAP/...) — it does not walk
    # COPY/CALL relationships. Run the CALL/COPY extractor over the same
    # synthetic program too, so its COPY CVACT01Y edge (PROGRAM SYNACCT ->
    # COPYBOOK CVACT01Y) is part of the merged graph, matching how a real
    # pipeline would run both extractors over every CICS program.
    synacct_call_nodes, synacct_call_edges = extract_cobol_connections(
        _SYNTHETIC_CICS_PROGRAM,
        copybook_dirs=[cpy_dir],
        parser=cobol_parser,
        dialect_parsers=[CicsDialectParser()],
    )

    all_nodes = jcl_nodes + call_nodes + cics_nodes + synacct_call_nodes
    all_edges = jcl_edges + call_edges + cics_edges + synacct_call_edges
    graph = merge_graph(all_nodes, all_edges)

    # The JCL job's batch program and the CICS transaction's program both
    # COPY the same real copybook — one shared node, not two.
    copybook_key = (NodeKind.COPYBOOK, "CVACT01Y")
    assert graph.has_node(copybook_key)

    from_job = reachable_from(graph, (NodeKind.JOB, "READACCT"))
    from_transaction = reachable_from(graph, (NodeKind.TRANSACTION, "CAVW"))
    assert copybook_key in from_job
    assert copybook_key in from_transaction

    # Deliverable: one interactive HTML visualization of this slice.
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "carddemo_knowledge_graph.html"
    render_html(graph, output_path, title="CardDemo Knowledge Graph (READACCT slice)")
    assert output_path.is_file()
