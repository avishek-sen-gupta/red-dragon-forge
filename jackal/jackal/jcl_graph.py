"""extract_jcl_graph() — static analysis: the JCL step-sequencing portion of
the shared knowledge graph, built by walking an already-parsed Job (via the
existing parse_jcl — this module adds no new JCL parsing).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind

from jackal.dsn import DirectDSN, InStreamDSN, dsn_key
from jackal.jcl.parser import parse_jcl
from jackal.jcl.proc_expand import expand_procs
from jackal.model import DispStatus, Job

_DISP_TO_EDGE_KIND: dict[DispStatus, EdgeKind] = {
    DispStatus.NEW: EdgeKind.WRITES,
    DispStatus.OLD: EdgeKind.UPDATES,
    DispStatus.SHR: EdgeKind.READS,
    DispStatus.MOD: EdgeKind.WRITES,
}


def _job_to_graph(
    job: Job, step_proc: dict[str, str]
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: dict[tuple[NodeKind, str], GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(kind: NodeKind, node_id: str) -> str:
        nodes.setdefault((kind, node_id), GraphNode(id=node_id, kind=kind))
        return node_id

    job_id = _add_node(NodeKind.JOB, job.name.upper())

    for step in job.steps:
        step_id = _add_node(NodeKind.STEP, f"{job.name.upper()}.{step.name.upper()}")
        proc_name = step_proc.get(step.name.upper())
        edges.append(
            GraphEdge(
                source=job_id,
                source_kind=NodeKind.JOB,
                target=step_id,
                target_kind=NodeKind.STEP,
                kind=EdgeKind.JCL_STEP_RUNS,
                attrs={"proc": proc_name} if proc_name else {},
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
                        attrs={
                            "ddname": dd.ddname,
                            "text": "\n".join(dd.in_stream),
                        },
                    )
                )
                continue
            if dd.sysout or not isinstance(dd.dsn, DirectDSN):
                continue
            dataset_id = _add_node(NodeKind.DATASET, dsn_key(dd.dsn).upper())
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


def _step_proc_provenance(job: Job, expanded_job: Job) -> dict[str, str]:
    """Map each expanded step's uppercased name to the PROC name it came
    from. A step whose (uppercased) name matches an outer step's own name
    exactly wasn't expanded (no dot added) — everything else with a dot in
    its name that isn't in the original job is PROC-sourced, and the PROC
    name is the part before the first dot's corresponding original step's
    pgm."""
    original_by_name = {s.name.upper(): s for s in job.steps}
    provenance: dict[str, str] = {}
    for step in expanded_job.steps:
        name = step.name.upper()
        if name in original_by_name:
            continue  # unexpanded, ordinary step
        outer_name = name.split(".", 1)[0]
        outer_step = original_by_name.get(outer_name)
        if outer_step is not None:
            provenance[name] = outer_step.pgm.upper()
    return provenance


def extract_jcl_graph(
    jcl_source: str, proclib_dirs: Sequence[Path] = ()
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse JCL text and return its step-sequencing portion of the shared
    knowledge graph: JOB/STEP/PROGRAM/DATASET/INSTREAM_DATA nodes;
    JCL_STEP_RUNS edges (job->step, in step order, and step->program) and
    READS/WRITES/UPDATES edges (step->dataset, derived from DD disposition —
    NEW/MOD->WRITES, OLD->UPDATES, SHR->READS; the raw DispStatus is kept in
    attrs["disp"]).

    A DD fed by literal inline content (DD *) has no dataset identity to
    read/write — it gets its own INSTREAM_DATA node (id scoped by
    JOB.STEP.DDNAME, so distinct occurrences never collide) and a READS edge
    from its step, instead of being folded into DATASET. That edge's
    attrs["text"] carries the raw in-stream lines verbatim (e.g. IDCAMS
    control statements) as an opaque string — this module does no semantic
    parsing of the content, just passes it through.

    TempRef (&&NAME) and BackwardRef (*.STEP.DD) datasets, DummyDSN (DD
    DUMMY), and SYSOUT DDs, are not stable cross-job identities and are not
    represented as nodes at all.

    proclib_dirs (default empty — no-op) resolves and inlines EXEC PROC=
    calls via expand_procs before building the graph. An expanded step's
    JOB -> STEP edge carries attrs["proc"] naming the PROC it came from, so
    it's visibly distinguishable from a step written directly in the job —
    following the same "opaque discriminant on the edge" precedent as
    attrs["text"] (SYSIN) and attrs["select_name"] (COBOL_FILE).
    """
    job = parse_jcl(jcl_source)
    step_proc: dict[str, str] = {}
    if proclib_dirs:
        expanded_job = expand_procs(job, proclib_dirs)
        step_proc = _step_proc_provenance(job, expanded_job)
        job = expanded_job
    return _job_to_graph(job, step_proc)
