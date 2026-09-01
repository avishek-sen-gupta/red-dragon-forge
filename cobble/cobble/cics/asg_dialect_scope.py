"""The coprocessor dialect parsers an ASG construction needs, and their scope.

``parse_statement`` resolves a coprocessor statement type through the
``_dialect_parsers`` ContextVar, whose default is empty, and an unregistered type
raises rather than yielding an opaque statement -- which takes down the whole
program's ASG, not the one statement. So every path that turns bridge JSON into a
``CobolASG`` has to register them, including one that only wants FILE-CONTROL:
there is no way to reach FILE-CONTROL without building the ASG.

Separate from ``verb_source_asg``, which is a deliberately faithful transcription
of production's observer path: registering parsers is neither part of that path nor
specific to it, and that module is one of this one's consumers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from cobble.cics.statements import CicsDialectParser
from interpreter.cobol import cobol_statements as _cobol_statements
from squall.statements import SqlDialectParser


def asg_dialect_parsers() -> tuple[CicsDialectParser, SqlDialectParser]:
    """The dialect parsers an ASG walk needs registered.

    Production composes these in ``interpreter.project.coprocessor_compile``,
    which threads every coprocessor's parser through at once. This port has a
    single ASG parse, so the composition lives here.

    Cicada's parser is what the graph actually reads — every edge comes from an
    ``ExecCicsStatement``. Squall's is here because a coprocessor statement type
    with no dialect parser is a hard error: ``parse_statement`` raises
    ``Unknown COBOL statement type: 'EXEC_SQL'`` and takes the whole program's
    verbs down with it. Registering it makes an EXEC SQL block parse to opaque
    text that the walk then ignores.
    """
    return (CicsDialectParser(), SqlDialectParser())


@contextmanager
def asg_dialect_parsers_registered() -> Iterator[None]:
    """Register the dialect parsers for the duration of an ASG construction."""
    token = _cobol_statements._dialect_parsers.set(asg_dialect_parsers())
    try:
        yield
    finally:
        _cobol_statements._dialect_parsers.reset(token)
