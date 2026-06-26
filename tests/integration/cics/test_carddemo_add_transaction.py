"""MANUAL regression test: COTRN02C add-transaction flow (menu option 08).

UI-driven TRANSACT WRITE with cross-file validation. The user enters an
account/card plus the transaction fields and confirms; COTRN02C validates the
account+card against the xref (CXACAIX by account, CCXREF by card), mints the
next transaction id (STARTBR/READPREV), and WRITEs a new TRANSACT record.

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '08' -> XCTL COTRN02C.
  Turn 4: first display (empty form).
  Turn 5: ENTER fields, CONFIRM blank -> validate -> 'Confirm to add' prompt.
  Turn 6: resend + CONFIRM='Y' -> WRITE TRANSACT (id = last+1).
"""

from __future__ import annotations

import os
import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.dispatcher import CicsRegion, InputEvent
from cics.le_stubs import le_service_stub_sources
from cics.preprocessor import apply_cics_prepass
from cics.strategy import CicsLoweringStrategy
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
_XREF_RECLN = 50
_TRAN_RECLN = 350

_DFHENTER = "\x7d"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

_ACCT_ID = "00000000001"
_CUST_ID = "000000001"
_CARD_NUM = "4111111111111111"
_LAST_TRAN_ID = "0000000000000010"
_NEW_TRAN_ID = "0000000000000011"

_TXN = {
    "ACTIDIN": _ACCT_ID,
    "CARDNIN": _CARD_NUM,
    "TTYPCD": "01",
    "TCATCD": "0001",
    "TRNSRC": "POS",
    "TDESC": "TEST TRANSACTION",
    "TRNAMT": "+00000100.00",
    "TORIGDT": "2024-01-01",
    "TPROCDT": "2024-01-01",
    "MID": "000000001",
    "MNAME": "TEST MERCHANT",
    "MCITY": "CHICAGO",
    "MZIP": "60601",
}


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


def _xref_record() -> bytes:
    """CVACT03Y (50 bytes): CARD-NUM X(16)@0, CUST-ID 9(9)@16, ACCT-ID 9(11)@25."""
    rec = (
        _ebcdic(_CARD_NUM, 16)
        + _num(_CUST_ID, 9)
        + _num(_ACCT_ID, 11)
        + _ebcdic("", 14)
    )
    return rec.ljust(_XREF_RECLN, b"\x40")[:_XREF_RECLN]


def _tran_record(tran_id: str) -> bytes:
    rec = _ebcdic(tran_id, 16) + _ebcdic("", _TRAN_RECLN - 16)
    return rec.ljust(_TRAN_RECLN, b"\x40")[:_TRAN_RECLN]


