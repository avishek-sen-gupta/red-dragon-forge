"""
squall.fixed_format
~~~~~~~~~~~~~~~~~~~
A positional model of a fixed-format COBOL source line, and the only sanctioned
way to rewrite one.

The ProLeap bridge is hard-wired to FIXED format (``proleap-bridge/.../Main.java:86``
defaults ``CobolSourceFormatEnum format = CobolSourceFormatEnum.FIXED;`` and never
receives ``-format`` from anywhere in this stack), which is what makes this
positional zone model correct: columns 1-6 are the sequence area, column 7 is the
indicator, columns 8-72 are the code area, and columns 73-80 are the
identification area — fixed by column, never by content.

Why this exists
----------------
A prepass once rewrote a line 20 characters shorter than the statement it
replaced. That shift slid the identification field left, into the code area.
ANTLR's error recovery silently swallowed the following ``01`` group along with
the stray token — exit code 0, no diagnostic, a vanished record declaration.

This module makes that class of bug inexpressible: every rewrite goes through
``with_code``/``replace_span``, which write only the code area (columns 8-72)
and never touch columns 1-7 or 73-80. A rewrite that no longer fits raises
``CodeAreaOverflow`` instead of overflowing into — and silently corrupting —
neighboring zones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_SEQUENCE_END = 6
_INDICATOR_END = 7
_CODE_END = 72
_CODE_WIDTH = _CODE_END - _INDICATOR_END


class CodeAreaOverflow(ValueError):
    """Raised when a rewrite's code does not fit in columns 8-72."""


class InvalidSpan(ValueError):
    """Raised when a ``replace_span`` span cannot address ``lines`` unambiguously.

    A clamped or wrapped-around span would rewrite the wrong lines silently —
    exactly the corruption this module exists to prevent — so a malformed span
    is refused outright rather than guessed at.
    """


@dataclass(frozen=True)
class FixedLine:
    """The four positional zones of one fixed-format COBOL source line."""

    sequence: str
    indicator: str
    code: str
    identification: str


def parse_line(raw: str) -> FixedLine:
    """Split *raw* into its positional zones.

    A line shorter than 7 columns has no indicator (and no sequence beyond what
    it has); a line shorter than 73 columns has no identification area. No zone
    is ever manufactured that the line did not already have.
    """
    return FixedLine(
        sequence=raw[:_SEQUENCE_END],
        indicator=raw[_SEQUENCE_END:_INDICATOR_END],
        code=raw[_INDICATOR_END:_CODE_END],
        identification=raw[_CODE_END:],
    )


def render(line: FixedLine) -> str:
    """Reassemble a line's zones into text.

    Pads the code area out to its full 65-column width only when an
    identification area must be kept in place at column 73; otherwise
    right-strips, so a line that never had trailing zones does not gain them.
    """
    if line.identification:
        return (
            line.sequence
            + line.indicator
            + line.code.ljust(_CODE_WIDTH)
            + line.identification
        )
    return (line.sequence + line.indicator + line.code).rstrip()


def with_code(line: FixedLine, code: str) -> FixedLine:
    """Return *line* with its code area replaced by *code*, verbatim.

    *code* is taken as-is, with no auto-indentation — the caller decides
    Area A vs. Area B placement. Raises ``CodeAreaOverflow`` if *code* does not
    fit in the 65-column code area, rather than truncating it.
    """
    if len(code) > _CODE_WIDTH:
        raise CodeAreaOverflow(
            f"code area is {_CODE_WIDTH} columns wide; got {len(code)}: {code!r}"
        )
    return FixedLine(
        sequence=line.sequence,
        indicator=line.indicator,
        code=code,
        identification=line.identification,
    )


def replace_span(
    lines: Sequence[FixedLine], start: int, end: int, code: str
) -> tuple[FixedLine, ...]:
    """Put *code* on ``lines[start]`` and empty the code area of the rest.

    *end* is inclusive: ``lines[start..end]`` (both ends included) are the span
    being collapsed onto one statement. Every line keeps its own sequence and
    identification fields — only the code area changes.

    Raises ``InvalidSpan`` for any span that cannot address ``lines``
    unambiguously — negative ``start``, ``end < start``, or ``end`` past the
    last index — rather than clamping it. A clamped span silently rewrites the
    wrong lines, which is the exact failure mode this module exists to
    eliminate; ``start == end`` (a single-line span) is legitimate.
    """
    if start < 0 or end < start or end >= len(lines):
        raise InvalidSpan(
            f"span [{start}, {end}] is not valid for {len(lines)} line(s)"
        )
    span = tuple(
        with_code(line, code) if index == start else with_code(line, "")
        for index, line in enumerate(lines[start : end + 1], start=start)
    )
    return tuple(lines[:start]) + span + tuple(lines[end + 1 :])
