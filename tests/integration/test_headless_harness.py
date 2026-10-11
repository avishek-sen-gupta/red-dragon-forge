"""CardDemo sign-on (COSGN00C), driven headless through cobol_harness.

Demonstrates the harness's sweet spot: compile one program from source,
stub its XCTL targets, seed one VSAM dataset by field name, drive two
pseudo-conversational turns, assert on both screen output and dispatch
result.

Three scenarios:
  1. Cold start (EIBCALEN=0) -- sign-on screen displayed
  2. Valid admin login -- XCTL to COADM01C (stubbed to RETURN)
  3. Wrong password -- error message on screen
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cics.types import DispatchKind

from cobol_harness.region import CicsSession
from tests.integration.forge_cobol_helpers import make_parser as forge_make_parser

_REPO_ROOT = Path(__file__).parents[2]
_CARDDEMO = _REPO_ROOT / "vendor" / "carddemo" / "app"
_CPY = _CARDDEMO / "cpy"
_CPY_BMS = _CARDDEMO / "cpy-bms"
_CBL = _CARDDEMO / "cbl"

_ENTER = "\x7d"
_TRANSID = "CC00"
_PROGRAM = "COSGN00C"
_MAP = "COSGN0A"


@pytest.fixture
def session(bridge_jar, tmp_path):
    """A CicsSession with COSGN00C compiled, USRSEC seeded with one admin
    user (ADMIN001/PASSWORD), and COADM01C + COMEN01C stubbed as noop
    RETURN programs."""
    parser = forge_make_parser(bridge_jar, copybook_dirs=[_CPY, _CPY_BMS])
    session = CicsSession(
        copybook_dirs=[_CPY, _CPY_BMS],
        vsam_dir=tmp_path / "vsam",
        parser=parser,
    )
    session.vsam.register("USRSEC", record_length=80, key_offset=0, key_length=8)
    rec = session.build_record(
        "CSUSR01Y",
        "SEC-USER-DATA",
        {
            "SEC-USR-ID": "ADMIN001",
            "SEC-USR-FNAME": "ADMIN",
            "SEC-USR-LNAME": "USER",
            "SEC-USR-PWD": "PASSWORD",
            "SEC-USR-TYPE": "A",
        },
        expected_length=80,
    )
    session.vsam.seed("USRSEC", [rec])

    source = (_CBL / "COSGN00C.cbl").read_bytes()
    session.compile_main(source, _PROGRAM)
    session.compile_link_targets(["COADM01C", "COMEN01C"])

    return session


def _cold_start(session: CicsSession):
    """Run the cold-start turn (EIBCALEN=0) and return it."""
    session.region({_TRANSID: _PROGRAM})
    return session.start_turn(_TRANSID, commarea=b"", eibaid=_ENTER, fields={})


def test_cold_start_sends_sign_on_screen(session):
    """Turn 1: EIBCALEN=0, program sends the empty sign-on form and does
    RETURN TRANSID('CC00') COMMAREA(...)."""
    turn = _cold_start(session)

    assert turn.result.kind == DispatchKind.RETURN_TRANSID
    assert turn.screen(_MAP) is not None


def test_valid_admin_login_xctls_to_admin_menu(session):
    """Turn 1: cold start. Turn 2: valid admin credentials -- program
    validates, reads USRSEC, password matches, XCTLs to COADM01C.
    CicsSession surfaces the XCTL as the DispatchResult (the harness's
    _capturing_vm replaces run_cics, so the dispatcher returns the XCTL
    rather than following it into the target program)."""
    turn1 = _cold_start(session)
    commarea = turn1.result.commarea

    session.region({_TRANSID: _PROGRAM})
    turn2 = session.start_turn(
        _TRANSID,
        commarea=commarea,
        eibaid=_ENTER,
        fields={"USERID": "ADMIN001", "PASSWD": "PASSWORD"},
    )

    assert turn2.result.kind == DispatchKind.XCTL
    assert turn2.result.program == "COADM01C"


def test_wrong_password_shows_error(session):
    """Turn 1: cold start. Turn 2: valid user ID but wrong password --
    program reads USRSEC, finds the user, password doesn't match, sends
    the sign-on screen with an error and does RETURN TRANSID."""
    turn1 = _cold_start(session)
    commarea = turn1.result.commarea

    session.region({_TRANSID: _PROGRAM})
    turn2 = session.start_turn(
        _TRANSID,
        commarea=commarea,
        eibaid=_ENTER,
        fields={"USERID": "ADMIN001", "PASSWD": "WRONGPWD"},
    )

    assert turn2.result.kind == DispatchKind.RETURN_TRANSID
    assert "Wrong Password" in turn2.field(_MAP, "ERRMSG")
