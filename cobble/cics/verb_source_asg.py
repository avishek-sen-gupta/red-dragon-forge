"""VM-free CICS verb source for the standalone knowledge-graph cobble.

THIS IS THE ONE SEAM FILE — the only ported module permitted to contain real
logic changes (everything else in cobble/ is byte-for-byte + import-rewrite).

Production sources CICS verbs by lowering each program to the VM
(``cics.verb_source_lowering.stream_program_verbs`` →
``cics.coprocessor.build_cics_spec`` → ``cics.strategy.CicsLoweringStrategy`` →
the VM). This module reproduces the SAME ``{program: [CicsVerb]}`` shape from a
typed-ASG walk instead, so the port pulls in no VM:

  * Parse each program to a ``CobolASG`` with the ported ProLeap bridge, with the
    ported ``CicsDialectParser`` registered on the ``_dialect_parsers`` ContextVar
    so EXEC CICS blocks materialise as ``ExecCicsStatement`` (verb + options).
  * Recursively walk the ASG for every ``ExecCicsStatement``.
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

from cobble.cics.flow_graph_core import _verb_edge
from cobble.cics.flow_observer import CicsVerb
from cobble.cics.graph_sink import GraphSink
from cobble.cics.statements import CicsDialectParser, ExecCicsStatement
from cobble.interpreter.cobol import cobol_statements as _cobol_statements
from cobble.interpreter.project.graph_types import GraphNode

logger = logging.getLogger(__name__)


# ── operand → static VALUE resolution (mirrors cics.strategy._field_value /
#    _resolve_operand, which walk ctx._asg.data_fields) ──────────────────────
def _field_value(name, fields):
    """Walk CobolField tree to find a field by name and return its static VALUE, or None."""
    name_upper = name.upper()
    direct = next((f for f in fields if f.name.upper() == name_upper), None)
    if direct is not None:
        return direct.value if direct.value and not direct.value_is_figurative else None
    return next(
        (v for v in (_field_value(name, f.children) for f in fields) if v is not None),
        None,
    )


def _resolve_operand(opt, data_fields):
    if opt is None:
        return None
    if opt.is_literal:
        return opt.text
    resolved = _field_value(opt.text, data_fields)
    return resolved if resolved is not None else opt.text


# ── ASG walk: collect every ExecCicsStatement (including nested in IF/PERFORM/…) ──
def _iter_exec_cics(asg):
    seen: set[int] = set()
    out: list[ExecCicsStatement] = []

    def walk(o) -> None:
        oid = id(o)
        if oid in seen:
            return
        seen.add(oid)
        if isinstance(o, ExecCicsStatement):
            out.append(o)
            return
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            for f in dataclasses.fields(o):
                walk(getattr(o, f.name))
        elif isinstance(o, (list, tuple)):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for x in o.values():
                walk(x)

    walk(asg)
    return out


# Which CicsVerb the strategy's observer emits for each EXEC CICS verb — a faithful
# transcription of the self._observer.on_verb(...) call sites in
# cics.strategy.CicsLoweringStrategy.lower (RETURN/XCTL/LINK/SEND MAP/RECEIVE MAP,
# the VSAM point verbs, and the VSAM browse verbs).
def _statement_to_verb(stmt: ExecCicsStatement, program: str, data_fields):
    verb = stmt.verb
    opts = stmt.options

    def r(key, *fallback):
        opt = opts.get(key)
        for fk in fallback:
            if opt is None:
                opt = opts.get(fk)
        return _resolve_operand(opt, data_fields)

    if verb == "RETURN":
        if "TRANSID" in opts:
            return CicsVerb(
                verb="RETURN_TRANSID",
                program=program,
                map_name=None,
                mapset_name=None,
                xctl_target=None,
                transid=_resolve_operand(opts.get("TRANSID"), data_fields),
            )
        return None
    if verb == "XCTL":
        return CicsVerb(
            verb="XCTL",
            program=program,
            map_name=None,
            mapset_name=None,
            xctl_target=_resolve_operand(opts.get("PROGRAM"), data_fields),
            transid=None,
        )
    if verb == "LINK":
        return CicsVerb(
            verb="LINK",
            program=program,
            map_name=None,
            mapset_name=None,
            xctl_target=_resolve_operand(opts.get("PROGRAM"), data_fields),
            transid=None,
        )
    if verb == "SEND MAP":
        return CicsVerb(
            verb="SEND_MAP",
            program=program,
            map_name=r("MAP", "MAPNAME"),
            mapset_name=_resolve_operand(opts.get("MAPSET"), data_fields),
            xctl_target=None,
            transid=None,
        )
    if verb == "RECEIVE MAP":
        return CicsVerb(
            verb="RECEIVE_MAP",
            program=program,
            map_name=r("MAP", "MAPNAME"),
            mapset_name=_resolve_operand(opts.get("MAPSET"), data_fields),
            xctl_target=None,
            transid=None,
        )
    if verb in (
        "READ",
        "WRITE",
        "REWRITE",
        "DELETE",
        "STARTBR",
        "READNEXT",
        "READPREV",
        "ENDBR",
    ):
        file_opt = opts.get("FILE") or opts.get("DATASET")
        return CicsVerb(
            verb=verb,
            program=program,
            map_name=None,
            mapset_name=None,
            xctl_target=None,
            transid=None,
            file_name=_resolve_operand(file_opt, data_fields),
        )
    return None


def stream_program_verbs(prog_name, raw, parser, bms_mapsets, sink, failures):
    """Parse one program's ASG and stream its CICS-verb graph edges into ``sink``.

    Signature-compatible with cics.verb_source_lowering.stream_program_verbs (the
    production, VM-lowering implementation) so the ported flow_map only swaps the
    import. Isolates + loudly warns on failure, exactly as production does.
    """
    try:
        token = _cobol_statements._dialect_parsers.set((CicsDialectParser(),))
        try:
            asg = parser.parse(raw)
        finally:
            _cobol_statements._dialect_parsers.reset(token)
        for stmt in _iter_exec_cics(asg):
            verb = _statement_to_verb(stmt, prog_name, asg.data_fields)
            if verb is None:
                continue
            edge = _verb_edge(verb, bms_mapsets)
            if edge is None:
                continue
            sink.add_node(GraphNode(id=edge.source, kind=edge.source_kind))
            sink.add_node(GraphNode(id=edge.target, kind=edge.target_kind))
            sink.add_edge(edge)
    except Exception as exc:  # noqa: BLE001 — one bad program must not abort the run
        logger.warning("CICS program %s failed: %s", prog_name, exc, exc_info=True)
        if failures is not None:
            failures.append(f"CICS program {prog_name}: {exc}")
