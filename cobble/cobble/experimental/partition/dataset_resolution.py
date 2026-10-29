"""Each trace file site resolved to its dataset: a CICS site by its resolved file target and the CSD, a batch site by its SELECT, DD and the JCL steps that run its program directly or through CALLs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.origin_kind import OriginKind
from cobble.dataflow.fields.sink_kind import SinkKind
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.dataset_site import DatasetSite
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.knowledge_graph_view import KnowledgeGraph

CANDIDATES = "candidates"
NO_STEP = "no-step"
DD_UNBOUND = "dd-unbound"
UNRESOLVED_FILE = "unresolved-file"
UNRESOLVED_MARK = "?"

_Binding = tuple[str, tuple[str, ...]]


def _written(dep: DepRow, name: str) -> tuple[FileSite, ...]:
    if not dep.source.known:
        return ()
    return (FileSite(dep.program, dep.site, name, dep.source, True),)


def _read(dep: DepRow, name: str) -> tuple[FileSite, ...]:
    if not dep.target.known:
        return ()
    return (FileSite(dep.program, dep.site, name, dep.target, False),)


def _uses(dep: DepRow) -> tuple[FileSite, ...]:
    if dep.sink.kind is SinkKind.FILE and dep.sink.name:
        return _written(dep, dep.sink.name)
    if dep.origin.kind is OriginKind.FILE and dep.origin.name:
        return _read(dep, dep.origin.name)
    return ()


def file_sites(deps: Sequence[DepRow]) -> tuple[FileSite, ...]:
    return tuple(dict.fromkeys(site for dep in deps for site in _uses(dep)))


def _certainty(reasons: tuple[str, ...]) -> Certainty:
    return Certainty.POSSIBLE if reasons else Certainty.EXACT


def _unresolved(site: FileSite, name: str, reasons: tuple[str, ...]) -> DatasetSite:
    return DatasetSite(
        site, f"{UNRESOLVED_MARK}{name}", Certainty.POSSIBLE, reasons, False
    )


def _cics(
    site: FileSite, target: TargetSite, graph: KnowledgeGraph
) -> tuple[DatasetSite, ...]:
    if not target.candidates:
        return (_unresolved(site, site.file, target.reasons),)
    many = (CANDIDATES,) if len(target.candidates) > 1 else ()
    reasons = (*target.reasons, *many)
    return tuple(
        DatasetSite(
            site,
            graph.csd.get(name.rstrip(), name.rstrip()),
            _certainty(reasons),
            reasons,
            True,
        )
        for name in target.candidates
    )


def _joined(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    return (*left, *(reason for reason in right if reason not in left))


def _steps(
    graph: KnowledgeGraph, program: str, reasons: tuple[str, ...], seen: frozenset[str]
) -> tuple[_Binding, ...]:
    direct = tuple((step, reasons) for step in graph.runs.get(program, ()))
    upward = tuple(
        found
        for caller, doubts in graph.callers.get(program, ())
        if caller not in seen
        for found in _steps(graph, caller, _joined(reasons, doubts), seen | {caller})
    )
    return (*direct, *upward)


def _strongest(bindings: Sequence[_Binding]) -> tuple[_Binding, ...]:
    exact = {dsn for dsn, reasons in bindings if not reasons}
    return tuple(
        dict.fromkeys(
            (dsn, reasons)
            for dsn, reasons in bindings
            if dsn not in exact or not reasons
        )
    )


def _batch(site: FileSite, dd: str, graph: KnowledgeGraph) -> tuple[DatasetSite, ...]:
    steps = _steps(graph, site.program, (), frozenset({site.program}))
    if not steps:
        return (_unresolved(site, site.file, (NO_STEP,)),)
    bound = _strongest(
        [
            (graph.bindings[(step, dd)], reasons)
            for step, reasons in steps
            if (step, dd) in graph.bindings
        ]
    )
    if not bound:
        return (_unresolved(site, dd, (DD_UNBOUND,)),)
    return tuple(
        DatasetSite(site, dsn, _certainty(reasons), reasons, True)
        for dsn, reasons in bound
    )


def _resolved(
    site: FileSite, files: Mapping[str, TargetSite], graph: KnowledgeGraph
) -> tuple[DatasetSite, ...]:
    if site.site in files:
        return _cics(site, files[site.site], graph)
    if (site.program, site.file) in graph.selects:
        return _batch(site, graph.selects[(site.program, site.file)], graph)
    return (_unresolved(site, site.file, (UNRESOLVED_FILE,)),)


def file_targets(targets: Sequence[TargetSite]) -> Mapping[str, TargetSite]:
    return {
        f"{target.caller}/{target.node}": target
        for target in targets
        if target.kind is TargetKind.FILE
    }


def dataset_sites(
    sites: Sequence[FileSite], graph: KnowledgeGraph, targets: Sequence[TargetSite]
) -> tuple[DatasetSite, ...]:
    files = file_targets(targets)
    return tuple(found for site in sites for found in _resolved(site, files, graph))
