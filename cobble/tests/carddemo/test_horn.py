"""The Horn lowering's answers on CardDemo sign-on, against answers read from COSGN00C.cbl by hand."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import pytest
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.dataflow.fields.extent_line import ExtentLine
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.condition import Condition, Op
from cobble.experimental.horn.lower import HornSystem, lower
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import program_of
from cobble.experimental.horn.reaches import reaches
from cobble.parsing.asg_cache import cache_path, first_program_at
from tests.carddemo.conftest import CardDemoRun

logger = logging.getLogger(__name__)

SIGNON = "COSGN00C"
USER_MENU = Point(SIGNON, "READ-USER-SEC-FILE/1.when.0.0.then.5.else.0")
ADMIN_MENU = Point(SIGNON, "READ-USER-SEC-FILE/1.when.0.0.then.5.then.0")


@pytest.fixture(scope="module")
def signon(carddemo: CardDemoRun) -> HornSystem:
    extents = tuple(
        ExtentLine.model_validate_json(line)
        for line in carddemo.extents.read_text().splitlines()
    )
    with cached_asg_dialect_parsers_registered():
        asg = first_program_at(
            cache_path(carddemo.asg, carddemo.cobol / f"{SIGNON}.cbl")
        )
        return lower(program_of(asg, extents))


def _ask(system: HornSystem, point: Point, conditions: Sequence[Condition]) -> Answer:
    verdict = reaches(system, point, conditions, time.perf_counter)
    logger.info(
        "%s %s: %s in %.3fs", point.node, conditions, verdict.answer, verdict.seconds
    )
    return verdict.answer


def test_signon_can_transfer_to_the_user_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:230 IF CDEMO-USRTYP-ADMIN, :235-237 ELSE EXEC CICS XCTL
    PROGRAM ('COMEN01C'). Some run reaches it."""
    assert _ask(signon, USER_MENU, ()) == Answer.SAT


def test_signon_can_transfer_to_the_admin_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:230-232 IF CDEMO-USRTYP-ADMIN EXEC CICS XCTL PROGRAM
    ('COADM01C'). Some run reaches it."""
    assert _ask(signon, ADMIN_MENU, ()) == Answer.SAT


def test_signon_never_sends_an_admin_to_the_user_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:227 MOVE SEC-USR-TYPE TO CDEMO-USER-TYPE, then :230 IF
    CDEMO-USRTYP-ADMIN, which COCOM01Y.cpy:27 declares as VALUE 'A'. The XCTL to
    COMEN01C is on the ELSE, and nothing writes CDEMO-USER-TYPE between the test and
    the XCTL."""
    admin = Condition("CDEMO-USER-TYPE", Op.EQ, "'A'")
    assert _ask(signon, USER_MENU, (admin,)) == Answer.UNSAT


def test_signon_never_sends_a_user_to_the_admin_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:227 and :230, as above: the XCTL to COADM01C is on the THEN of
    CDEMO-USER-TYPE = 'A'."""
    other = Condition("CDEMO-USER-TYPE", Op.NE, "'A'")
    assert _ask(signon, ADMIN_MENU, (other,)) == Answer.UNSAT
