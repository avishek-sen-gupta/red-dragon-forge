"""A fixpoint out-dir read back, member by member, as the dep rows the partition graph and the query take."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from itertools import chain
from pathlib import Path

from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import NO_RANGE, ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.build_corpus import (
    COUNTS_FILE,
    DEFS_FILE,
    GRAPH_FILE,
    MEMBERS_DIR,
    SINKS_FILE,
)
from cobble.dataflow.fixpoint.flow_attrs import FlowAttrs
from cobble.dataflow.fixpoint.member_counts import MemberCounts
from cobble.dataflow.fixpoint.reaching_row import ReachingRow
from cobble.dataflow.fixpoint.sink_row import SinkRow
from cobble.knowledge_graph.graph_file import read_graph_rows
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge
from cobol_memory.region_id import RegionId
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class MissingProvenance(ValueError):
    """A member directory written before the fixpoint wrote provenance."""


def _members(fixpoint_dir: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in (fixpoint_dir / MEMBERS_DIR).iterdir()
            if path.is_dir() and not path.name.endswith(".tmp")
        )
    )


def _stale(directory: Path, why: str) -> MissingProvenance:
    return MissingProvenance(
        f"{directory} has no provenance ({why}); rerun cobble-dataflow-fixpoint with --force"
    )


_Reaching = Mapping[tuple[str, str], ReachingRow]
_UNREACHED = ReachingRow(
    program="", node="", extent="", definers=(), values=(), reasons=()
)


def _definers(directory: Path) -> _Reaching:
    found = (
        ReachingRow.model_validate(row) for row in rows.stream(directory / DEFS_FILE)
    )
    return {(row.node, row.extent): row for row in found}


def _from_entry(source: ByteRange, reaching: ReachingRow) -> bool:
    """Linkage bytes that may still hold what the program was entered with."""
    return (
        source.region == RegionId.LINKAGE.value
        and UnresolvedReason.INBOUND_LINKAGE.value in reaching.reasons
    )


def _attrs(directory: Path, edge: GraphEdge) -> FlowAttrs:
    try:
        return FlowAttrs.model_validate(edge.attrs)
    except ValidationError as error:
        raise _stale(
            directory, "an edge lacks its origin, landing or rebuilt flag"
        ) from error


def _flow(program: str, attrs: FlowAttrs, definers: _Reaching) -> DepRow:
    source = byte_range(attrs.source_extent, program) if not attrs.origin else NO_RANGE
    reaching = definers.get((attrs.node, attrs.source_extent), _UNREACHED)
    return DepRow(
        program=program,
        via="",
        target=byte_range(attrs.target_extent, program),
        origin=attrs.origin,
        source=source,
        site=f"{program}/{attrs.node}",
        definers=tuple(f"{program}/{definer}" for definer in reaching.definers),
        sink="",
        literal=attrs.literal,
        entry=_from_entry(source, reaching),
        landing=attrs.landing,
        rebuilt=attrs.rebuilt,
    )


def _sunk(program: str, row: SinkRow, definers: _Reaching) -> DepRow:
    source = byte_range(row.source_extent, program)
    reaching = definers.get((row.node, row.source_extent), _UNREACHED)
    return DepRow(
        program=program,
        via="",
        target=NO_RANGE,
        origin="",
        source=source,
        site=f"{program}/{row.node}",
        definers=tuple(f"{program}/{definer}" for definer in row.definers),
        sink=row.sink,
        entry=_from_entry(source, reaching),
    )


def _member_rows(directory: Path, number: int, total: int) -> Iterator[DepRow]:
    logger.info("provenance: members read %d/%d (%s)", number, total, directory.name)
    if not (directory / SINKS_FILE).is_file():
        raise _stale(directory, f"no {SINKS_FILE}")
    counts = MemberCounts.model_validate_json(
        (directory / COUNTS_FILE).read_text(encoding="utf-8")
    )
    definers = _definers(directory)
    yield from (
        _flow(counts.program, _attrs(directory, row), definers)
        for row in read_graph_rows(directory / GRAPH_FILE)
        if isinstance(row, GraphEdge) and row.kind is EdgeKind.FLOWS_TO
    )
    yield from (
        _sunk(counts.program, SinkRow.model_validate(row), definers)
        for row in rows.stream(directory / SINKS_FILE)
    )


def provenance(fixpoint_dir: Path) -> Iterator[DepRow]:
    """Every flow and sink row of every finished member, one member's files at a time."""
    members = _members(fixpoint_dir)
    return chain.from_iterable(
        _member_rows(directory, number, len(members))
        for number, directory in enumerate(members, 1)
    )
