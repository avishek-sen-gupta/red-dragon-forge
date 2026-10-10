"""extract_jcl_graph() — static analysis: the JCL step-sequencing portion of
the shared knowledge graph, built by walking an already-parsed Job (via the
existing parse_jcl — this module adds no new JCL parsing).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from cobble.jcl.job_steps import NamedDd, StepView, expanded_steps
from cobble.knowledge_graph.graph_types import (
    AttrValue,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from jackal.expansion import DirectoryProcLibrary, ProcLibrary, expand_or_fail
from jackal.jcl.parser import parse_jcl
from jackal.model import DirectDSN, DispStatus, InStreamDSN, Job
from jackal.tso import TSO_COMMAND_DD, TsoRun, is_tso_monitor, tso_runs

if TYPE_CHECKING:
    from cobble.corpus_index import CorpusIndex

# What one part of a job contributes: its nodes, then its edges. Built bottom
# up (DD, step, job) and concatenated, so emission order is the walk order.
# ``TypeAlias`` rather than a 3.12 ``type`` statement because the lint config
# still parses this package as 3.11.
Graph: TypeAlias = "tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]"

_DISP_TO_EDGE_KIND: Mapping[DispStatus, EdgeKind] = {
    DispStatus.NEW: EdgeKind.WRITES,
    DispStatus.OLD: EdgeKind.UPDATES,
    DispStatus.SHR: EdgeKind.READS,
    DispStatus.MOD: EdgeKind.WRITES,
}


def _node(kind: NodeKind, node_id: str, corpus_index: CorpusIndex) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind=kind,
        location=corpus_index.resolve_file_path(kind, node_id),
    )


def _step_id(job_name: str, step: StepView) -> str:
    return f"{job_name.upper()}.{step.rendered_name.upper()}"


def _instream_graph(step_id: str, named: NamedDd, corpus_index: CorpusIndex) -> Graph:
    """A DD fed by inline content: its own node, scoped to this occurrence."""
    node = _node(
        NodeKind.INSTREAM_DATA,
        f"{step_id}.{named.rendered_name.upper()}",
        corpus_index,
    )
    edge = GraphEdge(
        source=step_id,
        source_kind=NodeKind.STEP,
        target=node.id,
        target_kind=NodeKind.INSTREAM_DATA,
        kind=EdgeKind.READS,
        attrs={"ddname": named.rendered_name, "text": "\n".join(named.dd.in_stream)},
    )
    return ((node,), (edge,))


def _tso_edge_attrs(step: StepView, run: TsoRun) -> dict[str, AttrValue]:
    """What the edge says about itself: which monitor ran the program, out of
    which DD, and under which DB2 plan. An absent plan is omitted rather than
    empty — RUN without PLAN named none, which is not the same as unknown."""
    return {
        "monitor": step.program.upper(),
        "ddname": TSO_COMMAND_DD,
        **({"plan": run.plan} if run.plan else {}),
    }


def _command_stream_runs(step: StepView) -> tuple[TsoRun, ...]:
    """Every RUN subcommand in the step's command stream, in the order the
    monitor would execute them. Only out of SYSTSIN: a SYSIN alongside it
    belongs to the program the monitor runs, so a RUN subcommand written there
    is that program's data and nothing executes it."""
    return tuple(
        run
        for named in step.dds
        if named.rendered_name.upper() == TSO_COMMAND_DD
        for run in tso_runs(named.dd.in_stream)
    )


def _one_run_per_program(runs: Sequence[TsoRun]) -> tuple[TsoRun, ...]:
    """The first run of each distinct program, in first-sighting order.

    A stream that runs the same program twice describes one relationship
    between that step and that program, and the second sighting carries nothing
    the first does not — the same rule _one_per_identity applies to nodes.
    """
    return tuple(
        next(run for run in runs if run.program == program)
        for program in dict.fromkeys(run.program for run in runs)
    )


def _tso_graph(step_id: str, step: StepView, corpus_index: CorpusIndex) -> Graph:
    """The programs a TSO monitor step runs, named in its own SYSTSIN stream.

    Nothing at all for any other step. For a monitor step it is the one place
    the program doing the work is named: the step's EXEC PGM= names the
    monitor, so without this the graph has the step running IKJEFT01 and
    stopping there. The INSTREAM_DATA node the same DD produces carries the
    command text verbatim, but as an opaque string no traversal can follow.
    """
    if not is_tso_monitor(step.program):
        return ((), ())
    runs = _one_run_per_program(_command_stream_runs(step))
    return (
        tuple(_node(NodeKind.PROGRAM, run.program, corpus_index) for run in runs),
        tuple(
            GraphEdge(
                source=step_id,
                source_kind=NodeKind.STEP,
                target=run.program,
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.TSO_RUNS_PROGRAM,
                attrs=_tso_edge_attrs(step, run),
            )
            for run in runs
        ),
    )


def _dataset_graph(
    step_id: str, named: NamedDd, dsn: DirectDSN, corpus_index: CorpusIndex
) -> Graph:
    status = named.dd.disposition().status
    node = _node(NodeKind.DATASET, dsn.dataset_name().upper(), corpus_index)
    edge = GraphEdge(
        source=step_id,
        source_kind=NodeKind.STEP,
        target=node.id,
        target_kind=NodeKind.DATASET,
        kind=_DISP_TO_EDGE_KIND[status],
        attrs={"ddname": named.rendered_name, "disp": status.value},
    )
    return ((node,), (edge,))


