"""Counts file sites by the route that resolved each to a dataset, and the unresolved ones by why."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set

from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.experimental.partition.dataset_resolution import file_targets
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.file_site_census_result import FileSiteCensus
from cobble.experimental.partition.file_site_gap import FileSiteGap
from cobble.experimental.partition.knowledge_graph_view import KnowledgeGraph


def _gap(
    site: FileSite,
    targets: Mapping[str, TargetSite],
    callers: Mapping[TargetKind, Set[str]],
    selecting: Set[str],
) -> FileSiteGap:
    holds = (
        (FileSiteGap.TARGET_NOT_FILE, site.site in targets),
        (
            FileSiteGap.FILE_TARGETS_AT_OTHER_NODES,
            site.program in callers[TargetKind.FILE],
        ),
        (FileSiteGap.SELECTS_UNDER_OTHER_NAMES, site.program in selecting),
        (
            FileSiteGap.ONLY_NON_FILE_TARGETS,
            site.program in callers[TargetKind.PROGRAM],
        ),
    )
    return next((gap for gap, held in holds if held), FileSiteGap.PROGRAM_UNKNOWN)


def file_site_census(
    sites: Sequence[FileSite], graph: KnowledgeGraph, targets: Sequence[TargetSite]
) -> FileSiteCensus:
    files = file_targets(targets)
    cics = tuple(site for site in sites if site.site in files)
    batch = tuple(
        site
        for site in sites
        if site.site not in files and (site.program, site.file) in graph.selects
    )
    resolved = {*cics, *batch}
    sited = {f"{target.caller}/{target.node}": target for target in targets}
    callers = {
        kind: frozenset(target.caller for target in targets if target.kind is kind)
        for kind in TargetKind
    }
    selecting = frozenset(program for program, _ in graph.selects)
    gapped = tuple(
        (_gap(site, sited, callers, selecting), site)
        for site in sites
        if site not in resolved
    )
    return FileSiteCensus(
        sites=len(sites),
        cics=len(cics),
        batch=len(batch),
        gaps=tuple(
            (gap, found)
            for gap in FileSiteGap
            for found in (tuple(site for kind, site in gapped if kind is gap),)
            if found
        ),
    )
