"""VM-free CICS verb source for the standalone knowledge-graph cobble.

THIS IS THE ONE SEAM FILE — the only ported module permitted to contain real
logic changes (everything else in cobble/ is byte-for-byte + import-rewrite).

Production sources CICS verbs by lowering each program to the VM
(``cics.verb_source_lowering.stream_program_verbs`` →
``cics.coprocessor.build_cics_spec`` → ``cics.strategy.CicsLoweringStrategy`` →
the VM). This module reproduces the SAME ``{program: [CicsVerb]}`` shape from a
typed-ASG walk instead, so the port pulls in no VM:

  * Read each program's ``CobolASG`` through the reader it is handed -- the parse
    cache, in cobble-build -- with the coprocessor dialect parsers (see ``cics.asg_dialect_scope``) registered on the
    ``_dialect_parsers`` ContextVar so EXEC CICS blocks materialise as
    ``ExecCicsStatement`` (verb + options) and EXEC SQL blocks as opaque
    ``ExecSqlStatement`` text rather than aborting the program.
  * Walk the ASG for every ``ExecCicsStatement`` (``exec_cics_walk``), in source
    order and in time linear in the ASG's size.
  * For each, build a ``CicsVerb`` exactly as ``CicsLoweringStrategy.lower``'s
    ``self._observer.on_verb(...)`` calls do — resolving each data-name operand to
    its static VALUE clause via ``_resolve_operand`` / ``_field_value`` (the same
    algorithm strategy.py uses over ``ctx._asg.data_fields``, honouring figurative
    constants by treating ``value_is_figurative`` fields as unresolved).
  * Feed each ``CicsVerb`` through the byte-for-byte ported ``flow_graph_core.
    _verb_edge`` → ``graph_sink``, exactly as production's ``GraphEmittingObserver``.

Kept to the smallest faithful reproduction of the strategy's observer path; the
ported ``flow_map.py`` swaps only its ``stream_program_verbs`` import to point here.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from cics.statements import ExecCicsStatement
from cobble.cics.exec_cics_walk import exec_cics_statements
from cobble.cics.flow_graph_core import _verb_edge
from cobble.cics.flow_observer import CicsVerb, DynamicSite
from cobble.knowledge_graph.graph_types import GraphNode
from cobol_asg.asg_types import CobolASG

if TYPE_CHECKING:
    from cobble.corpus_index import CorpusIndex

logger = logging.getLogger(__name__)

AsgReader = Callable[[Path], CobolASG]


# ── operand → static VALUE resolution (mirrors cics.strategy._field_value /
#    _resolve_operand, which walk ctx._asg.data_fields) ──────────────────────
def _static_value(field):
    """A field's VALUE clause, or nothing when it has none or it is figurative."""
    return field.value if field.value and not field.value_is_figurative else None


def _field_value(name, fields):
    """Walk CobolField tree to find a field by name and return its static VALUE, or None."""
    name_upper = name.upper()
    named = [f for f in fields if f.name.upper() == name_upper]
    if named:
        return _static_value(named[0])
    return next(
        (v for v in (_field_value(name, f.children) for f in fields) if v), None
    )


def _resolve_operand(opt, data_fields):
    match opt:
        case None:
            return None
        case _ if opt.is_literal:
            return opt.text
        case _:
            return _field_value(opt.text, data_fields) or opt.text


# Which CicsVerb the strategy's observer emits for each EXEC CICS verb — a faithful
# transcription of the self._observer.on_verb(...) call sites in
# cics.strategy.CicsLoweringStrategy.lower (RETURN/XCTL/LINK/SEND MAP/RECEIVE MAP,
# the VSAM point verbs, and the VSAM browse verbs).
def _verb(verb: str, program: str, **operands) -> CicsVerb:
    """A CicsVerb with every operand the verb does not carry left "" -- the
    dataclass default, so a caller naming only what it resolved is enough."""
    return CicsVerb(verb=verb, program=program, **operands)


def _return_verb(stmt: ExecCicsStatement, program: str, data_fields):
    """RETURN is only a graph event when it names the next transaction."""
    if "TRANSID" not in stmt.options:
        return None
    return _verb(
        "RETURN_TRANSID",
        program,
        transid=_resolve_operand(stmt.options.get("TRANSID"), data_fields) or "",
    )


def _start_verb(stmt: ExecCicsStatement, program: str, data_fields):
    """START is only a graph event when it names the transaction it dispatches.

    TRANSID is optional in the API (START also carries TERMID/INTERVAL/FROM), and
    the transaction is what the edge points at, so a START without one is nothing
    the graph can record -- the rule RETURN already follows.
    """
    if "TRANSID" not in stmt.options:
        return None
    return _verb(
        "START_TRANSID",
        program,
        transid=_resolve_operand(stmt.options.get("TRANSID"), data_fields) or "",
    )


def _transfer_verb(stmt: ExecCicsStatement, program: str, _data_fields):
    """XCTL and LINK: both name the program they transfer to in PROGRAM(...).

    Unlike every other operand here, PROGRAM is not resolved through
    ``_resolve_operand``: its static-VALUE fallback can report a stale value, and
    with no VALUE at all it falls back further to the field's own name, fabricating
    a PROGRAM node out of a data item. A literal operand is still the whole
    answer, carried as ``xctl_target``. A data-name operand is carried unresolved,
    as ``program_operand``, for the dataflow analysis (or its absence) to answer.
    """
    match stmt.options.get("PROGRAM"):
        case None:
            return _verb(stmt.verb, program)
        case operand if operand.is_literal:
            return _verb(stmt.verb, program, xctl_target=operand.text)
        case operand:
            return _verb(stmt.verb, program, program_operand=operand.text)