def _write_seed_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    write_flat_file(
        data_dir / "USRSEC.dat",
        [_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U")],
        _USRSEC_RECLN,
    )
    # Same xref record exposed under both keys: CCXREF by card (@0), CXACAIX by
    # account (@25).
    write_flat_file(data_dir / "CCXREF.dat", [_xref_record()], _XREF_RECLN)
    write_flat_file(data_dir / "CXACAIX.dat", [_xref_record()], _XREF_RECLN)
    write_flat_file(
        data_dir / "TRANSACT.dat", [_tran_record(_LAST_TRAN_ID)], _TRAN_RECLN
    )


_FCT_YAML = """\
datasets:
  USRSEC:
    record_length: 80
    file: USRSEC.dat
    key_length: 8
  CCXREF:
    record_length: 50
    file: CCXREF.dat
    key_length: 16
  CXACAIX:
    record_length: 50
    file: CXACAIX.dat
    key_length: 11
    key_offset: 25
  TRANSACT:
    record_length: 350
    file: TRANSACT.dat
    key_length: 16
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


def _drive_to_add_transaction(tmp_path: Path, bridge_jar):
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.cobol.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    addtran_path = app / "cbl" / "COTRN02C.cbl"
    assert addtran_path.is_file(), f"COTRN02C not found: {addtran_path}"

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
    strategy = CicsLoweringStrategy(
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )

    signon = compile_cics_program(
        apply_cics_prepass(signon_path.read_text()).encode(), parser, strategy
    )
    menu = compile_cics_program(
        apply_cics_prepass(menu_path.read_text()).encode(), parser, strategy
    )
    # COTRN02C CALLs 'CSUTLDTC' to validate the Orig/Proc dates; CSUTLDTC in turn
    # CALLs the LE service "CEEDAYS" (no COBOL source). Resolve CSUTLDTC from the
    # app's cbl dir and supply the CEEDAYS stub.
    addtran = compile_cics_program(
        apply_cics_prepass(addtran_path.read_text()).encode(),
        parser,
        strategy,
        program_source_dir=app / "cbl",
        extra_subprogram_sources=le_service_stub_sources(),
    )

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COTRN02C": addtran}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CT02": "COTRN02C"}
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
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "08"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COTRN02C"
    ), f"menu option '08' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COTRN02C"

    return region, screen_q, engine


def _last(screens, mapname):
    matches = [s for s in screens if s.get("map") == mapname]
    return matches[-1]["fields"] if matches else None


def _added_transaction(engine):
    """Read back the freshly-WRITTEN TRANSACT record (CVTRA05Y, by tran id)."""
    rec, _ = engine.read("TRANSACT", _NEW_TRAN_ID.encode("cp037"), 16)
    assert rec is not None, f"new transaction {_NEW_TRAN_ID} was not written"
    b = bytes(rec)
    return {
        "TRAN_ID": b[0:16].decode("cp037").strip(),
        "TYPE_CD": b[16:18].decode("cp037").strip(),
        "CAT_CD": b[18:22].decode("cp037").strip(),
        "SOURCE": b[22:32].decode("cp037").strip(),
        "DESC": b[32:132].decode("cp037").strip(),
        "MERCHANT_ID": b[143:152].decode("cp037").strip(),
        "MERCHANT_NAME": b[152:202].decode("cp037").strip(),
        "CARD_NUM": b[262:278].decode("cp037").strip(),
    }


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_add_transaction_writes(tmp_path, bridge_jar):
    """find/enter -> confirm prompt -> CONFIRM='Y' -> WRITE TRANSACT.

    The faithful two-turn flow: ENTER the transaction with CONFIRM blank yields a
    'Confirm to add this transaction' prompt; resending with CONFIRM='Y' mints the
    next id (last 0000000000000010 -> 0000000000000011) and WRITEs the record.
    The success message + reformatted amount are asserted on screen; the written
    record's key fields are cross-checked in the engine."""
    region, screen_q, engine = _drive_to_add_transaction(tmp_path, bridge_jar)
    # Pre-condition: the next id does not exist yet.
    assert engine.read("TRANSACT", _NEW_TRAN_ID.encode("cp037"), 16)[0] is None

    # Turn 4: first display (empty form).
    drain(screen_q)
    region.step()
    drain(screen_q)

    # Turn 5: enter every field, CONFIRM blank -> validation passes, confirm prompt.
    region.step(input_event=InputEvent(eibaid=_DFHENTER, fields=dict(_TXN)))
    f5 = _last(drain(screen_q), "COTRN2A")
    assert f5, "no COTRN2A screen after entering the transaction"
    msg5 = (f5.get("ERRMSG") or "").lower()
    assert "confirm to add" in msg5, f"expected confirm prompt; got {msg5!r}"
    # The amount was normalised to the +99999999.99 display picture.
    assert (f5.get("TRNAMT") or "").strip() == "+00000100.00"

    # Turn 6: resend the form with CONFIRM='Y' -> ADD-TRANSACTION -> WRITE.
    confirm = dict(_TXN)
    confirm["CONFIRM"] = "Y"
    r6 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields=confirm))
    f6 = _last(drain(screen_q), "COTRN2A")
    assert f6, "no COTRN2A screen after confirming"
    msg6 = (f6.get("ERRMSG") or "").lower()
    assert "added successfully" in msg6 and _NEW_TRAN_ID in (
        f6.get("ERRMSG") or ""
    ), f"transaction not added; ERRMSG={f6.get('ERRMSG')!r}"
    assert r6.kind == DispatchKind.RETURN_TRANSID
    assert (r6.transid or "").strip() == "CT02"

    # Internal cross-check: the WRITE persisted the entered fields under the new id.
    added = _added_transaction(engine)
    assert added["TRAN_ID"] == _NEW_TRAN_ID
    assert added["CARD_NUM"] == _CARD_NUM
    assert added["TYPE_CD"] == _TXN["TTYPCD"]
    assert added["CAT_CD"] == _TXN["TCATCD"]  # PIC 9(4), stored as '0001'
    assert added["SOURCE"] == _TXN["TRNSRC"]
    assert added["DESC"] == _TXN["TDESC"]
    assert added["MERCHANT_NAME"] == _TXN["MNAME"]
