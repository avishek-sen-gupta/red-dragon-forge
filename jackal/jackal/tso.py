"""Which programs a TSO batch step runs, read from its SYSTSIN command stream.

A step whose EXEC PGM= names the TSO terminal monitor does not itself do the
work. The monitor reads commands from SYSTSIN, and under DB2 the command that
names the real program is DSN's RUN subcommand::

    //STEP02   EXEC PGM=IKJEFT01
    //SYSTSIN  DD *
      DSN SYSTEM(DSN)
      RUN PROGRAM(PAYROLL) PLAN(PAYPLAN) -
          LIB('BATCH.LOADLIB')
      END
    /*

So a graph built from EXEC PGM= alone attributes that whole step to the
monitor and never mentions PAYROLL. On one production corpus of 860 JCL
members that hid 446 such steps, naming 262 distinct programs, 257 of which
have their own source in the corpus.

Text in, records out: this reads a DD's already-parsed ``in_stream`` lines and
adds no JCL parsing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import reduce

# The TSO terminal monitor program, under each name z/OS ships it. IKJEFT01
# passes neither the last command's return code nor an abend on to the step,
# IKJEFT1A passes the return code, IKJEFT1B passes both -- one monitor, three
# entry points, and the same SYSTSIN stream whichever the step names.
TSO_MONITORS: frozenset[str] = frozenset({"IKJEFT01", "IKJEFT1A", "IKJEFT1B"})

# The DD the monitor reads its commands from. Deliberately not "any in-stream
# DD": SYSTSIN is the monitor's input, while a SYSIN alongside it belongs to
# the program the monitor runs, so a RUN subcommand appearing there would be
# that program's data and not a command anyone executes.
TSO_COMMAND_DD = "SYSTSIN"

# A TSO command continues when its last non-blank character is one of these.
_CONTINUATION = ("-", "+")

# DSN's RUN subcommand. PROGRAM abbreviates to PROG, TSO matches keywords and
# operands without regard to case, and a load module name is at most 8
# characters from the alphanumeric-plus-national set.
_RUN = re.compile(
    r"\bRUN\s+PROG(?:RAM)?\s*\(\s*(?P<program>[A-Z0-9@#$]{1,8})\s*\)"
    r"(?:\s+PLAN\s*\(\s*(?P<plan>[A-Z0-9@#$]{1,8})\s*\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TsoRun:
    """One RUN subcommand: the program, and the DB2 plan it runs under.

    ``plan`` is "" when the subcommand named none -- absent, not unknown: RUN
    without PLAN is legal and takes the plan from the program name.
    """

    program: str
    plan: str = ""


def is_tso_monitor(pgm: str) -> bool:
    """Whether a step's EXEC PGM= names the terminal monitor rather than the
    program doing the work. Tolerates the empty pgm an EXEC PROC= step has."""
    return pgm.upper() in TSO_MONITORS


@dataclass(frozen=True)
class _Fold:
    """A left fold over the cards of one stream: the commands already whole,
    the one being built, and whether the last card ended in ``+``."""

    commands: tuple[str, ...] = ()
    current: str = ""
    drop_leading_blanks: bool = False


def _continues(text: str) -> bool:
    """Whether this card's last non-blank character continues the command."""
    return text[-1:] in _CONTINUATION


def _card_text(state: _Fold, text: str) -> str:
    """One card's contribution to the command being built: its leading blanks
    dropped when the previous card ended in ``+``, and the continuation
    character itself never carried into the joined text."""
    body = text.lstrip() if state.drop_leading_blanks else text
    return body[:-1] if _continues(text) else body


def _absorb(state: _Fold, raw: str) -> _Fold:
    """One card folded in: it either extends the current command or ends it."""
    text = raw.rstrip()
    joined = state.current + _card_text(state, text)
    if _continues(text):
        return _Fold(state.commands, joined, text.endswith("+"))
    return _Fold((*state.commands, joined), "", False)


def _fold_continuations(lines: Iterable[str]) -> tuple[str, ...]:
    """Join TSO continuation lines into whole commands.

    A line continues when its last non-blank character is ``-`` or ``+``; the
    plus removes the next line's leading blanks and the hyphen keeps them.
    Either way the operand text is contiguous across the join, which is all
    this module reads -- the distinction only matters inside a quoted string,
    and no operand read here is quoted.

    In-stream lines arrive blank-padded to the card, so the padding has to go
    before the continuation character is the last character of anything.

    A stream whose last card continues leaves that command unterminated; it is
    kept, because half a command still names whatever it already named.
    """
    folded = reduce(_absorb, lines, _Fold())
    return tuple(
        command for command in (*folded.commands, folded.current) if command.strip()
    )


def tso_runs(lines: Sequence[str]) -> tuple[TsoRun, ...]:
    """Every program the RUN subcommands in one SYSTSIN stream name, in order.

    Repeats are kept rather than collapsed: two RUN subcommands naming the
    same program are two runs of it, and whether that is one graph edge or two
    is the caller's decision, not this function's.
    """
    return tuple(
        TsoRun(
            program=match.group("program").upper(),
            plan=(match.group("plan") or "").upper(),
        )
        for command in _fold_continuations(lines)
        for match in _RUN.finditer(command)
    )
