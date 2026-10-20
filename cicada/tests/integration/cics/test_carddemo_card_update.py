"""MANUAL regression test: COCRDUPC credit-card-update flow (menu option 05).

CARDDAT READ + REWRITE with a confirm step. The user finds a card, edits its
fields, presses ENTER to validate (-> confirm prompt), then PF5 to commit the
REWRITE (guarded by an optimistic re-read).

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '05' -> XCTL COCRDUPC.
  Turn 4: first display (prompt for account + card).
  Turn 5: ENTER acct+card -> READ CARDDAT -> show current fields.
  Turn 6: ENTER edited fields -> validate -> 'confirm' prompt.
  Turn 7: PF5 -> 9200-WRITE-PROCESSING -> REWRITE CARDDAT.
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
_CARD_RECLN = 150

_DFHENTER = "\x7d"
_DFHPF5 = "\xf5"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

_ACCT_ID = "00000000001"
_CARD_NUM = "4111111111111111"
_EMBOSSED = "JOHN Q PUBLIC"
_NEW_EMBOSSED = "JANE Q PUBLIC"
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


def _card_record(embossed: str) -> bytes:
    rec = (
        _ebcdic(_CARD_NUM, 16)
        + _num(_ACCT_ID, 11)
        + _num("123", 3)
        + _ebcdic(embossed, 50)
        + _ebcdic(f"{_EXP_YEAR}-{_EXP_MONTH}-31", 10)
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
        SeedCluster("CARDDAT", 150, 16, (_card_record(_EMBOSSED),)),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _drive_to_card_update(tmp_path: Path, bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    cardupd_path = app / "cbl" / "COCRDUPC.cbl"
    assert cardupd_path.is_file(), f"COCRDUPC not found: {cardupd_path}"

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
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    cardupd = compile_cics_program(cardupd_path.read_bytes(), parser, spec)

    program_cache.update({"COSGN00C": signon, "COMEN01C": menu, "COCRDUPC": cardupd})
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CCUP": "COCRDUPC"}
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
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "05"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "COCRDUPC"
    ), f"menu option '05' XCTL'd to {r3.program!r} (kind={r3.kind}); expected COCRDUPC"

    return region, screen_q, engine


def _last(screens, mapname):
    matches = [s for s in screens if s.get("map") == mapname]
    return matches[-1]["fields"] if matches else None


_EDIT_FIELDS = {
    "ACCTSID": _ACCT_ID,
    "CARDSID": _CARD_NUM,
    "CRDNAME": _NEW_EMBOSSED,
    "CRDSTCD": _STATUS,
    "EXPMON": _EXP_MONTH,
    "EXPYEAR": _EXP_YEAR,
}


def _embossed_in_carddat(engine) -> str:
    rec_read = engine.read("CARDDAT", _CARD_NUM.encode("cp037"), 16)
    assert isinstance(rec_read, RecordRead), "card vanished"
    rec = rec_read.record
    return bytes(rec[30:80]).decode("cp037").strip()


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_card_update_rewrites(tmp_path, bridge_jar):
    """find -> edit -> validate (confirm prompt) -> PF5 commit. The edited
    embossed name is REWRITTEN to CARDDAT (verified on screen and in the engine),
    after the optimistic re-read confirms the record was unchanged."""
    region, screen_q, engine = _drive_to_card_update(tmp_path, bridge_jar)
    assert _embossed_in_carddat(engine) == _EMBOSSED  # pre-condition

    # Turn 4: first display (prompt).
    drain(screen_q)
    region.step()
    drain(screen_q)

    # Turn 5: find the card -> current details shown.
    region.step(
        input_event=InputEvent(
            eibaid=_DFHENTER, fields={"ACCTSID": _ACCT_ID, "CARDSID": _CARD_NUM}
        )
    )
    f5 = _last(drain(screen_q), "CCRDUPA")
    assert f5 and (f5.get("CRDNAME") or "").strip() == _EMBOSSED

    # Turn 6: edit the embossed name + ENTER -> changes validated, awaiting PF5.
    region.step(input_event=InputEvent(eibaid=_DFHENTER, fields=_EDIT_FIELDS))
    f6 = _last(drain(screen_q), "CCRDUPA")
    assert f6 and (f6.get("CRDNAME") or "").strip() == _NEW_EMBOSSED
    assert "press f5" in (f6.get("INFOMSG") or "").lower()

    # Turn 7: PF5 -> optimistic re-read + REWRITE.
    r7 = region.step(input_event=InputEvent(eibaid=_DFHPF5, fields=_EDIT_FIELDS))
    f7 = _last(drain(screen_q), "CCRDUPA")
    assert (
        f7 and "committed" in (f7.get("INFOMSG") or "").lower()
    ), f"update not committed; INFOMSG={f7.get('INFOMSG') if f7 else None!r}"
    assert r7.kind == DispatchKind.RETURN_TRANSID
    assert (r7.transid or "").strip() == "CCUP"

    # Internal cross-check: the REWRITE persisted the new embossed name.
    assert _embossed_in_carddat(engine) == _NEW_EMBOSSED
