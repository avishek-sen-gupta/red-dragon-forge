"""cics_cache.py — EXEC CICS as OUR ASG cache stores it, not as the bridge does.

``cics.statements.CicsDialectParser`` reconstructs an ``ExecCicsStatement`` from
``data["exec_cics_text"]`` -- the raw source text the ProLeap bridge emits. Our
cache (parse_corpus.py) stores ``CobolASG.to_dict()``, and ExecCicsStatement's
to_dict writes the ALREADY PARSED form instead:

    {"type": "EXEC_CICS", "verb": "READ",
     "options": {"INTO": {"text": "LAYOUT1-REC", "is_literal": false},
                 "NOHANDLE": null}}

There is no ``exec_cics_text`` in that, so cicada's parser returns
``ExecCicsStatement(verb="", options={})`` for every one of them -- silently. All
1409 EXEC CICS statements in a 120-program sample came back empty before this
existed, which is why the first depgraph run built no CICS edges at all.

So: a dialect parser for the serialized form, registered AHEAD of cicada's, which
still handles bridge JSON when a program is parsed fresh. ``parse_statement``
takes the first parser whose ``applies`` is True, and this one requires "verb" to
be present, so the two cannot collide.

Subscripts and reference modification are dropped by ExecCicsStatement.to_dict
and therefore cannot be recovered here. The coarse graph has one node per name
regardless of subscript, so nothing it needs is lost.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from cics.statements import CicsDialectParser, CicsOperand, ExecCicsStatement
from cobol_asg import cobol_statements as _cobol_statements
from squall.statements import SqlDialectParser


def _operand(data: object) -> CicsOperand | None:
    """One serialized option value as an operand, or None for a bare flag.

    NOHANDLE and RESP carry no value and serialize as null, which is the same
    thing cicada's parser produces for them -- a key present with no operand.
    """
    if not isinstance(data, dict):
        return None
    return CicsOperand(
        text=str(data.get("text", "")),
        is_literal=bool(data.get("is_literal", False)),
    )


class SerializedCicsDialectParser:
    """Constructs ExecCicsStatement from an ExecCicsStatement.to_dict() payload."""

    def applies(self, data: dict) -> bool:
        return data.get("type") == "EXEC_CICS" and "verb" in data

    def parse(self, data: dict) -> ExecCicsStatement:
        options = data.get("options") or {}
        return ExecCicsStatement(
            verb=str(data.get("verb", "")),
            options={key: _operand(value) for key, value in options.items()},
        )


@contextmanager
def cached_asg_dialect_parsers_registered() -> Iterator[None]:
    """Dialect parsers for reading the depgraph's ASG cache.

    The serialized-CICS parser first, then the two
    ``cobble.cics.asg_dialect_scope`` registers -- cicada's (bridge JSON) and
    squall's (EXEC SQL, which stays opaque text; without it a program containing
    one raises ``Unknown COBOL statement type: 'EXEC_SQL'`` and loses every
    statement it has).
    """
    parsers = (
        SerializedCicsDialectParser(),
        CicsDialectParser(),
        SqlDialectParser(),
    )
    token = _cobol_statements._dialect_parsers.set(parsers)
    try:
        yield
    finally:
        _cobol_statements._dialect_parsers.reset(token)
