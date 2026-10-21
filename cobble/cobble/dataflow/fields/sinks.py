"""Where a statement's bytes leave the program: the sink, and the operand that carries them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from cics.statements import CicsOperand, ExecCicsStatement, operand_reference
from cobble.dataflow.fields.transfer import Statement
from cobol_asg.cobol_statements import RewriteStatement, WriteStatement
from cobol_asg.ref_mod import RefModOperand

FILE_SINK = "FILE:"
MAP_SINK = "MAP:"
TS_QUEUE_SINK = "TSQ:"
TD_QUEUE_SINK = "TDQ:"
TRANSID_SINK = "TRANSID:"
MAP_OUTPUT_SUFFIX = "O"


@dataclass(frozen=True)
class Sink:
    """One destination outside the program, and the operand whose bytes go there."""

    name: str
    operand: RefModOperand


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


def _from(statement: ExecCicsStatement, sink: str) -> tuple[Sink, ...]:
    value = statement.options.get("FROM")
    if not isinstance(value, CicsOperand):
        return ()
    return (Sink(name=sink, operand=operand_reference(value)),)


def _cics_file(statement: ExecCicsStatement) -> tuple[Sink, ...]:
    return _from(statement, FILE_SINK + _text(statement, "FILE", "DATASET"))


def _cics_send_map(statement: ExecCicsStatement) -> tuple[Sink, ...]:
    """Without FROM, BMS sends the map's symbolic output record; MAPONLY sends no data."""
    if "MAPONLY" in statement.options:
        return ()
    map_name = _text(statement, "MAP", "MAPNAME")
    sink = MAP_SINK + map_name
    sent = _from(statement, sink)
    if sent:
        return sent
    return (Sink(name=sink, operand=RefModOperand(name=map_name + MAP_OUTPUT_SUFFIX)),)


def _cics_writeq_ts(statement: ExecCicsStatement) -> tuple[Sink, ...]:
    return _from(statement, TS_QUEUE_SINK + _text(statement, "QUEUE", "QNAME"))


def _cics_writeq_td(statement: ExecCicsStatement) -> tuple[Sink, ...]:
    return _from(statement, TD_QUEUE_SINK + _text(statement, "QUEUE"))


def _cics_start(statement: ExecCicsStatement) -> tuple[Sink, ...]:
    return _from(statement, TRANSID_SINK + _text(statement, "TRANSID"))


_CICS_SINKS: Mapping[str, Callable[[ExecCicsStatement], tuple[Sink, ...]]] = (
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


def _no_sinks(statement: ExecCicsStatement) -> tuple[Sink, ...]:
    return ()


def sinks_of(statement: Statement, files: Mapping[str, str]) -> tuple[Sink, ...]:
    """``files`` maps an FD record name to the file it is written to."""
    if isinstance(statement, WriteStatement | RewriteStatement):
        name = statement.record_name.upper()
        return (Sink(name=FILE_SINK + files[name], operand=RefModOperand(name=name)),)
    if isinstance(statement, ExecCicsStatement):
        handler = _CICS_SINKS.get(statement.verb.upper(), _no_sinks)
        return handler(statement)
    return ()
