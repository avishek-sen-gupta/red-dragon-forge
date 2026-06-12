"""MANUAL regression test: COBIL00C bill-payment flow (menu option 10).

Increment 1 of the bill-pay flow (cicada-a7m): the DISPLAY path. A regular user
signs on, navigates to COBIL00C, enters an account id, and the program reads
ACCTDAT and shows the current balance (edited) with a confirm prompt.

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '10' -> XCTL COBIL00C.
  Turn 4 (COBIL00C, first display): empty prompt -> RETURN TRANSID CB00.
  Turn 5 (COBIL00C, ENTER acct id, no confirm): READ ACCTDAT -> MOVE
      ACCT-CURR-BAL -> WS-CURR-BAL (PIC +9999999999.99) -> CURBAL ->
      'Confirm to make a bill payment' -> RETURN TRANSID CB00.

The pay path (CONFIRM='Y' -> REWRITE balance + WRITE payment transaction) is a
separate increment.
"""

from __future__ import annotations

import os
import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.dispatcher import CicsRegion, InputEvent
from cics.preprocessor import apply_cics_prepass
from cics.strategy import CicsLoweringStrategy
from cics.types import DispatchKind
from cics.vsam.backend import InMemoryBackend
from cics.vsam.engine import VsamEngine
from cics.vsam.fct import FctConfig
from cics.vsam.format import write_flat_file
from cics.vsam.seed import load_vsam_seed
from interpreter.cobol.features import CobolFeature
from tests.covers import covers
from tests.integration.cics.bms_tools_helpers import HLASM_EXPORT_BIN
from tests.integration.cics.channel_drain import drain
from tests.integration.cobol_helpers import JAR_PATH

_CARDDEMO_HOME = os.environ.get("CARDDEMO_HOME")

pytestmark = pytest.mark.carddemo_e2e

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_USRSEC_RECLN = 80
_ACCT_RECLN = 300

_DFHENTER = "\x7d"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

_ACCT_ID = "00000000001"
# Whole-dollar balance avoids the field->field fractional-MOVE loss (red-dragon-d3ww).
_BALANCE_SCALED = "000000100000"  # ACCT-CURR-BAL S9(10)V99 -> 1000.00
_BALANCE_EDITED = "+0000001000.00"  # WS-CURR-BAL PIC +9999999999.99


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


def _acct_record(acct_id: str, balance_scaled: str) -> bytes:
    """CVACT01Y account record (300 bytes): ID 9(11)@0, STATUS X(1)@11,
    CURR-BAL S9(10)V99@12, then limits/dates/cycles/zip/group/filler."""
    rec = (
        _num(acct_id, 11)  # ACCT-ID 9(11)
        + _ebcdic("Y", 1)  # ACCT-ACTIVE-STATUS X(1)
        + _num(balance_scaled, 12)  # ACCT-CURR-BAL S9(10)V99
        + _num("0", 12)  # ACCT-CREDIT-LIMIT
        + _num("0", 12)  # ACCT-CASH-CREDIT-LIMIT
        + _ebcdic("", 10)  # ACCT-OPEN-DATE
        + _ebcdic("", 10)  # ACCT-EXPIRAION-DATE
        + _ebcdic("", 10)  # ACCT-REISSUE-DATE
        + _num("0", 12)  # ACCT-CURR-CYC-CREDIT
        + _num("0", 12)  # ACCT-CURR-CYC-DEBIT
        + _ebcdic("", 10)  # ACCT-ADDR-ZIP
        + _ebcdic("", 10)  # ACCT-GROUP-ID
        + _ebcdic("", 178)  # FILLER
    )
    return rec.ljust(_ACCT_RECLN, b"\x40")[:_ACCT_RECLN]


