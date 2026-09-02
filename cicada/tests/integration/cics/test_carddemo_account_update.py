"""MANUAL regression test: COACTUPC account-update flow (menu option 02).

ACCTDAT + CUSTDAT READ + REWRITE with extensive field validation and a confirm
step. Enter an account, edit a customer field, ENTER to validate every field
(dates, SSN, NANP phone, numerics), then PF5 to commit the REWRITE.

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '02' -> XCTL COACTUPC.
  Turn 4: first display (prompt for account).
  Turn 5: ENTER acct -> READ ACCTDAT + CUSTDAT -> show current details (CACTUPA).
  Turn 6: ENTER edited fields -> validate -> 'Press F5 to save'.
  Turn 7: PF5 -> optimistic re-read + REWRITE ACCTDAT/CUSTDAT.
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
        + _num("000000200000", 12)  # cash limit -> 2000.00
        + _ebcdic("2020-01-01", 10)  # open date
        + _ebcdic("2025-12-31", 10)  # expiry date
        + _ebcdic("2024-06-15", 10)  # reissue date
        + _num("0", 12)  # curr cyc credit
        + _num("0", 12)  # curr cyc debit
        + _ebcdic("", 10)  # addr zip
        + _ebcdic("01", 10)  # group id
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
        + _ebcdic("(312)123-4567", 15)  # phone-1: (AAA)PPP-LLLL, valid NANP area
        + _ebcdic("(415)987-6543", 15)  # phone-2
        + _num("123456789", 9)  # SSN
        + _ebcdic("DL12345", 20)  # govt id
        + _ebcdic(_DOB, 10)  # DOB
        + _num("1234567890", 10)  # eft account id (numeric)
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


def _drive_to_account_update(tmp_path: Path, bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    acctview_path = app / "cbl" / "COACTUPC.cbl"
    assert acctview_path.is_file(), f"COACTUPC not found: {acctview_path}"

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
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    acctview = compile_cics_program(acctview_path.read_bytes(), parser, spec)

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COACTUPC": acctview}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CAUP": "COACTUPC"}
    region = CicsRegion(
        program_cache,
        transid_to_program,
        screen_q,
        input_q,
        context_holder=context_holder,
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
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "02"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COACTUPC"
    ), f"menu option '02' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COACTUPC"

    return region, screen_q, engine


_DFHPF5 = "\xf5"
_NEW_FNAME = "JANE"


def _last(screens, mapname):
    matches = [s for s in screens if s.get("map") == mapname]
    return matches[-1]["fields"] if matches else None


def _cust_first_name(engine) -> str:
    rec, _ = engine.read("CUSTDAT", _CUST_ID.encode("cp037"), 9)
    assert rec is not None, "customer vanished"
    return bytes(rec[9:34]).decode("cp037").strip()


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_account_update_rewrites(tmp_path, bridge_jar):
    """find an account -> edit the customer first name -> validate (confirm
    prompt) -> PF5 commit. COACTUPC reads ACCTDAT + CUSTDAT, validates every
    field, then REWRITEs; the new name is verified on screen and in the engine."""
    region, screen_q, engine = _drive_to_account_update(tmp_path, bridge_jar)
    assert _cust_first_name(engine) == _FNAME  # pre-condition

    # Turn 4: first display.
    drain(screen_q)
    region.step()
    drain(screen_q)

    # Turn 5: find the account -> current account + customer details shown.
    region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"ACCTSID": _ACCT_ID}))
    find = _last(drain(screen_q), "CACTUPA")
    assert find and (find.get("ACSFNAM") or "").strip() == _FNAME

    # Re-send every displayed field (the terminal echoes the whole map), changing
    # only the customer first name.
    edit = {k: (v or "").strip() for k, v in find.items()}
    edit["ACCTSID"] = _ACCT_ID
    edit["ACSFNAM"] = _NEW_FNAME

    # Turn 6: ENTER -> all fields validated -> awaiting PF5.
    region.step(input_event=InputEvent(eibaid=_DFHENTER, fields=edit))
    f6 = _last(drain(screen_q), "CACTUPA")
    assert f6 and (f6.get("ACSFNAM") or "").strip() == _NEW_FNAME
    assert "press f5" in (f6.get("INFOMSG") or "").lower(), (
        f"changes not validated; INFOMSG={f6.get('INFOMSG') if f6 else None!r} "
        f"ERRMSG={f6.get('ERRMSG') if f6 else None!r}"
    )

    # Turn 7: PF5 -> optimistic re-read + REWRITE of ACCTDAT/CUSTDAT.
    r7 = region.step(input_event=InputEvent(eibaid=_DFHPF5, fields=edit))
    f7 = _last(drain(screen_q), "CACTUPA")
    assert (
        f7 and "committed" in (f7.get("INFOMSG") or "").lower()
    ), f"update not committed; INFOMSG={f7.get('INFOMSG') if f7 else None!r}"
    assert r7.kind == DispatchKind.RETURN_TRANSID
    assert (r7.transid or "").strip() == "CAUP"

    # Internal cross-check: the REWRITE persisted the new first name.
    assert _cust_first_name(engine) == _NEW_FNAME
