"""MANUAL regression test: COACTVWC account-view flow (menu option 01).

A multi-file READ join: enter an account id, COACTVWC reads CXACAIX (acct->cust
xref) to find the customer, then ACCTDAT and CUSTDAT, and renders CACTVWA with
account + customer details.

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '01' -> XCTL COACTVWC.
  Turn 4: first display (prompt for account).
  Turn 5: ENTER acct -> READ CXACAIX + ACCTDAT + CUSTDAT -> detail.
"""

from __future__ import annotations

import os
import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.interval import StartQueue
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
_ACCT_RECLN = 300
_XREF_RECLN = 50
_CUST_RECLN = 500

_DFHENTER = "\x7d"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

_ACCT_ID = "00000000001"
_CUST_ID = "000000001"
_CARD_NUM = "4111111111111111"
_FNAME = "JOHN"
_MNAME = "Q"
_LNAME = "PUBLIC"
_DOB = "1980-01-15"
_STATUS = "Y"


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


def _num(s: str, n: int) -> bytes:
    return s.zfill(n)[:n].encode("cp037")


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


def _acct_record() -> bytes:
    """CVACT01Y account record (300 bytes): ID@0, STATUS@11, CURR-BAL@12 (1000.00),
    CREDIT-LIMIT@24 (5000.00)."""
    rec = (
        _num(_ACCT_ID, 11)
        + _ebcdic(_STATUS, 1)
        + _num("000000100000", 12)  # ACCT-CURR-BAL -> 1000.00
        + _num("000000500000", 12)  # ACCT-CREDIT-LIMIT -> 5000.00
        + _num("0", 12)  # cash limit
        + _ebcdic("2020-01-01", 10)  # open date
        + _ebcdic("", 10)
        + _ebcdic("", 10)
        + _num("0", 12)
        + _num("0", 12)
        + _ebcdic("", 10)
        + _ebcdic("", 10)  # group id
        + _ebcdic("", 178)
    )
    return rec.ljust(_ACCT_RECLN, b"\x40")[:_ACCT_RECLN]


def _xref_record() -> bytes:
    """CVACT03Y (50 bytes): CARD-NUM@0, CUST-ID 9(9)@16, ACCT-ID 9(11)@25 (key)."""
    rec = (
        _ebcdic(_CARD_NUM, 16)
        + _num(_CUST_ID, 9)
        + _num(_ACCT_ID, 11)
        + _ebcdic("", 14)
    )
    return rec.ljust(_XREF_RECLN, b"\x40")[:_XREF_RECLN]


def _cust_record() -> bytes:
    """CVCUS01Y customer (500 bytes): ID 9(9)@0, FIRST X(25)@9, MIDDLE@34, LAST@59,
    ... SSN 9(9)@279, DOB X(10)@308."""
    rec = (
        _num(_CUST_ID, 9)
        + _ebcdic(_FNAME, 25)
        + _ebcdic(_MNAME, 25)
        + _ebcdic(_LNAME, 25)
        + _ebcdic("1 MAIN ST", 50)  # addr-1
        + _ebcdic("", 50)  # addr-2
        + _ebcdic("SPRINGFIELD", 50)  # addr-3 (city)
        + _ebcdic("IL", 2)
        + _ebcdic("USA", 3)
        + _ebcdic("62701", 10)
        + _ebcdic("555-0001", 15)
        + _ebcdic("", 15)
        + _num("123456789", 9)  # SSN
        + _ebcdic("DL12345", 20)  # govt id
        + _ebcdic(_DOB, 10)  # DOB
        + _ebcdic("", 10)  # eft
        + _ebcdic("Y", 1)  # pri holder
        + _num("750", 3)  # FICO
        + _ebcdic("", 168)
    )
    return rec.ljust(_CUST_RECLN, b"\x40")[:_CUST_RECLN]


