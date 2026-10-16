"""MANUAL regression test: COCRDSLC credit-card-detail flow (menu option 04).

A CARDDAT point-READ by card number (distinct from COCRDLIC's browse). The user
enters an account + card number; COCRDSLC reads that card and renders the
CCRDSLA detail screen (embossed name / status / expiry).

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '04' -> XCTL COCRDSLC.
  Turn 4 (COCRDSLC, first display): prompt -> RETURN TRANSID CCDL.
  Turn 5 (COCRDSLC, ENTER acct+card): READ CARDDAT -> detail fields.
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

_USRSEC_RECLN = 80
_CARD_RECLN = 150

_DFHENTER = "\x7d"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

_ACCT_ID = "00000000001"
_CARD_NUM = "4111111111111111"
_EMBOSSED = "JOHN Q PUBLIC"
_EXP_YEAR = "2099"
_EXP_MONTH = "12"
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


def _card_record() -> bytes:
    """CVACT02Y card record (150 bytes). Expiry is stored YYYY-MM-DD; COCRDSLC
    redefines it as YEAR(4) + sep + MONTH(2) + sep + DAY(2)."""
    rec = (
        _ebcdic(_CARD_NUM, 16)
        + _num(_ACCT_ID, 11)
        + _num("123", 3)
        + _ebcdic(_EMBOSSED, 50)
        + _ebcdic(f"{_EXP_YEAR}-{_EXP_MONTH}-31", 10)  # 2099-12-31
        + _ebcdic(_STATUS, 1)
        + _ebcdic("", 59)
    )
    return rec.ljust(_CARD_RECLN, b"\x40")[:_CARD_RECLN]


def _make_engine(tmp_path: Path) -> VsamEngine:
    clusters = (
        SeedCluster(
            "USRSEC",
            80,
            8,
            (_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U"),),
        ),
        SeedCluster("CARDDAT", 150, 16, (_card_record(),)),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _drive_to_card_view(tmp_path: Path, bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    cardview_path = app / "cbl" / "COCRDSLC.cbl"
    assert cardview_path.is_file(), f"COCRDSLC not found: {cardview_path}"

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
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        start_queue=start_queue,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )
    spec = build_cics_spec()

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    cardview = compile_cics_program(cardview_path.read_bytes(), parser, spec)

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COCRDSLC": cardview}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CCDL": "COCRDSLC"}
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
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "04"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COCRDSLC"
    ), f"menu option '04' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COCRDSLC"

    return region, screen_q, engine


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_card_view_detail(tmp_path, bridge_jar):
    """Turn 5: entering account + card number reads CARDDAT and renders the
    CCRDSLA detail (embossed name / status / expiry month+year)."""
    region, screen_q, _ = _drive_to_card_view(tmp_path, bridge_jar)

    # Turn 4: first display (prompt).
    drain(screen_q)
    r4 = region.step()
    drain(screen_q)
    assert r4.kind == DispatchKind.RETURN_TRANSID

    # Turn 5: enter the account + card -> READ CARDDAT -> detail fields.
    r5 = region.step(
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"ACCTSID": _ACCT_ID, "CARDSID": _CARD_NUM}
        )
    )
    screens = drain(screen_q)
    assert any(
        s.get("map") == "CCRDSLA" for s in screens
    ), f"COCRDSLC did not render CCRDSLA; maps={[s.get('map') for s in screens]}"
    fields = [s for s in screens if s.get("map") == "CCRDSLA"][-1]["fields"]

    def got(key: str) -> str:
        return (fields.get(key) or "").strip()

    assert got("CRDNAME") == _EMBOSSED, f"CRDNAME: got {fields.get('CRDNAME')!r}"
    assert got("CRDSTCD") == _STATUS, f"CRDSTCD: got {fields.get('CRDSTCD')!r}"
    assert got("EXPMON") == _EXP_MONTH, f"EXPMON: got {fields.get('EXPMON')!r}"
    assert got("EXPYEAR") == _EXP_YEAR, f"EXPYEAR: got {fields.get('EXPYEAR')!r}"
    # The account/card the user entered are echoed back.
    assert got("ACCTSID") == _ACCT_ID
    assert got("CARDSID") == _CARD_NUM

    assert r5.kind == DispatchKind.RETURN_TRANSID
    assert (r5.transid or "").strip() == "CCDL"