def _write_seed_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    write_flat_file(
        data_dir / "USRSEC.dat",
        [_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U")],
        _USRSEC_RECLN,
    )
    write_flat_file(
        data_dir / "ACCTDAT.dat",
        [_acct_record(_ACCT_ID, _BALANCE_SCALED)],
        _ACCT_RECLN,
    )


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
"""


def _make_engine(tmp_path: Path) -> VsamEngine:
    data_dir = tmp_path / "data"
    fct_path = tmp_path / "fct.yaml"
    _write_seed_files(data_dir)
    fct_path.write_text(_FCT_YAML)

    seed = load_vsam_seed(fct_path, data_dir)
    fct = FctConfig.from_yaml(fct_path)
    engine = VsamEngine(fct, backend=InMemoryBackend(seed=seed))
    engine.load_all()
    return engine


def _drive_to_bill_pay(tmp_path: Path):
    """Compile COSGN00C + COMEN01C + COBIL00C and drive turns 1-3.

    Returns (region, screen_q, engine) positioned just after the menu XCTL into
    COBIL00C — the caller's next step() runs COBIL00C's first display (turn 4).
    """
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.cobol.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    billpay_path = app / "cbl" / "COBIL00C.cbl"
    assert billpay_path.is_file(), f"COBIL00C not found: {billpay_path}"

    sym_dir = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=app / "bms",
        out_dir=sym_dir,
        hlasm_export_bin=HLASM_EXPORT_BIN,
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        JAR_PATH,
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
    billpay = compile_cics_program(
        apply_cics_prepass(billpay_path.read_text()).encode(), parser, strategy
    )

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COBIL00C": billpay}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CB00": "COBIL00C"}
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

    # Turn 1: sign-on -> XCTL COMEN01C
    r1 = region.start(
        "CC00",
        commarea=b"\x00" * 100,
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"USERID": _USER_ID, "PASSWD": _USER_PWD}
        ),
    )
    assert r1.kind == DispatchKind.XCTL and (r1.program or "").strip() == "COMEN01C"

    # Turn 2: menu first display
    drain(screen_q)
    r2 = region.step()
    assert r2.kind == DispatchKind.RETURN_TRANSID

    # Turn 3: ENTER option '10' -> XCTL COBIL00C
    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "10"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COBIL00C"
    ), f"menu option '10' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COBIL00C"

    return region, screen_q, engine


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_bill_pay_shows_balance(tmp_path):
    """Turn 5: entering the account id reads ACCTDAT and renders the edited
    current balance plus the confirm prompt."""
    region, screen_q, _ = _drive_to_bill_pay(tmp_path)

    # Turn 4: first display (empty prompt)
    drain(screen_q)
    r4 = region.step()
    drain(screen_q)
    assert r4.kind == DispatchKind.RETURN_TRANSID

    # Turn 5: ENTER the account id, leaving CONFIRM untouched (as a real terminal
    # would for an unmodified field) -> CONFIRMI stays LOW-VALUES -> EVALUATE hits
    # the LOW-VALUES branch -> READ ACCTDAT -> show balance + confirm prompt.
    r5 = region.step(
        input_event=InputEvent(eibaid=_DFHENTER, fields={"ACTIDIN": _ACCT_ID})
    )
    screens = drain(screen_q)
    assert any(
        s.get("map") == "COBIL0A" for s in screens
    ), f"COBIL00C did not render COBIL0A; maps={[s.get('map') for s in screens]}"
    fields = [s for s in screens if s.get("map") == "COBIL0A"][-1]["fields"]

    assert (
        fields.get("CURBAL") or ""
    ).strip() == _BALANCE_EDITED, (
        f"CURBAL: expected {_BALANCE_EDITED!r}, got {fields.get('CURBAL')!r}"
    )
    assert (
        "confirm to make a bill payment" in (fields.get("ERRMSG") or "").lower()
    ), f"confirm prompt not shown; ERRMSG={fields.get('ERRMSG')!r}"

    assert r5.kind == DispatchKind.RETURN_TRANSID
    assert (r5.transid or "").strip() == "CB00"
