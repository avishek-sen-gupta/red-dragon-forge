"""MANUAL regression test: COUSR01C add-user flow (admin menu option 02).

Second increment of the COUSR* series (cicada-ing). First test to exercise a
VSAM mutation — EXEC CICS WRITE — end to end:

  Turn 1-3: admin sign-on -> COADM01C -> ENTER option '02' -> XCTL COUSR01C.
  Turn 4 (COUSR01C, first display): SEND MAP COUSR1A (empty add form) ->
      RETURN TRANSID CU01.
  Turn 5 (COUSR01C, ENTER): RECEIVE MAP -> validate 5 fields ->
      MOVE inputs to SEC-USER-DATA -> EXEC CICS WRITE USRSEC ->
      success message -> RETURN TRANSID CU01.

The WRITE is verified directly against the VSAM engine (read the new key back)
and via the on-screen confirmation message.
"""

from __future__ import annotations

import os
import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.dispatcher import CicsRegion, InputEvent
from cics.types import DispatchKind
from cics.vsam.engine import VsamEngine
from cics.vsam.fct import FctConfig
from cics.vsam.format import write_flat_file
from cics.vsam.seed import seed_vsam
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.integration.cics.bms_tools_helpers import HLASM_EXPORT_BIN
from tests.integration.cics.channel_drain import drain
from tests.integration.cobol_helpers import bridge_jar

_CARDDEMO_HOME = os.environ.get("CARDDEMO_HOME")

pytestmark = pytest.mark.carddemo_e2e

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_USRSEC_RECLN = 80

_DFHENTER = "\x7d"

_ADMIN_ID = "ADMIN001"
_ADMIN_PWD = "ADMINPWD"

# The user we add through COUSR01C.
_NEW_ID = "NEWUSR01"
_NEW_FNAME = "New"
_NEW_LNAME = "User"
_NEW_PWD = "NEWPWD12"
_NEW_TYPE = "U"


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


def _usrsec_record(uid: str, fname: str, lname: str, pwd: str, utype: str) -> bytes:
    rec = (
        _ebcdic(uid, 8)
        + _ebcdic(fname, 20)
        + _ebcdic(lname, 20)
        + _ebcdic(pwd, 8)
        + _ebcdic(utype, 1)
        + _ebcdic("", 23)
    )
    return rec.ljust(_USRSEC_RECLN, b"\x40")[:_USRSEC_RECLN]


def _write_seed_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    # Only the admin user is needed for sign-on; COUSR01C adds the rest.
    write_flat_file(
        data_dir / "USRSEC.dat",
        [_usrsec_record(_ADMIN_ID, "Ada", "Admin", _ADMIN_PWD, "A")],
        _USRSEC_RECLN,
    )


_FCT_YAML = """\
datasets:
  USRSEC:
    record_length: 80
    file: USRSEC.dat
    key_length: 8
"""


def _make_engine(tmp_path: Path) -> VsamEngine:
    data_dir = tmp_path / "data"
    fct_path = tmp_path / "fct.yaml"
    _write_seed_files(data_dir)
    fct_path.write_text(_FCT_YAML)

    fct = FctConfig.from_yaml(fct_path)
    vsam_dir = tmp_path / "vsam"
    seed_vsam(fct_path, data_dir, vsam_dir)
    engine = VsamEngine(fct, vsam_dir)
    engine.load_all()
    return engine


