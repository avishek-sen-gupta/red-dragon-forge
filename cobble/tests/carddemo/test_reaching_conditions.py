"""Reaching conditions on CardDemo, against answers read from the COBOL by hand."""

from __future__ import annotations

import time

from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.program import Program, program_of
from cobble.experimental.horn.reaching_conditions import Report, reaching_conditions
from cobble.parsing.asg_cache import cache_path, first_program_at
from tests.carddemo.conftest import CardDemoRun

SIGNON = "COSGN00C"
USER_MENU = "READ-USER-SEC-FILE/1.when.0.0.then.5.else.0"
ADMIN_MENU = "READ-USER-SEC-FILE/1.when.0.0.then.5.then.0"
TO_THE_MENUS = (
    ("EIBCALEN == 0", "FALSE"),
    ("EIBAID == DFHENTER", "TRUE"),
    ("ERR-FLG-ON (WS-ERR-FLG == 'Y')", "FALSE"),
    ("WS-RESP-CD == 0", "TRUE"),
    ("SEC-USR-PWD == WS-USER-PWD", "TRUE"),
)
ADMIN = "CDEMO-USRTYP-ADMIN (CDEMO-USER-TYPE == 'A')"
BLANK_INPUT_NEVER_REACHES = (
    ("%HANDLER[ANY] RAISED", "never runs on this way", "UNRUN"),
    ("%HANDLER[ANY] RAISED", "never runs on this way", "UNRUN"),
    ("%HANDLER[ANY] RAISED", "never runs on this way", "UNRUN"),
    ("PASSWDI == LOW-VALUES", "if it runs", "FALSE"),
    ("PASSWDI == SPACES", "if it runs", "FALSE"),
    ("USERIDI == LOW-VALUES", "if it runs", "FALSE"),
    ("USERIDI == SPACES", "if it runs", "FALSE"),
)


def _program(run: CardDemoRun, program: str) -> Program:
    with cached_asg_dialect_parsers_registered():
        return program_of(
            first_program_at(cache_path(run.asg, run.cobol / f"{program}.cbl"))
        )


def _text(program: Program, test: str) -> str:
    return program.cfg.node(test).atom.text


def _read(
    program: Program, report: Report
) -> tuple[
    tuple[Answer, tuple[tuple[str, str], ...], tuple[tuple[str, str, str], ...]], ...
]:
    """Each way as its answer, its decisions and its route, by the tests' text."""
    return tuple(
        (
            way.answer,
            tuple((_text(program, d.test), d.outcome.name) for d in way.way.decisions),
            tuple(
                sorted(
                    (_text(program, t.test), t.verdict.value, t.outcome.name)
                    for t in way.route
                )
            ),
        )
        for way in report.ways
    )


def test_signon_reaches_the_user_menu_one_way(carddemo: CardDemoRun) -> None:
    program = _program(carddemo, SIGNON)
    report = reaching_conditions(program, USER_MENU, time.monotonic)

    assert (_read(program, report), report.dropped, report.cut) == (
        (
            (
                Answer.SAT,
                (*TO_THE_MENUS, (ADMIN, "FALSE")),
                BLANK_INPUT_NEVER_REACHES,
            ),
        ),
        0,
        False,
    )


def test_signon_reaches_the_admin_menu_one_way(carddemo: CardDemoRun) -> None:
    program = _program(carddemo, SIGNON)
    report = reaching_conditions(program, ADMIN_MENU, time.monotonic)

    assert (_read(program, report), report.dropped, report.cut) == (
        (
            (
                Answer.SAT,
                (*TO_THE_MENUS, (ADMIN, "TRUE")),
                BLANK_INPUT_NEVER_REACHES,
            ),
        ),
        0,
        False,
    )
