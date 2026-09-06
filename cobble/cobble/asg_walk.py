"""One depth-agnostic descent over an ASG, whatever shape it arrives in.

Statements nest through a dozen different keys -- one per conditional arm, plus
the branch lists -- and compose to arbitrary depth (29+ levels observed).
srccfg.statements names them all, if you need the list. Enumerating those keys
is the defect bead red-dragon-forge-aj3 records: a one-level walk saw 36% of the
corpus's MOVE
statements, and the next statement form the bridge learns silently reopens the
hole for whichever consumer was not updated. So this walks the whole document
and classifies nothing -- a consumer filters for what it handles, which keeps
an unhandled statement form visible instead of mis-typed.

The stack is explicit because the nesting outruns CPython's recursion limit.
That, and ``object`` for a node this classifies nothing about, is why
.pre-commit-config.yaml excludes this file from the fp-lint gate.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import fields, is_dataclass
from typing import TypeVar

from cobol_asg.asg_types import CobolASG, CobolSection
from cobol_asg.cobol_statements import CobolStatementType

StatementT = TypeVar("StatementT")


def _children(node: object) -> tuple[object, ...]:
    if isinstance(node, Mapping):
        return tuple(node.values())
    if isinstance(node, (str, bytes)):
        return ()
    if isinstance(node, Sequence):
        return tuple(node)
    if is_dataclass(node) and not isinstance(node, type):
        return tuple(getattr(node, f.name) for f in fields(node))
    return ()


def descend(node: object) -> Iterator[object]:
    """Every node reachable from ``node``, pre-order, root first.

    Children are pushed in reverse and popped off the same end, which is what
    makes this depth-first. Prepending them instead would pop the previous
    sibling's subtree first -- breadth-ish order, and wrong.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in reversed(_children(current)):
            stack.append(child)


def _section_paragraphs(
    sections: Sequence[CobolSection],
) -> Iterator[Sequence[CobolStatementType]]:
    return (
        paragraph.statements for section in sections for paragraph in section.paragraphs
    )


def _procedure_roots(asg: CobolASG) -> tuple[object, ...]:
    section_statements = tuple(section.statements for section in asg.sections)
    paragraph_statements = tuple(paragraph.statements for paragraph in asg.paragraphs)
    return (
        tuple(asg.statements),
        section_statements,
        tuple(_section_paragraphs(asg.sections)),
        paragraph_statements,
    )


def procedure_statements(
    asg: CobolASG, kinds: tuple[type[StatementT], ...]
) -> Iterator[StatementT]:
    """Every statement of one of ``kinds`` in the program's procedure division.

    Rooted at the statement lists rather than at the ASG, so the descent never
    enters the data division's field trees -- which are large, and hold no
    statements.
    """
    return (
        node
        for root in _procedure_roots(asg)
        for node in descend(root)
        if isinstance(node, kinds)
    )
