"""Dynamic call sites a program resolves on its own, by reaching definitions over its CFG."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import reduce

from cics.statements import ExecCicsStatement
from cobble.dataflow.fields.aliases import area_extents
from cobble.dataflow.fields.extent import CellIndex, operand_extents
from cobble.dataflow.fields.extent_text import extent_text
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.transfer import Statement, Write
from cobble.dataflow.fields.values import EMPTY, UnresolvedReason, ValueSet, merged
from cobble.dataflow.fixpoint.call_site import CallSite
from cobble.dataflow.fixpoint.definition_kind import DefinitionKind
from cobble.dataflow.fixpoint.site_answer import SiteAnswer
from cobble.dataflow.fixpoint.site_definition import SiteDefinition
from cobble.dataflow.fixpoint.site_doubt import SiteDoubt
from cobble.dataflow.fixpoint.site_values import (
    SiteGraph,
    replaces,
    site_graph,
    touching,
    values_at,
)
from cobble.dataflow.fixpoint.targets import is_program_name
from cobble.dataflow.jumps.discover import transid_operand
from cobble.dataflow.layout import Record
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_memory.field_extent import FieldExtent, Precision

_OWN_STORAGE = frozenset({UnresolvedReason.UNINITIALISED})


def _one_exact(extents: tuple[FieldExtent, ...]) -> tuple[FieldExtent, ...]:
    """The operand's one exact extent, or none when it could be several places."""
    if len(extents) != 1 or extents[0].precision is not Precision.EXACT:
        return ()
    return extents


def _doubts(values: ValueSet) -> tuple[UnresolvedReason | SiteDoubt, ...]:
    by_text = {reason.value: reason for reason in values.reasons}
    return tuple(by_text[text] for text in sorted(by_text))


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


def _answered(found: tuple[ValueSet, ...]) -> SiteAnswer:
    """The program names the operand's values spell, or why they are unknown.

    Uninitialised doubt does not leave a site unknown. It is storage of this
    program's own that no write reached on some path, so it holds no name another
    program supplied, and the combine links such a site to the names its values
    spell and to nothing else. Any other doubt -- a copy from LINKAGE, a value a
    callee wrote -- means some other program may supply a name."""
    if not found:
        return SiteAnswer(doubts=(SiteDoubt.OPERAND_NOT_ONE_EXTENT,))
    held = reduce(merged, found, EMPTY)
    if not held.reasons <= _OWN_STORAGE:
        return SiteAnswer(doubts=_doubts(held))
    return _named(_names(held), _doubts(held))


def _named(
    names: tuple[str, ...], doubts: tuple[UnresolvedReason | SiteDoubt, ...]
) -> SiteAnswer:
    """Resolved to these names; no name at all is reported, and reaches nothing."""
    if not names:
        return SiteAnswer(resolved=True, doubts=(*doubts, SiteDoubt.NO_PROGRAM_NAME))
    return SiteAnswer(resolved=True, callees=names, doubts=doubts)


def _called(
    cfg: Cfg,
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
) -> SiteAnswer:
    """The programs a CALL, LINK or XCTL naming its program by a data item reaches,
    when every definition reaching that item names them."""
    extents = _one_exact(operand_extents(cfg.node(node).target_operand, index).extents)
    return _described(
        _answered(tuple(values_at(graph, image, node, extent) for extent in extents)),
        graph,
        extents,
    )


def _definition(node: str, write: Write, operand: FieldExtent) -> SiteDefinition:
    copied = tuple(
        extent_text(source.extent) for source in write.sources if not source.origin
    )
    return SiteDefinition(
        node=node,
        kind=_kind_of(write, operand, copied),
        values=tuple(
            sorted(
                value.decode("utf-8", errors="replace") for value in write.values.values
            )
        ),
        sources=copied,
        reasons=tuple(sorted(reason.value for reason in write.values.reasons)),
    )


def _kind_of(
    write: Write, operand: FieldExtent, copied: tuple[str, ...]
) -> DefinitionKind:
    if replaces(write, operand):
        return DefinitionKind.LITERAL
    if copied:
        return DefinitionKind.COPY
    return DefinitionKind.OTHER


def _described(
    answer: SiteAnswer, graph: SiteGraph, extents: tuple[FieldExtent, ...]
) -> SiteAnswer:
    """The answer with the operand named and every write touching it listed."""
    return replace(
        answer,
        operand=", ".join(extent_text(extent) for extent in extents),
        definitions=tuple(
            _definition(node, write, extent)
            for extent in extents
            for node, write in touching(graph, extent)
        ),
    )


def _transaction_ids(
    statement: ExecCicsStatement,
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
) -> SiteAnswer:
    operand = transid_operand(statement)
    if operand.is_literal:
        return SiteAnswer(
            resolved=True,
            callees=(operand.text.strip("'\"").rstrip(),),
            operand=operand.text,
        )
    extents = _one_exact(area_extents(operand.text, index))
    return _described(
        _answered(tuple(values_at(graph, image, node, extent) for extent in extents)),
        graph,
        extents,
    )


def _run_by(ids: SiteAnswer, programs: Mapping[str, str]) -> SiteAnswer:
    """The programs the CSD runs for these transaction ids. One the CSD does not
    define runs no program, and the combine, reading the same CSD, links it to
    none. Without a CSD nothing says which program a transaction runs."""
    if not ids.resolved:
        return ids
    if not programs:
        return replace(ids, resolved=False, callees=(), doubts=(SiteDoubt.NO_CSD,))
    return _mapped(ids, programs)


def _mapped(ids: SiteAnswer, programs: Mapping[str, str]) -> SiteAnswer:
    run = tuple(sorted({programs[one] for one in ids.callees if one in programs}))
    if len(run) == len(ids.callees):
        return replace(ids, callees=run)
    return replace(
        ids, callees=run, doubts=(*ids.doubts, SiteDoubt.TRANSACTION_NOT_IN_CSD)
    )


def _started(
    statement: Statement,
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
    programs: Mapping[str, str],
) -> SiteAnswer:
    """The programs a RETURN TRANSID's transaction runs, through the CSD."""
    if not isinstance(statement, ExecCicsStatement):
        return SiteAnswer(doubts=(SiteDoubt.OPERAND_NOT_ONE_EXTENT,))
    return _run_by(_transaction_ids(statement, graph, image, node, index), programs)


def _reached(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    graph: SiteGraph,
    image: Mapping[FieldExtent, ValueSet],
    node: str,
    index: CellIndex,
    programs: Mapping[str, str],
) -> SiteAnswer:
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
) -> tuple[tuple[str, SiteAnswer], ...]:
    """Every dynamic site with what reaching definitions found for it: the programs
    it reaches when every definition reaching its operand names them, otherwise why
    not."""
    dynamic = tuple(sorted({node for node, site in sites if site.dynamic}))
    if not dynamic:
        return ()
    graph = site_graph(cfg, statements, index, entry)
    image = initial_image(records, index)
    return tuple(
        (node, _reached(cfg, statements, graph, image, node, index, programs))
        for node in dynamic
    )