def _map_verb(stmt: ExecCicsStatement, program: str, data_fields):
    """SEND MAP / RECEIVE MAP, with MAPNAME as the older spelling of MAP."""
    options = stmt.options
    return _verb(
        stmt.verb.replace(" ", "_"),
        program,
        map_name=_resolve_operand(
            options.get("MAP") or options.get("MAPNAME"), data_fields
        )
        or "",
        mapset_name=_resolve_operand(options.get("MAPSET"), data_fields) or "",
    )


def _file_verb(stmt: ExecCicsStatement, program: str, data_fields):
    """The VSAM point and browse verbs, with DATASET as the older spelling of FILE."""
    options = stmt.options
    return _verb(
        stmt.verb,
        program,
        file_name=_resolve_operand(
            options.get("FILE") or options.get("DATASET"), data_fields
        )
        or "",
    )


_FILE_VERBS = (
    "READ",
    "WRITE",
    "REWRITE",
    "DELETE",
    "STARTBR",
    "READNEXT",
    "READPREV",
    "ENDBR",
)

_VERB_BUILDERS = {
    "RETURN": _return_verb,
    "START": _start_verb,
    "XCTL": _transfer_verb,
    "LINK": _transfer_verb,
    "SEND MAP": _map_verb,
    "RECEIVE MAP": _map_verb,
    **{verb: _file_verb for verb in _FILE_VERBS},
}


def _statement_to_verb(stmt: ExecCicsStatement, program: str, data_fields):
    """The CicsVerb this statement is, or None for a verb the graph does not read."""
    builder = _VERB_BUILDERS.get(stmt.verb)
    return builder(stmt, program, data_fields) if builder else None


# ── one program's verbs, edges and dynamic sites ──────────────────────────────
_TRANSFER_VERBS = ("XCTL", "LINK")


def _program_verbs(asg, prog_name):
    """Every CicsVerb the program's EXEC CICS statements become, in source order."""
    return tuple(
        verb
        for verb in (
            _statement_to_verb(stmt, prog_name, asg.data_fields)
            for stmt in exec_cics_statements(asg)
        )
        if verb
    )


def _program_edges(verbs, bms_mapsets):
    """Every graph edge the program's verbs yield."""
    return [edge for verb in verbs for edge in _verb_edge(verb, bms_mapsets)]


def _program_dynamic_sites(verbs) -> tuple[DynamicSite, ...]:
    """Every XCTL/LINK the program named a data item for, rather than a literal.

    Not carried as edges: build_graph reads this only when there is no
    targets.jsonl to resolve these sites instead, and it decides that once for
    the whole corpus, not per verb.
    """
    return tuple(
        DynamicSite(
            program=verb.program, transfer=verb.verb, expression=verb.program_operand
        )
        for verb in verbs
        if verb.verb in _TRANSFER_VERBS and verb.program_operand
    )


def _endpoint(node_id, kind, corpus_index: CorpusIndex) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind=kind,
        location=corpus_index.resolve_file_path(kind, node_id),
    )


def _emit(edge, sink, corpus_index: CorpusIndex) -> None:
    """An edge and both its endpoints, exactly as GraphEmittingObserver emits them."""
    sink.add_node(_endpoint(edge.source, edge.source_kind, corpus_index))
    sink.add_node(_endpoint(edge.target, edge.target_kind, corpus_index))
    sink.add_edge(edge)


@dataclasses.dataclass(frozen=True)
class VerbStreamResult:
    """One program's contribution: what failed, and the dynamic sites it named.

    Not folded into a plain tuple of failures: build_graph needs the dynamic
    sites whether or not targets.jsonl exists, to say a site is merely
    not-attempted rather than reporting nothing for it at all.
    """

    failures: tuple[str, ...] = ()
    dynamic_sites: tuple[DynamicSite, ...] = ()


def stream_program_verbs(
    prog_name: str,
    member: Path,
    read_asg: AsgReader,
    bms_mapsets,
    sink,
    corpus_index: CorpusIndex,
) -> VerbStreamResult:
    """Read one program's ASG and stream its CICS-verb graph edges into ``sink``.

    Isolates + loudly warns on failure, exactly as production does, and returns the
    failure rather than appending it to a list the caller handed down: what one
    program did is this function's result, not an effect it had on its caller's
    state. Production's ``cics.verb_source_lowering.stream_program_verbs`` takes a
    ``failures`` list instead; the ported ``flow_map`` folds what comes back here,
    so the two differ by that argument alone.
    """
    try:
        asg = read_asg(member)
        verbs = _program_verbs(asg, prog_name)
        for edge in _program_edges(verbs, bms_mapsets):
            _emit(edge, sink, corpus_index)
    except Exception as exc:  # one bad program must not abort the run
        logger.warning("CICS program %s failed: %s", prog_name, exc, exc_info=True)
        return VerbStreamResult(failures=(f"CICS program {prog_name}: {exc}",))
    return VerbStreamResult(dynamic_sites=_program_dynamic_sites(verbs))
