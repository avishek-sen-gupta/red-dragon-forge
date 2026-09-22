"""cics_cache.py — EXEC CICS as OUR ASG cache stores it, not as the bridge does.

``cics.statements.CicsDialectParser`` reconstructs an ``ExecCicsStatement`` from
``data["exec_cics_text"]`` -- the raw source text the ProLeap bridge emits. Our
cache (cobble.parsing.parse_corpus) stores ``CobolASG.to_dict()``, and ExecCicsStatement's
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

Subscripts and reference modification survive because cobble writes the cache with
its own serializer -- cobble.cics.cics_operand, which is also the reader used here.
The coarse graph still has one node per name regardless of subscript; the analyses
that resolve an operand to a storage extent are the ones that need the index.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from cics.statements import CicsDialectParser, ExecCicsStatement
from cobble.cics.cics_operand import operand_from_dict
from cobol_asg import cobol_statements as _cobol_statements
from squall.statements import SqlDialectParser


class SerializedCicsDialectParser:
    """Constructs ExecCicsStatement from an ExecCicsStatement.to_dict() payload."""

    def applies(self, data: Mapping) -> bool:
        return data.get("type") == "EXEC_CICS" and "verb" in data

    def parse(self, data: Mapping) -> ExecCicsStatement:
        """A bare flag serializes as null and stays a key with no operand."""
        options = data.get("options") or {}
        return ExecCicsStatement(
            verb=str(data.get("verb", "")),
            options={
                option: operand_from_dict(value) if isinstance(value, Mapping) else None
                for option, value in options.items()
            },
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
