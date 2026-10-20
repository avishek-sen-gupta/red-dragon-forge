"""MANUAL regression test: COUSR03C delete-user flow (admin menu option 04).

Fourth increment of the COUSR* series (cicada-ing). Exercises EXEC CICS DELETE:

  Turn 1-3: admin sign-on -> COADM01C -> ENTER option '04' -> XCTL COUSR03C.
  Turn 4 (COUSR03C, first display): empty prompt -> RETURN TRANSID CU03.
  Turn 5 (COUSR03C, ENTER): USRIDIN -> READ USRSEC -> show the user -> RETURN CU03.
  Turn 6 (COUSR03C, PF5): EXEC CICS DELETE USRSEC -> 'has been deleted' -> RETURN.

The DELETE is verified against the VSAM engine (the key is gone) and via the
on-screen confirmation message.
"""

from __future__ import annotations

import os
import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.interval import StartQueue
from cics.dispatcher import CicsRegion, InputEvent
from cics.types import DispatchKind
from cics.vsam.no_record import NoRecord
from cics.vsam.record_read import RecordRead
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.vsam_system import SeedCluster, build_test_system
from tests.integration.cics.bms_tools_helpers import HLASM_EXPORT_BIN
from tests.integration.cics.channel_drain import drain
from tests.integration.cobol_helpers import bridge_jar

_CARDDEMO_HOME = os.environ.get("CARDDEMO_HOME")

pytestmark = pytest.mark.carddemo_e2e

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_USRSEC_RECLN = 80

_DFHENTER = "\x7d"
_DFHPF5 = "\xf5"

_ADMIN_ID = "ADMIN001"
_ADMIN_PWD = "ADMINPWD"

# The user we delete.
_TGT_ID = "USER0002"
_TGT_FNAME = "First2"


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


def _make_engine(tmp_path: Path) -> VsamEngine:
    clusters = (
        SeedCluster(
            "USRSEC",
            80,
            8,
            (
                _usrsec_record(_ADMIN_ID, "Ada", "Admin", _ADMIN_PWD, "A"),
                _usrsec_record("USER0001", "First1", "Last1", "PASS0001", "U"),
                _usrsec_record(_TGT_ID, _TGT_FNAME, "Last2", "PASS0002", "U"),
            ),
        ),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _drive_to_user_delete(tmp_path: Path, bridge_jar):
    """Compile COSGN00C + COADM01C + COUSR03C and drive turns 1-3 (admin path).

    Returns (region, screen_q, engine).
    """
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    adminmenu_path = app / "cbl" / "COADM01C.cbl"
    userdel_path = app / "cbl" / "COUSR03C.cbl"
    assert userdel_path.is_file(), f"COUSR03C not found: {userdel_path}"

    sym_dir = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=app / "bms",
        out_dir=sym_dir,
        hlasm_export_bin=HLASM_EXPORT_BIN,
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(
            dirs=(sym_dir, app / "cpy", app / "cpy-bms", _CICS_COPYBOOKS)
        ),
    )

    engine = _make_engine(tmp_path)
    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    context_holder = [None]
    result_holder: list = [None]
    start_queue = StartQueue()
    program_cache: dict = {}
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache=program_cache,
        start_queue=start_queue,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )
    spec = build_cics_spec()

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    adminmenu = compile_cics_program(adminmenu_path.read_bytes(), parser, spec)
    userdel = compile_cics_program(userdel_path.read_bytes(), parser, spec)

    program_cache.update(
        {
            "COSGN00C": signon,
            "COADM01C": adminmenu,
            "COUSR03C": userdel,
        }
    )
    transid_to_program = {"CC00": "COSGN00C", "CA00": "COADM01C", "CU03": "COUSR03C"}
    region = CicsRegion(
        program_cache,
        transid_to_program,
        screen_q,
        input_q,
        context_holder=context_holder,
        start_queue=start_queue,
        result_holder=result_holder,
        max_steps=2_000_000,
        min_commarea_len=400,
        builtins=runtime.builtins,
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

    # Turn 3: ENTER option '04' -> XCTL COUSR03C
    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "04"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COUSR03C"
    ), f"admin option '04' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COUSR03C"

    return region, screen_q, engine


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_user_delete_removes_record(tmp_path, bridge_jar):
    """Turn 5 reads the user; turn 6 (PF5) DELETEs it. Verify the key is gone
    from USRSEC and the confirmation message is shown."""
    region, screen_q, engine = _drive_to_user_delete(tmp_path, bridge_jar)

    # Pre-condition: the target exists.
    rec_read = engine.read("USRSEC", _TGT_ID.encode("cp037"), 8)
    assert isinstance(rec_read, RecordRead), "target user missing before delete"
    rec = rec_read.record

    # Turn 4: first display (empty prompt)
    drain(screen_q)
    r4 = region.step()
    drain(screen_q)
    assert r4.kind == DispatchKind.RETURN_TRANSID

    # Turn 5: ENTER the user id -> READ -> show the user
    r5 = region.step(
        input_event=InputEvent(eibaid=_DFHENTER, fields={"USRIDIN": _TGT_ID})
    )
    screens5 = drain(screen_q)
    fields5 = [s for s in screens5 if s.get("map") == "COUSR3A"][-1]["fields"]
    assert (
        fields5.get("FNAME") or ""
    ).strip() == _TGT_FNAME, (
        f"read-display FNAME: expected {_TGT_FNAME!r}, got {fields5.get('FNAME')!r}"
    )
    assert r5.kind == DispatchKind.RETURN_TRANSID

    # Turn 6: PF5 -> EXEC CICS DELETE
    r6 = region.step(
        input_event=InputEvent(eibaid=_DFHPF5, fields={"USRIDIN": _TGT_ID})
    )
    screens6 = drain(screen_q)
    assert r6.kind == DispatchKind.RETURN_TRANSID
    assert (r6.transid or "").strip() == "CU03"

    # Verify the DELETE: the key is gone; a neighbouring user is untouched.
    rec_read = engine.read("USRSEC", _TGT_ID.encode("cp037"), 8)
    assert isinstance(rec_read, NoRecord), "target user still present after delete"
    other_read = engine.read("USRSEC", "USER0001".encode("cp037"), 8)
    assert isinstance(other_read, RecordRead), "delete removed the wrong record"
    other = other_read.record

    msgs = [
        (s.get("fields", {}).get("ERRMSG") or "")
        for s in screens6
        if s.get("map") == "COUSR3A"
    ]
    assert any(
        "has been deleted" in m.lower() for m in msgs
    ), f"delete-confirmation message not shown; ERRMSG values={msgs!r}"
