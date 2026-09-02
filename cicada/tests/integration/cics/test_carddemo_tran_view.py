"""MANUAL regression test: COTRN01C transaction-view-detail flow (menu option 07).

Tests a VSAM point-READ by key — distinct from COTRN00C's STARTBR/READNEXT
browse. The user types a transaction ID; COTRN01C reads that single TRANSACT
record and renders the COTRN1A detail screen.

  Turn 1-3: sign-on -> menu -> ENTER option '07' -> XCTL COTRN01C.
  Turn 4 (COTRN01C, first display): XCTL'd in -> CDEMO-PGM-REENTER false ->
      no pre-selected tran -> SEND MAP COTRN1A (empty prompt) -> RETURN TRANSID CT01.
  Turn 5 (COTRN01C, ENTER): RECEIVE MAP -> PROCESS-ENTER-KEY ->
      MOVE TRNIDIN TO TRAN-ID -> READ TRANSACT -> populate detail fields ->
      SEND MAP COTRN1A -> RETURN TRANSID CT01.

VSAM engine seeded via FctConfig.from_yaml + seed_vsam (the same pipeline
as test_carddemo_tran_list).
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

_TRAN_RECLN = 350
_USRSEC_RECLN = 80

_DFHENTER = "\x7d"

# The transaction we seed and then view by ID.
_VIEW_TRAN_ID = "0000000000000007"

# Recognisable detail-field values (whole-dollar amount avoids the field->field
# fractional-MOVE loss tracked in red-dragon-d3ww).
_TRAN_TYPE_CD = "01"
_TRAN_CAT_CD = "0005"
_TRAN_SOURCE = "POS"
_TRAN_DESC = "PURCHASE AT ACME STORE"
_TRAN_AMT_EDITED = "+00012345.00"  # WS-TRAN-AMT PIC +99999999.99 from 12345.00
_TRAN_MERCHANT_ID = "000000042"
_TRAN_MERCHANT_NAME = "ACME CORP"
_TRAN_MERCHANT_CITY = "SPRINGFIELD"
_TRAN_MERCHANT_ZIP = "12345"
_TRAN_CARD_NUM = "4111111111111111"


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


def _num(s: str, n: int) -> bytes:
    return s.zfill(n)[:n].encode("cp037")


def _view_tran_record() -> bytes:
    """CVTRA05Y TRAN-RECORD (350 bytes) with recognisable detail values."""
    rec = (
        _ebcdic(_VIEW_TRAN_ID, 16)  # TRAN-ID X(16) @0 — primary key
        + _ebcdic(_TRAN_TYPE_CD, 2)  # TRAN-TYPE-CD X(2) @16
        + _num(_TRAN_CAT_CD, 4)  # TRAN-CAT-CD 9(4) @18
        + _ebcdic(_TRAN_SOURCE, 10)  # TRAN-SOURCE X(10) @22
        + _ebcdic(_TRAN_DESC, 100)  # TRAN-DESC X(100) @32
        + _num("00001234500", 11)  # TRAN-AMT S9(9)V99 @132 -> 12345.00
        + _num(_TRAN_MERCHANT_ID, 9)  # TRAN-MERCHANT-ID 9(9) @143
        + _ebcdic(_TRAN_MERCHANT_NAME, 50)  # TRAN-MERCHANT-NAME X(50) @152
        + _ebcdic(_TRAN_MERCHANT_CITY, 50)  # TRAN-MERCHANT-CITY X(50) @202
        + _ebcdic(_TRAN_MERCHANT_ZIP, 10)  # TRAN-MERCHANT-ZIP X(10) @252
        + _ebcdic(_TRAN_CARD_NUM, 16)  # TRAN-CARD-NUM X(16) @262
        + _ebcdic("2024-01-01-12.00.00.000000", 26)  # TRAN-ORIG-TS X(26) @278
        + _ebcdic("2024-01-02-12.00.00.000000", 26)  # TRAN-PROC-TS X(26) @304
        + _ebcdic("", 20)  # FILLER X(20) @330
    )
    return rec.ljust(_TRAN_RECLN, b"\x40")[:_TRAN_RECLN]


def _usrsec_record() -> bytes:
    """CSUSR01Y record (80 bytes): USER0001 / PASS0001, regular-user type 'U'."""
    rec = (
        _ebcdic("USER0001", 8)
        + _ebcdic("First", 20)
        + _ebcdic("Last", 20)
        + _ebcdic("PASS0001", 8)
        + _ebcdic("U", 1)
        + _ebcdic("", 23)
    )
    return rec.ljust(_USRSEC_RECLN, b"\x40")[:_USRSEC_RECLN]


def _write_seed_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    write_flat_file(data_dir / "USRSEC.dat", [_usrsec_record()], _USRSEC_RECLN)
    write_flat_file(data_dir / "TRANSACT.dat", [_view_tran_record()], _TRAN_RECLN)


_FCT_YAML = """\
datasets:
  USRSEC:
    record_length: 80
    file: USRSEC.dat
    key_length: 8
  TRANSACT:
    record_length: 350
    file: TRANSACT.dat
    key_length: 16
