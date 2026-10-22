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
    _verb_edge`` and return the edges; ``flow_map`` writes them, with their
    endpoints, in program order, as production's ``GraphEmittingObserver`` does.

Kept to the smallest faithful reproduction of the strategy's observer path.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from bms_copybook_gen.models import BmsMapSet
from cics.statements import ExecCicsStatement
from cobble.cics.exec_cics_walk import exec_cics_statements
from cobble.cics.flow_graph_core import _verb_edge
from cobble.cics.flow_observer import CicsVerb, DynamicSite
from cobble.knowledge_graph.graph_types import GraphEdge
from cobol_asg.asg_types import CobolASG

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
        case literal if literal.is_literal:
            return _verb(stmt.verb, program, xctl_target=literal.text)
        case named:
            return _verb(stmt.verb, program, program_operand=named.text)


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


def _file_verb(stmt: ExecCicsStatement, program: str, _data_fields):
    """The VSAM point and browse verbs, with DATASET as the older spelling of FILE.

    Like PROGRAM, FILE is not resolved through ``_resolve_operand``: a VALUE may be
    overwritten before the statement runs. A literal is the whole answer, carried
    as ``file_name``; a data item is carried unresolved, as ``file_operand``, for
    the dataflow analysis (or its absence) to answer.
    """
    match stmt.options.get("FILE") or stmt.options.get("DATASET"):
        case None:
            return _verb(stmt.verb, program)
        case literal if literal.is_literal:
            return _verb(stmt.verb, program, file_name=literal.text)
        case named:
            return _verb(stmt.verb, program, file_operand=named.text)


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
    """Every XCTL/LINK, and every file verb, the program named a data item for,
    rather than a literal.

    Not carried as edges: build_graph reads this only when there is no
    targets.jsonl to resolve these sites instead, and it decides that once for
    the whole corpus, not per verb.
    """
    return tuple(
        DynamicSite(program=verb.program, transfer=verb.verb, expression=operand)
        for verb in verbs
        for operand in (_dynamic_operand(verb),)
        if operand
    )


def _dynamic_operand(verb) -> str:
    if verb.verb in _TRANSFER_VERBS:
        return verb.program_operand
    return verb.file_operand


@dataclasses.dataclass(frozen=True)
class VerbStreamResult:
    """One program's contribution: its edges, what failed, and the dynamic sites
    it named.

    The edges come back rather than going straight into a sink, so a program can be
    read in a worker process and its edges written by the one process that owns the
    graph file, in the order a serial run writes them. build_graph needs the
    dynamic sites whether or not targets.jsonl exists, to say a site is merely
    not-attempted rather than reporting nothing for it at all.
    """

    edges: tuple[GraphEdge, ...] = ()
    failures: tuple[str, ...] = ()
    dynamic_sites: tuple[DynamicSite, ...] = ()


def program_verbs(
    prog_name: str,
    member: Path,
    read_asg: AsgReader,
    bms_mapsets: Mapping[str, BmsMapSet],
) -> VerbStreamResult:
    """Read one program's ASG and return its CICS-verb graph edges.

    Isolates + loudly warns on failure, exactly as production does, and returns the
    failure rather than appending it to a list the caller handed down. Named in the
    log before the read: on a corpus where one member takes minutes, the name is the
    only thing that tells a working run from a stuck one.
    """
    logger.debug("CICS flow: reading %s", prog_name)
    try:
        asg = read_asg(member)
        verbs = _program_verbs(asg, prog_name)
        edges = tuple(_program_edges(verbs, bms_mapsets))
    except Exception as exc:  # one bad program must not abort the run
        logger.warning("CICS program %s failed: %s", prog_name, exc, exc_info=True)
        return VerbStreamResult(failures=(f"CICS program {prog_name}: {exc}",))
    return VerbStreamResult(edges=edges, dynamic_sites=_program_dynamic_sites(verbs))