def _write_seed_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    write_flat_file(
        data_dir / "USRSEC.dat",
        [_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U")],
        _USRSEC_RECLN,
    )
    write_flat_file(data_dir / "ACCTDAT.dat", [_acct_record()], _ACCT_RECLN)
    write_flat_file(data_dir / "CXACAIX.dat", [_xref_record()], _XREF_RECLN)
    write_flat_file(data_dir / "CUSTDAT.dat", [_cust_record()], _CUST_RECLN)


_FCT_YAML = """\
datasets:
  USRSEC:
    record_length: 80
    file: USRSEC.dat
    key_length: 8
  ACCTDAT:
    record_length: 300
    file: ACCTDAT.dat
    key_length: 11
  CXACAIX:
    record_length: 50
    file: CXACAIX.dat
    key_length: 11
    key_offset: 25
  CUSTDAT:
    record_length: 500
    file: CUSTDAT.dat
    key_length: 9
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


def _drive_to_account_view(tmp_path: Path, bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    acctview_path = app / "cbl" / "COACTVWC.cbl"
    assert acctview_path.is_file(), f"COACTVWC not found: {acctview_path}"

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
    start_queue = StartQueue()
    spec = build_cics_spec(
        start_queue=start_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    acctview = compile_cics_program(acctview_path.read_bytes(), parser, spec)

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COACTVWC": acctview}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CAVW": "COACTVWC"}
    region = CicsRegion(
        program_cache,
        transid_to_program,
        screen_q,
        input_q,
        context_holder=context_holder,
        start_queue=start_queue,
        result_holder=result_holder,
        max_steps=2_000_000,
        min_commarea_len=2000,
    )

    r1 = region.start(
        "CC00",
        commarea=b"\x00" * 100,
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"USERID": _USER_ID, "PASSWD": _USER_PWD}
        ),
    )
    assert r1.kind == DispatchKind.XCTL and (r1.program or "").strip() == "COMEN01C"

    drain(screen_q)
    r2 = region.step()
    assert r2.kind == DispatchKind.RETURN_TRANSID

    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "01"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COACTVWC"
    ), f"menu option '01' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COACTVWC"

    return region, screen_q, engine


# The balance/limit render through WS-CURR-BAL/-credit edit pictures
# (+ZZZ,ZZZ,ZZZ.99 — sign, Z suppression, comma insertion).
_BAL_EDITED = "+      1,000.00"
_LIM_EDITED = "+      5,000.00"


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_account_view_detail(tmp_path, bridge_jar):
    """Turn 5: entering an account id joins CXACAIX -> ACCTDAT -> CUSTDAT and
    renders CACTVWA with the account (status / edited balance / edited limit)
    and the customer (id / first+middle+last name / DOB)."""
    region, screen_q, _ = _drive_to_account_view(tmp_path, bridge_jar)

    # Turn 4: first display (prompt).
    drain(screen_q)
    r4 = region.step()
    drain(screen_q)
    assert r4.kind == DispatchKind.RETURN_TRANSID

    # Turn 5: enter the account id -> multi-file read -> detail.
    r5 = region.step(
        input_event=InputEvent(eibaid=_DFHENTER, fields={"ACCTSID": _ACCT_ID})
    )
    screens = drain(screen_q)
    assert any(
        s.get("map") == "CACTVWA" for s in screens
    ), f"COACTVWC did not render CACTVWA; maps={[s.get('map') for s in screens]}"
    fields = [s for s in screens if s.get("map") == "CACTVWA"][-1]["fields"]

    def got(key: str) -> str:
        return (fields.get(key) or "").strip()

    # Account fields (from ACCTDAT).
    assert got("ACSTTUS") == _STATUS, f"ACSTTUS: got {fields.get('ACSTTUS')!r}"
    assert got("ACURBAL") == _BAL_EDITED, f"ACURBAL: got {fields.get('ACURBAL')!r}"
    assert got("ACRDLIM") == _LIM_EDITED, f"ACRDLIM: got {fields.get('ACRDLIM')!r}"
    # Customer fields (from CUSTDAT, reached via the CXACAIX xref).
    assert got("ACSTNUM") == _CUST_ID, f"ACSTNUM: got {fields.get('ACSTNUM')!r}"
    assert got("ACSFNAM") == _FNAME, f"ACSFNAM: got {fields.get('ACSFNAM')!r}"
    assert got("ACSMNAM") == _MNAME, f"ACSMNAM: got {fields.get('ACSMNAM')!r}"
    assert got("ACSLNAM") == _LNAME, f"ACSLNAM: got {fields.get('ACSLNAM')!r}"
    assert got("ACSTDOB") == _DOB, f"ACSTDOB: got {fields.get('ACSTDOB')!r}"

    assert r5.kind == DispatchKind.RETURN_TRANSID
    assert (r5.transid or "").strip() == "CAVW"