def _dataset_dd_graph(step_id: str, named: NamedDd, corpus_index: CorpusIndex) -> Graph:
    match named.dd.dsn:
        case DirectDSN() as dsn if not named.dd.sysout:
            return _dataset_graph(step_id, named, dsn, corpus_index)
        case _:
            return ((), ())


def _dd_graph(step_id: str, named: NamedDd, corpus_index: CorpusIndex) -> Graph:
    """What one DD contributes — nothing at all, for a DD with no identity."""
    if isinstance(named.dd.dsn, InStreamDSN):
        return _instream_graph(step_id, named, corpus_index)
    return _dataset_dd_graph(step_id, named, corpus_index)


def _nodes_of(graphs: Iterable[Graph]) -> tuple[GraphNode, ...]:
    return tuple(node for nodes, _edges in graphs for node in nodes)


def _edges_of(graphs: Iterable[Graph]) -> tuple[GraphEdge, ...]:
    return tuple(edge for _nodes, edges in graphs for edge in edges)


def _step_graph(job_name: str, step: StepView, corpus_index: CorpusIndex) -> Graph:
    step_id = _step_id(job_name, step)
    step_node = _node(NodeKind.STEP, step_id, corpus_index)
    program_node = _node(NodeKind.PROGRAM, step.program.upper(), corpus_index)
    runs_step = GraphEdge(
        source=job_name.upper(),
        source_kind=NodeKind.JOB,
        target=step_node.id,
        target_kind=NodeKind.STEP,
        kind=EdgeKind.JCL_STEP_RUNS,
        attrs={"proc": step.procs[0].name.upper()} if step.procs else {},
    )
    runs_program = GraphEdge(
        source=step_node.id,
        source_kind=NodeKind.STEP,
        target=program_node.id,
        target_kind=NodeKind.PROGRAM,
        kind=EdgeKind.JCL_STEP_RUNS,
    )
    dd_graphs = tuple(_dd_graph(step_id, named, corpus_index) for named in step.dds)
    tso_nodes, tso_edges = _tso_graph(step_id, step, corpus_index)
    return (
        (step_node, program_node, *_nodes_of(dd_graphs), *tso_nodes),
        (runs_step, runs_program, *_edges_of(dd_graphs), *tso_edges),
    )


def _one_per_identity(nodes: Iterable[GraphNode]) -> list[GraphNode]:
    """One node per (kind, id), in first-sighting order — two DDs naming the
    same dataset are one node, and the second sighting carries nothing the
    first does not."""
    return list({(node.kind, node.id): node for node in nodes}.values())


def _job_to_graph(
    job_name: str, steps: Sequence[StepView], corpus_index: CorpusIndex
) -> tuple[list[GraphNode], list[GraphEdge]]:
    job_node = _node(NodeKind.JOB, job_name.upper(), corpus_index)
    step_graphs = tuple(_step_graph(job_name, step, corpus_index) for step in steps)
    return (
        _one_per_identity((job_node, *_nodes_of(step_graphs))),
        list(_edges_of(step_graphs)),
    )


def extract_jcl_graph(
    jcl_source: str, corpus_index: CorpusIndex, proclib_dirs: Sequence[Path] = ()
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

    One in-stream content is read rather than passed through: the SYSTSIN of a
    step whose program is the TSO terminal monitor. There the commands name the
    program that actually runs, so the step gets a TSO_RUNS_PROGRAM edge to it
    (one per distinct program, attrs carrying the monitor, the DD, and the DB2
    plan where the subcommand named one) alongside its JCL_STEP_RUNS edge to
    the monitor itself. Both edges are true; see jackal.tso.

    TempRef (&&NAME) and BackwardRef (*.STEP.DD) datasets, DummyDSN (DD
    DUMMY), and SYSOUT DDs, are not stable cross-job identities and are not
    represented as nodes at all. A DSN that is one lone unresolved symbol is
    a TempRef in the reading z/OS gives it, and is skipped the same way.

    The job is expanded against proclib_dirs before it is drawn: each PROC
    call found there is replaced by its steps, and one found in none stays a
    step whose program is the PROC's name, with the call's override DDs. An
    expanded step's JOB -> STEP edge carries attrs["proc"] naming the
    outermost PROC it came from, so it's visibly distinguishable from a step
    written directly in the job — following the same "opaque discriminant on
    the edge" precedent as attrs["text"] (SYSIN) and attrs["select_name"]
    (COBOL_FILE). A job whose references do not resolve raises
    ExpansionFailed.
    """
    return jcl_graph_from_job(
        parse_jcl(jcl_source), corpus_index, DirectoryProcLibrary(tuple(proclib_dirs))
    )


def jcl_graph_from_job(
    job: Job, corpus_index: CorpusIndex, library: ProcLibrary
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """``extract_jcl_graph`` for a member already parsed, expanded against ``library``.

    A corpus build parses each member once into a JclStore and reaches the graph
    through here; ``extract_jcl_graph`` above is the entry point for a caller
    holding text rather than a Job. Same graph either way — the split exists only
    so the parse can be hoisted out of the pass.
    """
    expanded = expand_or_fail(job, library)
    return _job_to_graph(expanded.name, expanded_steps(expanded), corpus_index)
