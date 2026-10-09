"""MANUAL regression test: COCRDLIC credit-card-list flow (menu option 03).

First use of the CARDDAT (card master) file. COCRDLIC browses CARDDAT via
STARTBR/READNEXT and lists cards (account no / card no / status) per page.

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '03' -> XCTL COCRDLIC.
  Turn 4 (COCRDLIC, first display): browse CARDDAT -> SEND MAP CCRDLIA.

VSAM engine seeded via FctConfig.from_yaml + seed_vsam.
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
_CARD_RECLN = 150

_DFHENTER = "\x7d"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

_ACCT_A = "00000000001"
_ACCT_B = "00000000002"

# (card_num, acct_id, status) seeded into CARDDAT, in ascending card-number key
# order.
_CARDS = [
    ("4111111111111111", _ACCT_A, "Y"),
    ("4111111111111112", _ACCT_A, "Y"),
    ("5500000000000001", _ACCT_B, "N"),
]


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


def _card_record(card_num: str, acct_id: str, status: str) -> bytes:
    """CVACT02Y card record (150 bytes): CARD-NUM X(16)@0 (key), ACCT-ID 9(11)@16,
    CVV 9(3)@27, EMBOSSED-NAME X(50)@30, EXP X(10)@80, STATUS X(1)@90, FILLER."""
    rec = (
        _ebcdic(card_num, 16)
        + _num(acct_id, 11)
        + _num("123", 3)
        + _ebcdic("CARD HOLDER", 50)
        + _ebcdic("2099-12-31", 10)
        + _ebcdic(status, 1)
        + _ebcdic("", 59)
    )
    return rec.ljust(_CARD_RECLN, b"\x40")[:_CARD_RECLN]


def _write_seed_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    write_flat_file(
        data_dir / "USRSEC.dat",
        [_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U")],
        _USRSEC_RECLN,
    )
    write_flat_file(
        data_dir / "CARDDAT.dat",
        [_card_record(c, a, s) for (c, a, s) in _CARDS],
        _CARD_RECLN,
    )


_FCT_YAML = """\
datasets:
  USRSEC:
    record_length: 80
    file: USRSEC.dat
    key_length: 8
  CARDDAT:
    record_length: 150
    file: CARDDAT.dat
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


def _drive_to_card_list(tmp_path: Path, bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    cardlist_path = app / "cbl" / "COCRDLIC.cbl"
    assert cardlist_path.is_file(), f"COCRDLIC not found: {cardlist_path}"

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
        transid_to_program={},
        program_cache={},
        start_queue=start_queue,
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    cardlist = compile_cics_program(cardlist_path.read_bytes(), parser, spec)

    program_cache = {"COSGN00C": signon, "COMEN01C": menu, "COCRDLIC": cardlist}
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CCLI": "COCRDLIC"}
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
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "03"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COCRDLIC"
    ), f"menu option '03' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COCRDLIC"

    return region, screen_q, engine


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_card_list_first_page(tmp_path, bridge_jar):
    """Turn 4: COCRDLIC browses CARDDAT and renders CCRDLIA with one row per
    seeded card (account no / card no / status) in ascending card-number order;
    unused rows stay blank and the 'no more records' notice is shown."""
    region, screen_q, _ = _drive_to_card_list(tmp_path, bridge_jar)

    drain(screen_q)
    r4 = region.step()
    screens = drain(screen_q)

    assert any(
        s.get("map") == "CCRDLIA" for s in screens
    ), f"COCRDLIC did not render CCRDLIA; maps={[s.get('map') for s in screens]}"
    fields = [s for s in screens if s.get("map") == "CCRDLIA"][-1]["fields"]

    # The three seeded cards fill rows 1-3, in card-number key order.
    for slot, (card_num, acct_id, status) in enumerate(_CARDS, start=1):
        acctno = (fields.get(f"ACCTNO{slot}") or "").strip()
        crdnum = (fields.get(f"CRDNUM{slot}") or "").strip()
        crdsts = (fields.get(f"CRDSTS{slot}") or "").strip()
        assert acctno == acct_id, f"ACCTNO{slot}: expected {acct_id!r}, got {acctno!r}"
        assert (
            crdnum == card_num
        ), f"CRDNUM{slot}: expected {card_num!r}, got {crdnum!r}"
        assert crdsts == status, f"CRDSTS{slot}: expected {status!r}, got {crdsts!r}"

    # The remaining rows on the 7-row page are blank (low-values or spaces).
    for slot in range(len(_CARDS) + 1, 8):
        assert not (fields.get(f"CRDNUM{slot}") or "").strip(
            " \x00"
        ), f"CRDNUM{slot} should be blank, got {fields.get(f'CRDNUM{slot}')!r}"

    assert "no more records" in (fields.get("ERRMSG") or "").lower()
    assert r4.kind == DispatchKind.RETURN_TRANSID
    assert (r4.transid or "").strip() == "CCLI"
