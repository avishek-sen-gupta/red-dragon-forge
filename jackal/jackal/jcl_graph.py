"""extract_jcl_graph() — static analysis: the JCL step-sequencing portion of
the shared knowledge graph, built by walking an already-parsed Job (via the
existing parse_jcl — this module adds no new JCL parsing).
"""

from __future__ import annotations

from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind

from jackal.dsn import DirectDSN, InStreamDSN
from jackal.jcl.parser import parse_jcl
from jackal.model import DispStatus, Job

_DISP_TO_EDGE_KIND: dict[DispStatus, EdgeKind] = {
    DispStatus.NEW: EdgeKind.WRITES,
    DispStatus.OLD: EdgeKind.UPDATES,
    DispStatus.SHR: EdgeKind.READS,
    DispStatus.MOD: EdgeKind.WRITES,
}


def _job_to_graph(job: Job) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: dict[tuple[NodeKind, str], GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(kind: NodeKind, node_id: str) -> str:
        nodes.setdefault((kind, node_id), GraphNode(id=node_id, kind=kind))
        return node_id

    job_id = _add_node(NodeKind.JOB, job.name.upper())

    for step in job.steps:
        step_id = _add_node(NodeKind.STEP, f"{job.name.upper()}.{step.name.upper()}")
        edges.append(
            GraphEdge(
                source=job_id,
                source_kind=NodeKind.JOB,
                target=step_id,
                target_kind=NodeKind.STEP,
                kind=EdgeKind.JCL_STEP_RUNS,
            )
        )

        prog_id = _add_node(NodeKind.PROGRAM, step.pgm.upper())
        edges.append(
            GraphEdge(
                source=step_id,
                source_kind=NodeKind.STEP,
                target=prog_id,
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.JCL_STEP_RUNS,
            )
        )

        for dd in step.dds:
            if isinstance(dd.dsn, InStreamDSN):
                instream_id = _add_node(
                    NodeKind.INSTREAM_DATA,
                    f"{job.name.upper()}.{step.name.upper()}.{dd.ddname.upper()}",
                )
                edges.append(
                    GraphEdge(
                        source=step_id,
                        source_kind=NodeKind.STEP,
                        target=instream_id,
                        target_kind=NodeKind.INSTREAM_DATA,
                        kind=EdgeKind.READS,
                        attrs={"ddname": dd.ddname},
                    )
                )
                continue
            if dd.sysout or not isinstance(dd.dsn, DirectDSN):
                continue
            dataset_id = _add_node(NodeKind.DATASET, dd.dsn.name.upper())
            edges.append(
                GraphEdge(
                    source=step_id,
                    source_kind=NodeKind.STEP,
                    target=dataset_id,
                    target_kind=NodeKind.DATASET,
                    kind=_DISP_TO_EDGE_KIND[dd.disp.status],
                    attrs={"ddname": dd.ddname, "disp": dd.disp.status.value},
                )
            )

    return list(nodes.values()), edges


def extract_jcl_graph(jcl_source: str) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse JCL text and return its step-sequencing portion of the shared
    knowledge graph: JOB/STEP/PROGRAM/DATASET/INSTREAM_DATA nodes;
    JCL_STEP_RUNS edges (job->step, in step order, and step->program) and
    READS/WRITES/UPDATES edges (step->dataset, derived from DD disposition —
    NEW/MOD->WRITES, OLD->UPDATES, SHR->READS; the raw DispStatus is kept in
    attrs["disp"]).

    A DD fed by literal inline content (DD *) has no dataset identity to
    read/write — it gets its own INSTREAM_DATA node (id scoped by
    JOB.STEP.DDNAME, so distinct occurrences never collide) and a READS edge
    from its step, instead of being folded into DATASET.

    TempRef (&&NAME) and BackwardRef (*.STEP.DD) datasets, DummyDSN (DD
    DUMMY), and SYSOUT DDs, are not stable cross-job identities and are not
    represented as nodes at all.
    """
    job = parse_jcl(jcl_source)
    return _job_to_graph(job)
