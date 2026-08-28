"""Scoping for the coprocessor dialect parsers an ASG construction needs.

``parse_statement`` resolves a coprocessor statement type through the
``_dialect_parsers`` ContextVar, whose default is empty, and an unregistered type
raises rather than yielding an opaque statement -- which takes down the whole
program's ASG, not the one statement. So every path that turns bridge JSON into a
``CobolASG`` has to register them, including one that only wants FILE-CONTROL:
there is no way to reach FILE-CONTROL without building the ASG.

Separate from ``verb_source_asg`` (which owns the composition) because that module
is a deliberately faithful transcription of production's observer path, and this
is neither part of that path nor specific to it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from cobble.cics.verb_source_asg import asg_dialect_parsers
from cobble.interpreter.cobol import cobol_statements as _cobol_statements


@contextmanager
def asg_dialect_parsers_registered() -> Iterator[None]:
    """Register the dialect parsers for the duration of an ASG construction."""
    token = _cobol_statements._dialect_parsers.set(asg_dialect_parsers())
    try:
        yield
    finally:
        _cobol_statements._dialect_parsers.reset(token)