def _drive_to_user_add(tmp_path: Path, bridge_jar):
    """Compile COSGN00C + COADM01C + COUSR01C and drive turns 1-3 (admin path).

    Returns (region, screen_q, engine); the engine is returned so the test can
    assert the WRITE landed in USRSEC.
    """
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    adminmenu_path = app / "cbl" / "COADM01C.cbl"
    useradd_path = app / "cbl" / "COUSR01C.cbl"
    assert useradd_path.is_file(), f"COUSR01C not found: {useradd_path}"

    sym_dir = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=app / "bms",
        out_dir=sym_dir,
        hlasm_export_bin=HLASM_EXPORT_BIN,
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybook_dirs=[sym_dir, app / "cpy", app / "cpy-bms", _CICS_COPYBOOKS],
    )

    engine = _make_engine(tmp_path)
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    context_holder = [None]
    result_holder: list = [None]
    spec = build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    adminmenu = compile_cics_program(adminmenu_path.read_bytes(), parser, spec)
    useradd = compile_cics_program(useradd_path.read_bytes(), parser, spec)

    program_cache = {
        "COSGN00C": signon,
        "COADM01C": adminmenu,
        "COUSR01C": useradd,
    }
    transid_to_program = {"CC00": "COSGN00C", "CA00": "COADM01C", "CU01": "COUSR01C"}
    region = CicsRegion(
        program_cache,
        transid_to_program,
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=2_000_000,
        min_commarea_len=400,
    )

    # Turn 1: admin sign-on -> XCTL COADM01C
    r1 = region.start(
        "CC00",
        commarea=b"\x00" * 100,
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"USERID": _ADMIN_ID, "PASSWD": _ADMIN_PWD}
        ),
    )
    assert r1.kind == DispatchKind.XCTL and (r1.program or "").strip() == "COADM01C"

    # Turn 2: admin menu first display
    drain(screen_q)
    r2 = region.step()
    assert r2.kind == DispatchKind.RETURN_TRANSID

    # Turn 3: ENTER option '02' -> XCTL COUSR01C
    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "02"}))
    assert (
        r3.kind == DispatchKind.XCTL
    ), f"admin option '02' did not XCTL (kind={r3.kind}); expected COUSR01C"
    assert (
        r3.program or ""
    ).strip() == "COUSR01C", (
        f"admin option '02' XCTL'd to {r3.program!r}, expected COUSR01C"
    )

    return region, screen_q, engine


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_user_add_writes_record(tmp_path, bridge_jar):
    """Turn 5 adds a new user via EXEC CICS WRITE; verify the record lands in
    USRSEC and the success message is shown."""
    region, screen_q, engine = _drive_to_user_add(tmp_path, bridge_jar)

    # Pre-condition: the new key does not yet exist.
    rec, _ = engine.read("USRSEC", _NEW_ID.encode("cp037"), 8)
    assert rec is None, "new user unexpectedly present before the add"

    # Turn 4: COUSR01C first display (empty add form)
    drain(screen_q)
    r4 = region.step()
    drain(screen_q)
    assert r4.kind == DispatchKind.RETURN_TRANSID

    # Turn 5: ENTER the new-user fields -> EXEC CICS WRITE
    r5 = region.step(
        input_event=InputEvent(
            eibaid=_DFHENTER,
            fields={
                "USERID": _NEW_ID,
                "FNAME": _NEW_FNAME,
                "LNAME": _NEW_LNAME,
                "PASSWD": _NEW_PWD,
                "USRTYPE": _NEW_TYPE,
            },
        )
    )
    screens = drain(screen_q)
    assert r5.kind == DispatchKind.RETURN_TRANSID
    assert (r5.transid or "").strip() == "CU01"

    # Verify the WRITE against the engine: the new key is now present with the
    # fields we supplied.
    rec, resp = engine.read("USRSEC", _NEW_ID.encode("cp037"), 8)
    assert rec is not None, "new user was not written to USRSEC"
    assert rec[0:8].decode("cp037").strip() == _NEW_ID
    assert rec[8:28].decode("cp037").strip() == _NEW_FNAME
    assert rec[28:48].decode("cp037").strip() == _NEW_LNAME
    assert rec[48:56].decode("cp037").strip() == _NEW_PWD
    assert rec[56:57].decode("cp037") == _NEW_TYPE

    # And the on-screen confirmation message reflects the add.
    msgs = [
        (s.get("fields", {}).get("ERRMSG") or "")
        for s in screens
        if s.get("map") == "COUSR1A"
    ]
    assert any(
        "has been added" in m.lower() for m in msgs
    ), f"add-confirmation message not shown; ERRMSG values={msgs!r}"
