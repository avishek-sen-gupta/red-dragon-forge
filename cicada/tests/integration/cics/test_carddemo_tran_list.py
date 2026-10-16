"""MANUAL regression test: COTRN00C transaction-list browse flow (menu option 06).

Tests VSAM STARTBR/READNEXT pagination — a fundamentally different code path from
the point-read flows in test_carddemo_signon_real.py:

  Turn 4 (COTRN00C, first display): XCTL'd in → CDEMO-PGM-REENTER=false →
      PROCESS-ENTER-KEY → STARTBR from LOW-VALUES → READNEXT × 10 records →
      SEND MAP COTRN0A → RETURN TRANSID CT00.
  Turn 5 (COTRN00C, PF8 page-forward): RECEIVE MAP → DFHPF8 branch →
      STARTBR from CDEMO-CT00-TRNID-LAST → skip-one READNEXT → read next
      page → SEND MAP COTRN0A → RETURN TRANSID CT00.

Files are clusters in a test system catalog under tmp_path.
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

_TRAN_RECLN = 350
_USRSEC_RECLN = 80

_DFHENTER = "\x7d"
_DFHPF8 = "\xf8"

# Seed 12 TRANSACT records: first page shows 10, second shows 2.
_NUM_TRAN_RECORDS = 12

# Expected formatted values derived from the seeded record fields.
# WS-TRAN-DATE: TRAN-ORIG-TS "2024-01-01-..." → MM/DD/YY via CSDAT01Y offsets.
_TRAN_DATE = "01/01/24"

# WS-TRAN-AMT is PIC +99999999.99 (numeric-edited). TRAN-AMT is seeded to zero,
# so the edited display value is a fixed '+' sign, eight zero digits, '.00'.
_TRAN_AMT = "+00000000.00"


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


def _num(s: str, n: int) -> bytes:
    return s.zfill(n)[:n].encode("cp037")


def _tran_id(n: int) -> str:
    return f"{n:016d}"


def _tran_record(n: int) -> bytes:
    """CVTRA05Y TRAN-RECORD (350 bytes): TRAN-ID X(16)@0, TRAN-DESC with
    recognisable sequence number, minimal valid values elsewhere."""
    rec = (
        _ebcdic(_tran_id(n), 16)  # TRAN-ID X(16) @0 — primary key
        + _ebcdic("  ", 2)  # TRAN-TYPE-CD X(2) @16
        + _num("0000", 4)  # TRAN-CAT-CD 9(4) @18
        + _ebcdic("", 10)  # TRAN-SOURCE X(10) @22
        + _ebcdic(f"TRAN{n:04d}", 100)  # TRAN-DESC X(100) @32
        + _num("00000000000", 11)  # TRAN-AMT S9(9)V99 @132 (11 display bytes)
        + _num("000000000", 9)  # TRAN-MERCHANT-ID 9(9) @143
        + _ebcdic("", 50)  # TRAN-MERCHANT-NAME X(50) @152
        + _ebcdic("", 50)  # TRAN-MERCHANT-CITY X(50) @202
        + _ebcdic("", 10)  # TRAN-MERCHANT-ZIP X(10) @252
        + _ebcdic("", 16)  # TRAN-CARD-NUM X(16) @262
        + _ebcdic("2024-01-01-00.00.00.000000", 26)  # TRAN-ORIG-TS X(26) @278
        + _ebcdic("2024-01-01-00.00.00.000000", 26)  # TRAN-PROC-TS X(26) @304
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


def _tran_list_engine(tmp_path: Path) -> VsamEngine:
    clusters = (
        SeedCluster("USRSEC", 80, 8, (_usrsec_record(),)),
        SeedCluster(
            "TRANSACT",
            350,
            16,
            tuple(_tran_record(n) for n in range(1, _NUM_TRAN_RECORDS + 1)),
        ),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _drive_to_tran_list(tmp_path: Path, bridge_jar):
    """Compile COSGN00C + COMEN01C + COTRN00C and drive turns 1-3.

    Turn 1: sign-on → XCTL COMEN01C.
    Turn 2: menu first display → RETURN_TRANSID CM00.
    Turn 3: ENTER option '06' → XCTL COTRN00C.

    Returns (region, screen_q) positioned just after the menu XCTL — the
    caller's next step() runs COTRN00C (turn 4).
    """
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    tranlist_path = app / "cbl" / "COTRN00C.cbl"
    assert tranlist_path.is_file(), f"COTRN00C not found: {tranlist_path}"

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
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        start_queue=start_queue,
        result_holder=result_holder,
        vsam_engine=_tran_list_engine(tmp_path),
        screen_queue=screen_q,
        input_queue=input_q,
    )
    spec = build_cics_spec()

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    tranlist = compile_cics_program(tranlist_path.read_bytes(), parser, spec)

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COTRN00C": tranlist}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CT00": "COTRN00C"}
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

    # Turn 1: sign-on → XCTL COMEN01C
    r1 = region.start(
        "CC00",
        commarea=b"\x00" * 100,
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"USERID": "USER0001", "PASSWD": "PASS0001"}
        ),
    )
    assert r1.kind == DispatchKind.XCTL and (r1.program or "").strip() == "COMEN01C"

    # Turn 2: menu first display (XCTL'd in → no fresh input)
    drain(screen_q)
    r2 = region.step()
    assert r2.kind == DispatchKind.RETURN_TRANSID

    # Turn 3: ENTER option '06' → XCTL COTRN00C
    drain(screen_q)
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "06"}))
    assert (
        r3.kind == DispatchKind.XCTL
    ), f"menu option '06' did not XCTL (kind={r3.kind}); expected COTRN00C"
    assert (
        r3.program or ""
    ).strip() == "COTRN00C", (
        f"menu option '06' XCTL'd to {r3.program!r}, expected COTRN00C"
    )

    return region, screen_q


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_transaction_list_first_page(tmp_path, bridge_jar):
    """Turn 4: XCTL'd into COTRN00C → first display renders COTRN0A with 10
    transaction rows via STARTBR/READNEXT browse from LOW-VALUES.

    Verifies TRNID01–TRNID10 are populated with the seeded IDs in order and
    the region parks pseudo-conversationally on CT00.
    """
    region, screen_q = _drive_to_tran_list(tmp_path, bridge_jar)

    # Turn 4: COTRN00C first display (XCTL'd in → no fresh input)
    drain(screen_q)
    r4 = region.step()
    screens = drain(screen_q)

    assert any(
        s.get("map") == "COTRN0A" for s in screens
    ), f"COTRN00C did not render COTRN0A; maps={[s.get('map') for s in screens]}"
    fields = next(s for s in screens if s.get("map") == "COTRN0A")["fields"]

    # All ten rows must be populated with the seeded values in ascending order.
    for slot, n in enumerate(range(1, 11), start=1):
        trnid_key = f"TRNID{slot:02d}"
        tdate_key = f"TDATE{slot:02d}"
        tdesc_key = f"TDESC{slot:02d}"
        tamt_key = f"TAMT{slot:03d}"

        assert (fields.get(trnid_key) or "").strip() == _tran_id(
            n
        ), f"{trnid_key}: expected {_tran_id(n)!r}, got {fields.get(trnid_key)!r}"
        assert (
            fields.get(tdate_key) or ""
        ).strip() == _TRAN_DATE, (
            f"{tdate_key}: expected {_TRAN_DATE!r}, got {fields.get(tdate_key)!r}"
        )
        assert (
            fields.get(tdesc_key) or ""
        ).strip() == f"TRAN{n:04d}", (
            f"{tdesc_key}: expected 'TRAN{n:04d}', got {fields.get(tdesc_key)!r}"
        )
        assert (
            fields.get(tamt_key) or ""
        ).strip() == _TRAN_AMT, (
            f"{tamt_key}: expected {_TRAN_AMT!r}, got {fields.get(tamt_key)!r}"
        )
    assert r4.kind == DispatchKind.RETURN_TRANSID
    assert (r4.transid or "").strip() == "CT00"


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_transaction_list_page_forward(tmp_path, bridge_jar):
    """Turn 5: PF8 (page-forward) → COTRN00C dispatches PROCESS-PF8-KEY, sets
    TRAN-ID = CDEMO-CT00-TRNID-LAST ('...0010'), and re-browses via STARTBR.

    PROCESS-PAGE-FORWARD guard: IF EIBAID NOT = DFHENTER AND DFHPF7 AND DFHPF3
    skips the first READNEXT for PF8 (non-ENTER, non-PF7, non-PF3), so the
    browse advances past record 10 and page 2 shows records 11, 12 in slots
    1 and 2.
    """
    region, screen_q = _drive_to_tran_list(tmp_path, bridge_jar)

    # Turn 4: first page (XCTL'd in → no fresh input) — consume to set
    # CDEMO-CT00-TRNID-LAST in the commarea before the PF8 turn.
    drain(screen_q)
    r4 = region.step()
    assert r4.kind == DispatchKind.RETURN_TRANSID

    # Turn 5: PF8 page-forward → PROCESS-PF8-KEY → PROCESS-PAGE-FORWARD
    drain(screen_q)
    r5 = region.step(input_event=InputEvent(eibaid=_DFHPF8, fields={}))
    screens = drain(screen_q)

    assert any(
        s.get("map") == "COTRN0A" for s in screens
    ), f"PF8 did not render COTRN0A; maps={[s.get('map') for s in screens]}"
    fields = next(s for s in screens if s.get("map") == "COTRN0A")["fields"]

    # PF8 skips the first READNEXT, so page 2 starts after record 10.
    # With 12 total records, slots 1-2 show records 11, 12.
    for slot, n in enumerate([11, 12], start=1):
        trnid_key = f"TRNID{slot:02d}"
        tdate_key = f"TDATE{slot:02d}"
        tdesc_key = f"TDESC{slot:02d}"
        tamt_key = f"TAMT{slot:03d}"

        assert (fields.get(trnid_key) or "").strip() == _tran_id(
            n
        ), f"{trnid_key} page 2: expected {_tran_id(n)!r}, got {fields.get(trnid_key)!r}"
        assert (
            fields.get(tdate_key) or ""
        ).strip() == _TRAN_DATE, f"{tdate_key} page 2: expected {_TRAN_DATE!r}, got {fields.get(tdate_key)!r}"
        assert (
            fields.get(tdesc_key) or ""
        ).strip() == f"TRAN{n:04d}", (
            f"{tdesc_key} page 2: expected 'TRAN{n:04d}', got {fields.get(tdesc_key)!r}"
        )
        assert (
            fields.get(tamt_key) or ""
        ).strip() == _TRAN_AMT, (
            f"{tamt_key} page 2: expected {_TRAN_AMT!r}, got {fields.get(tamt_key)!r}"
        )

    assert r5.kind == DispatchKind.RETURN_TRANSID
    assert (r5.transid or "").strip() == "CT00"
