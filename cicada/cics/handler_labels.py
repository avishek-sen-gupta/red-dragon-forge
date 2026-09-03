"""Collect a program's HANDLE CONDITION target paragraphs and number them.

The dispatcher's cascade compares a runtime index against compile-time constants,
so every paragraph a program can transfer to needs an index before the first
fallible command is lowered — and a HANDLE CONDITION may appear textually after
that command. Hence a pre-pass rather than collection during lowering.
"""

from __future__ import annotations

from collections.abc import Sequence

from cics.statements import ExecCicsStatement

_HANDLE = "HANDLE CONDITION"


def collect_handler_labels(
    statements: Sequence[ExecCicsStatement],
) -> dict[str, int]:
    """Paragraph name -> 1-based dispatch index, in first-appearance order.

    Index 0 is reserved for "no handler", which is what LOW-VALUES gives every
    slot of the injected table.
    """
    labels: dict[str, int] = {}
    for stmt in statements:
        if stmt.verb != _HANDLE:
            continue
        for operand in stmt.options.values():
            if operand is None or operand.is_literal:
                continue
            if operand.text not in labels:
                labels = {**labels, operand.text: len(labels) + 1}
    return labels
