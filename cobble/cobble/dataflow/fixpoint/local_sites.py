"""Dynamic call sites a program resolves on its own, by reaching definitions over its CFG."""

from __future__ import annotations

from collections.abc import Mapping

from cics.statements import ExecCicsStatement
from cobble.dataflow.fields.aliases import area_extents
from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.transfer import Statement
from cobble.dataflow.fields.values import ValueSet
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.site_values import SiteGraph, site_graph, values_at
from cobble.dataflow.fixpoint.targets import is_program_name
from cobble.dataflow.jumps.discover import transid_operand
from cobble.dataflow.layout import Record
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_memory.field_extent import FieldExtent, Precision

Resolved = tuple[tuple[str, tuple[str, ...]], ...]


def _one_exact(extents: tuple[FieldExtent, ...]) -> tuple[FieldExtent, ...]:
    """The operand's one exact extent, or none when it could be several places."""
    if len(extents) != 1 or extents[0].precision is not Precision.EXACT:
        return ()
    return extents


def _names(values: ValueSet) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                name
                for value in values.values
                for name in (value.decode("utf-8", errors="replace").rstrip(),)
                if is_program_name(name)
            }
        )
    )


def _called(
    cfg: Cfg,
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
) -> tuple[str, ...]:
    """The programs a CALL, LINK or XCTL naming its program by a data item reaches,
    when every definition reaching that item names them."""
    extents = _one_exact(operand_extents(cfg.node(node).target_operand, index).extents)
    found = tuple(values_at(graph, image, node, extent) for extent in extents)
    return _names(found[0]) if found and found[0].complete else ()


def _transaction_values(
    statement: ExecCicsStatement,
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
) -> tuple[str, ...]:
    operand = transid_operand(statement)
    if operand.is_literal:
        return (operand.text.strip("'\"").rstrip(),)
    extents = _one_exact(area_extents(operand.text, index))
    found = tuple(values_at(graph, image, node, extent) for extent in extents)
    return _names(found[0]) if found and found[0].complete else ()


def _started(
    statement: Statement,
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
    programs: Mapping[str, str],
) -> tuple[str, ...]:
    """The programs a RETURN TRANSID's transaction runs, through the CSD."""
    if not isinstance(statement, ExecCicsStatement):
        return ()
    return tuple(
        sorted(
            {
                programs[transid]
                for transid in _transaction_values(statement, graph, image, node, index)
                if transid in programs
            }
        )
    )


def _reached(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
    programs: Mapping[str, str],
) -> tuple[str, ...]:
    if cfg.node(node).transfer in CALL_TRANSFERS:
        return _called(cfg, graph, image, node, index)
    return _started(statements[node], graph, image, node, index, programs)


def local_sites(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    records: tuple[Record, ...],
    entry: str,
    sites: tuple[tuple[str, CallSite], ...],
    programs: Mapping[str, str],
) -> Resolved:
    """Each dynamic site whose program operand every reaching definition names,
    with the programs it reaches; a site any other definition reaches is left out."""
    dynamic = tuple(sorted({node for node, site in sites if site.dynamic}))
    if not dynamic:
        return ()
    graph = site_graph(cfg, statements, index, entry)
    image = initial_image(records, index)
    return tuple(
        (node, callees)
        for node in dynamic
        for callees in (_reached(cfg, statements, graph, image, node, index, programs),)
        if callees
    )
