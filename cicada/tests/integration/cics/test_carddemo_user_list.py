"""MANUAL regression test: COUSR00C user-list flow (admin menu option 01).

First increment of the COUSR* user-management series (cicada-ing). Exercises the
ADMIN path — an admin-type user (SEC-USR-TYPE 'A') signs on and is routed to the
admin menu COADM01C (not the regular COMEN01C), then lists users from USRSEC.

  Turn 1 (COSGN00C): admin sign-on -> READ USRSEC -> type 'A' -> XCTL COADM01C.
  Turn 2 (COADM01C, first display): SEND MAP COADM1A -> RETURN TRANSID CA00.
  Turn 3 (COADM01C): ENTER option '01' -> XCTL COUSR00C.
  Turn 4 (COUSR00C, first display): STARTBR USRSEC from LOW-VALUES ->
      READNEXT x N -> SEND MAP COUSR0A -> RETURN TRANSID CU00.

VSAM engine seeded via FctConfig.from_yaml + seed_vsam (USRSEC only).
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

# Seeded users in ascending key order (CSUSR01Y SEC-USR-ID X(8) is the KSDS key;
# 'A' < 'U' so the admin sorts first). Each entry: (id, fname, lname, type).
_USERS = [
    (_ADMIN_ID, "Ada", "Admin", "A"),
    ("USER0001", "First1", "Last1", "U"),
    ("USER0002", "First2", "Last2", "U"),
    ("USER0003", "First3", "Last3", "U"),
    ("USER0004", "First4", "Last4", "U"),
    ("USER0005", "First5", "Last5", "U"),
]


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


def _usrsec_record(uid: str, fname: str, lname: str, pwd: str, utype: str) -> bytes:
    """CSUSR01Y record (80 bytes): ID X(8), FNAME X(20), LNAME X(20), PWD X(8),
    TYPE X(1), FILLER X(23)."""
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
    records = [
        _usrsec_record(
            uid, fname, lname, _ADMIN_PWD if uid == _ADMIN_ID else "PASS0001", utype
        )
        for (uid, fname, lname, utype) in _USERS
    ]
    write_flat_file(data_dir / "USRSEC.dat", records, _USRSEC_RECLN)


_FCT_YAML = """\
datasets:
  USRSEC:
    record_length: 80
    file: USRSEC.dat
    key_length: 8
"""


def _user_list_engine(tmp_path: Path) -> VsamEngine:
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


def _drive_to_user_list(tmp_path: Path, bridge_jar):
    """Compile COSGN00C + COADM01C + COUSR00C and drive turns 1-3 (admin path).

    Returns (region, screen_q) positioned just after the admin-menu XCTL into
    COUSR00C — the caller's next step() runs COUSR00C's first display (turn 4).
    """
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    adminmenu_path = app / "cbl" / "COADM01C.cbl"
    userlist_path = app / "cbl" / "COUSR00C.cbl"
    assert userlist_path.is_file(), f"COUSR00C not found: {userlist_path}"

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

    screen_q: queue.Queue = queue.Queue()
    input_q: queue.Queue = queue.Queue()
    context_holder = [None]
    result_holder: list = [None]
    spec = build_cics_spec(
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=_user_list_engine(tmp_path),
        screen_queue=screen_q,
        input_queue=input_q,
    )

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    adminmenu = compile_cics_program(adminmenu_path.read_bytes(), parser, spec)
    userlist = compile_cics_program(userlist_path.read_bytes(), parser, spec)

    program_cache = {
        "COSGN00C": signon,
        "COADM01C": adminmenu,
        "COUSR00C": userlist,
    }
    transid_to_program = {"CC00": "COSGN00C", "CA00": "COADM01C", "CU00": "COUSR00C"}
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

    # Turn 1: admin sign-on -> XCTL COADM01C (admin menu, not COMEN01C)
    r1 = region.start(
        "CC00",
        commarea=b"\x00" * 100,
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"USERID": _ADMIN_ID, "PASSWD": _ADMIN_PWD}
        ),
    )
    assert (
        r1.kind == DispatchKind.XCTL
    ), f"admin sign-on did not XCTL (kind={r1.kind}); expected COADM01C"
    assert (
        r1.program or ""
    ).strip() == "COADM01C", (
        f"admin sign-on XCTL'd to {r1.program!r}, expected COADM01C (admin menu)"
    )

    # Turn 2: admin menu first display
    drain(screen_q)
    r2 = region.step()
    assert r2.kind == DispatchKind.RETURN_TRANSID

    # Turn 3: ENTER option '01' -> XCTL COUSR00C
    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "01"}))
    assert (
        r3.kind == DispatchKind.XCTL
    ), f"admin option '01' did not XCTL (kind={r3.kind}); expected COUSR00C"
    assert (
        r3.program or ""
    ).strip() == "COUSR00C", (
        f"admin option '01' XCTL'd to {r3.program!r}, expected COUSR00C"
    )

    return region, screen_q


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_user_list_first_page(tmp_path, bridge_jar):
    """Turn 4: COUSR00C browses USRSEC and renders COUSR0A with one row per
    seeded user (ID / first name / last name / type) in ascending key order."""
    region, screen_q = _drive_to_user_list(tmp_path, bridge_jar)

    # Turn 4: COUSR00C first display (XCTL'd in -> no fresh input)
    drain(screen_q)
    r4 = region.step()
    screens = drain(screen_q)

    assert any(
        s.get("map") == "COUSR0A" for s in screens
    ), f"COUSR00C did not render COUSR0A; maps={[s.get('map') for s in screens]}"
    fields = next(s for s in screens if s.get("map") == "COUSR0A")["fields"]

    for slot, (uid, fname, lname, utype) in enumerate(_USERS, start=1):
        usrid_key = f"USRID{slot:02d}"
        fname_key = f"FNAME{slot:02d}"
        lname_key = f"LNAME{slot:02d}"
        utype_key = f"UTYPE{slot:02d}"

        assert (
            fields.get(usrid_key) or ""
        ).strip() == uid, (
            f"{usrid_key}: expected {uid!r}, got {fields.get(usrid_key)!r}"
        )
        assert (
            fields.get(fname_key) or ""
        ).strip() == fname, (
            f"{fname_key}: expected {fname!r}, got {fields.get(fname_key)!r}"
        )
        assert (
            fields.get(lname_key) or ""
        ).strip() == lname, (
            f"{lname_key}: expected {lname!r}, got {fields.get(lname_key)!r}"
        )
        assert (
            fields.get(utype_key) or ""
        ).strip() == utype, (
            f"{utype_key}: expected {utype!r}, got {fields.get(utype_key)!r}"
        )

    assert r4.kind == DispatchKind.RETURN_TRANSID
    assert (r4.transid or "").strip() == "CU00"
