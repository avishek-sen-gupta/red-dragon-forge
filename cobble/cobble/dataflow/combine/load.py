"""Load one program's fixpoint tables from its member directory."""

from collections.abc import Iterable, Mapping
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.program_tables import ProgramTables
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.values import UnresolvedReason
from cobble.dataflow.fixpoint import rows
from cobble.dataflow.fixpoint.flow_attrs import FlowAttrs
from cobble.dataflow.fixpoint.provenance import stale
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump
from cobble.dataflow.jumps.jump_kind import JumpKind
from cobble.dataflow.jumps.rows import jump_from_row
from cobble.dataflow.srccfg.read_kind import ReadKind
from pydantic import ValidationError

_FLOWS_TO = "FLOWS_TO"
_T = TypeVar("_T")


def _grouped(pairs: Iterable[tuple[str, _T]]) -> Mapping[str, tuple[_T, ...]]:
    ordered = sorted((node, at, value) for at, (node, value) in enumerate(pairs))
    return MappingProxyType(
        {
            node: tuple(map(itemgetter(2), group))
            for node, group in groupby(ordered, itemgetter(0))
        }
    )


def _def_fact(row: rows.Row) -> Fact:
    return Fact(
        extent=rows.text(row, "extent"),
        values=rows.strings(row, "values"),
        writers=rows.strings(row, "definers"),
        reasons=tuple(UnresolvedReason(r) for r in rows.strings(row, "reasons")),
    )


def _def_facts(
    member: Path, program: str, jumps: frozenset[str]
) -> tuple[tuple[str, tuple[ByteRange, Fact]], ...]:
    """Every copied read, and what a jump consults to decide where control goes: a
    test's operand or a subscript elsewhere says nothing about the bytes it moves."""
    return tuple(
        (
            node,
            (byte_range(rows.text(row, "extent"), program), _def_fact(row)),
        )
        for row in rows.read(member / "defs.jsonl")
        for node in (rows.text(row, "node"),)
        if rows.text(row, "kind") == ReadKind.COPIED.value or node in jumps
    )


def _operand_fact(row: rows.Row) -> Fact:
    operand = rows.nested(row, "operand")
    return Fact(
        extent=rows.text(operand, "extent"),
        values=rows.strings(operand, "values"),
        writers=rows.strings(operand, "writers"),
        reasons=tuple(UnresolvedReason(r) for r in rows.strings(operand, "reasons")),
    )


def _site(row: rows.Row) -> TargetSite:
    return TargetSite(
        transfer=rows.text(row, "transfer"),
        expression=rows.text(row, "expression"),
        kind=TargetKind(rows.text(row, "kind", TargetKind.PROGRAM.value)),
        operand=_operand_fact(row),
    )


def _sites(member: Path) -> Mapping[str, TargetSite]:
    return MappingProxyType(
        {
            rows.text(row, "node"): _site(row)
            for row in rows.read(member / "targets.jsonl")
        }
    )


def _site_facts(
    sites: Mapping[str, TargetSite], program: str
) -> tuple[tuple[str, tuple[ByteRange, Fact]], ...]:
    return tuple(
        (node, (byte_range(site.operand.extent, program), site.operand))
        for node, site in sites.items()
        if site.operand.extent
    )


def _flows(member: Path, program: str) -> tuple[tuple[str, Flow], ...]:
    return tuple(
        (
            attrs.node,
            Flow(
                attrs.node,
                byte_range(attrs.source_extent, program),
                byte_range(attrs.target_extent, program),
                attrs.origin,
                attrs.landing,
            ),
        )
        for row in rows.read(member / "graph.jsonl")
        if rows.text(row, "type") == "edge" and rows.text(row, "kind") == _FLOWS_TO
        for attrs in (_attrs(member, row),)
    )


def _attrs(member: Path, row: rows.Row) -> FlowAttrs:
    try:
        return FlowAttrs.model_validate(rows.nested(row, "attrs"))
    except ValidationError as error:
        raise stale(
            member, "an edge lacks its typed origin, landing or rebuilt flag"
        ) from error


def _jumps(member: Path) -> tuple[Jump, ...]:
    path = member / "jumps.jsonl"
    if not path.is_file():
        return ()
    return tuple(
        jump_from_row(line) for line in path.read_text().splitlines() if line.strip()
    )


def load_tables(fixpoint_dir: Path, program: str) -> ProgramTables:
    member = fixpoint_dir / "members" / program
    jumps = _jumps(member)
    entries = tuple(jump for jump in jumps if jump.kind is JumpKind.ENTRY)
    real = tuple(jump for jump in jumps if jump.kind is not JumpKind.ENTRY)
    sites = _sites(member)
    return ProgramTables(
        program=program,
        facts=_grouped(
            (
                *_def_facts(member, program, frozenset(j.node for j in real)),
                *_site_facts(sites, program),
            )
        ),
        flows=_grouped(_flows(member, program)),
        jumps=MappingProxyType({jump.node: jump for jump in real}),
        received=tuple(
            (area.param, byte_range(area.extent, program))
            for entry in entries[:1]
            for area in entry.areas
        ),
        sites=sites,
    )