"""


def _tran_view_engine(tmp_path: Path) -> VsamEngine:
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


def _drive_to_tran_view(tmp_path: Path, bridge_jar):
    """Compile COSGN00C + COMEN01C + COTRN01C and drive turns 1-3.

    Returns (region, screen_q) positioned just after the menu XCTL into
    COTRN01C — the caller's next step() runs COTRN01C's first display (turn 4).
    """
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    tranview_path = app / "cbl" / "COTRN01C.cbl"
    assert tranview_path.is_file(), f"COTRN01C not found: {tranview_path}"

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
    start_queue = StartQueue()
    spec = build_cics_spec(
        start_queue=start_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=_tran_view_engine(tmp_path),
        screen_queue=screen_q,
        input_queue=input_q,
    )

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    tranview = compile_cics_program(tranview_path.read_bytes(), parser, spec)

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COTRN01C": tranview}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CT01": "COTRN01C"}
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
    )

    # Turn 1: sign-on -> XCTL COMEN01C
    r1 = region.start(
        "CC00",
        commarea=b"\x00" * 100,
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"USERID": "USER0001", "PASSWD": "PASS0001"}
        ),
    )
    assert r1.kind == DispatchKind.XCTL and (r1.program or "").strip() == "COMEN01C"

    # Turn 2: menu first display
    drain(screen_q)
    r2 = region.step()
    assert r2.kind == DispatchKind.RETURN_TRANSID

    # Turn 3: ENTER option '07' -> XCTL COTRN01C
    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "07"}))
    assert (
        r3.kind == DispatchKind.XCTL
    ), f"menu option '07' did not XCTL (kind={r3.kind}); expected COTRN01C"
    assert (
        r3.program or ""
    ).strip() == "COTRN01C", (
        f"menu option '07' XCTL'd to {r3.program!r}, expected COTRN01C"
    )

    return region, screen_q


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_transaction_view_detail(tmp_path, bridge_jar):
    """Turn 4 prompts; turn 5 reads the seeded transaction by ID and renders
    COTRN1A with the detail fields populated (incl. the edited amount)."""
    region, screen_q = _drive_to_tran_view(tmp_path, bridge_jar)

    # Turn 4: COTRN01C first display (XCTL'd in -> empty prompt screen)
    drain(screen_q)
    r4 = region.step()
    screens4 = drain(screen_q)
    assert any(
        s.get("map") == "COTRN1A" for s in screens4
    ), f"COTRN01C did not render COTRN1A; maps={[s.get('map') for s in screens4]}"
    assert r4.kind == DispatchKind.RETURN_TRANSID
    assert (r4.transid or "").strip() == "CT01"

    # Turn 5: ENTER the transaction ID -> READ TRANSACT -> detail fields
    r5 = region.step(
        input_event=InputEvent(eibaid=_DFHENTER, fields={"TRNIDIN": _VIEW_TRAN_ID})
    )
    screens5 = drain(screen_q)
    assert any(
        s.get("map") == "COTRN1A" for s in screens5
    ), f"COTRN01C did not re-render COTRN1A; maps={[s.get('map') for s in screens5]}"
    fields = next(s for s in screens5 if s.get("map") == "COTRN1A")["fields"]

    def got(key: str) -> str:
        return (fields.get(key) or "").strip()

    assert got("TRNID") == _VIEW_TRAN_ID, f"TRNID: got {fields.get('TRNID')!r}"
    assert got("CARDNUM") == _TRAN_CARD_NUM, f"CARDNUM: got {fields.get('CARDNUM')!r}"
    assert got("TTYPCD") == _TRAN_TYPE_CD, f"TTYPCD: got {fields.get('TTYPCD')!r}"
    assert got("TCATCD") == _TRAN_CAT_CD, f"TCATCD: got {fields.get('TCATCD')!r}"
    assert got("TRNSRC") == _TRAN_SOURCE, f"TRNSRC: got {fields.get('TRNSRC')!r}"
    assert got("TRNAMT") == _TRAN_AMT_EDITED, f"TRNAMT: got {fields.get('TRNAMT')!r}"
    assert got("TDESC") == _TRAN_DESC, f"TDESC: got {fields.get('TDESC')!r}"
    assert got("MID") == _TRAN_MERCHANT_ID, f"MID: got {fields.get('MID')!r}"
    assert got("MNAME") == _TRAN_MERCHANT_NAME, f"MNAME: got {fields.get('MNAME')!r}"
    assert got("MCITY") == _TRAN_MERCHANT_CITY, f"MCITY: got {fields.get('MCITY')!r}"
    assert got("MZIP") == _TRAN_MERCHANT_ZIP, f"MZIP: got {fields.get('MZIP')!r}"

    assert r5.kind == DispatchKind.RETURN_TRANSID
    assert (r5.transid or "").strip() == "CT01"
