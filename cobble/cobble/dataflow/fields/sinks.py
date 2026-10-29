"""Where a statement's bytes leave the program: the sink, and the operand that carries them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from cics.statements import CicsOperand, ExecCicsStatement, operand_reference
from cobble.dataflow.fields.sink import Sink
from cobble.dataflow.fields.sink_kind import SinkKind
from cobble.dataflow.fields.sink_site import SinkSite
from cobble.dataflow.fields.transfer import Statement
from cobol_asg.cobol_statements import RewriteStatement, WriteStatement
from cobol_asg.ref_mod import RefModOperand

MAP_OUTPUT_SUFFIX = "O"


def _text(statement: ExecCicsStatement, *options: str) -> str:
    return next(
        (
            value.text
            for option in options
            for value in (statement.options.get(option),)
            if isinstance(value, CicsOperand)
        ),
        "",
    )


def _from(statement: ExecCicsStatement, sink: Sink) -> tuple[SinkSite, ...]:
    value = statement.options.get("FROM")
    if not isinstance(value, CicsOperand):
        return ()
    return (SinkSite(sink=sink, operand=operand_reference(value)),)


def _cics_file(statement: ExecCicsStatement) -> tuple[SinkSite, ...]:
    return _from(statement, Sink(SinkKind.FILE, _text(statement, "FILE", "DATASET")))


def _cics_send_map(statement: ExecCicsStatement) -> tuple[SinkSite, ...]:
    """Without FROM, BMS sends the map's symbolic output record; MAPONLY sends no data."""
    if "MAPONLY" in statement.options:
        return ()
    map_name = _text(statement, "MAP", "MAPNAME")
    sink = Sink(SinkKind.MAP, map_name)
    sent = _from(statement, sink)
    if sent:
        return sent
    return (
        SinkSite(sink=sink, operand=RefModOperand(name=map_name + MAP_OUTPUT_SUFFIX)),
    )


def _cics_writeq_ts(statement: ExecCicsStatement) -> tuple[SinkSite, ...]:
    return _from(statement, Sink(SinkKind.TS_QUEUE, _text(statement, "QUEUE", "QNAME")))


def _cics_writeq_td(statement: ExecCicsStatement) -> tuple[SinkSite, ...]:
    return _from(statement, Sink(SinkKind.TD_QUEUE, _text(statement, "QUEUE")))


def _cics_start(statement: ExecCicsStatement) -> tuple[SinkSite, ...]:
    return _from(statement, Sink(SinkKind.TRANSID, _text(statement, "TRANSID")))


_CICS_SINKS: Mapping[str, Callable[[ExecCicsStatement], tuple[SinkSite, ...]]] = (
    MappingProxyType(
        {
            "WRITE": _cics_file,
            "REWRITE": _cics_file,
            "SEND MAP": _cics_send_map,
            "WRITEQ TS": _cics_writeq_ts,
            "WRITEQ TD": _cics_writeq_td,
            "START": _cics_start,
        }
    )
)


def _no_sinks(statement: ExecCicsStatement) -> tuple[SinkSite, ...]:
    return ()


def sinks_of(statement: Statement, files: Mapping[str, str]) -> tuple[SinkSite, ...]:
    """``files`` maps an FD record name to the file it is written to."""
    if isinstance(statement, WriteStatement | RewriteStatement):
        name = statement.record_name.upper()
        return (
            SinkSite(
                sink=Sink(SinkKind.FILE, files[name]), operand=RefModOperand(name=name)
            ),
        )
    if isinstance(statement, ExecCicsStatement):
        handler = _CICS_SINKS.get(statement.verb.upper(), _no_sinks)
        return handler(statement)
    return ()
