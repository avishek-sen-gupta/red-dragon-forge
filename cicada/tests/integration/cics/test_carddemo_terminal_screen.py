from __future__ import annotations

import os
import queue
from collections.abc import Mapping
from pathlib import Path

import pytest

from cics.bms.catalog import load_catalog
from cics.bms.generate import generate_symbolic_copybooks
from cics.bootstrap import compile_cics_program
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.dispatcher import CicsRegion, InputEvent
from cics.interval import StartQueue
from cics.screen.cursor import Cursor
from cics.screen.driver import AwaitingInput, PseudoConversationalDriver
from cics.screen.terminal_screen import TerminalScreen, address
from tests.covers import NotLanguageFeature, covers
from tests.integration.cics.bms_tools_helpers import HLASM_EXPORT_BIN
from tests.integration.cics.test_carddemo_signon_real import _usrsec_engine
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

pytestmark = pytest.mark.carddemo_e2e

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"
_TRANSACTIONS = {"CC00": "COSGN00C", "CM00": "COMEN01C"}
_MENU_TRANSACTIONS = {**_TRANSACTIONS, "CAUP": "COACTUPC", "CAVW": "COACTVWC"}
_DFHPF3 = "\xf3"


def _driver(
    tmp_path: Path,
    jar: str,
    transactions: Mapping[str, str] = _TRANSACTIONS,
    min_commarea_len: int = 400,
):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(os.environ["CARDDEMO_HOME"])
    sym = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=app / "bms", out_dir=sym, hlasm_export_bin=HLASM_EXPORT_BIN
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        jar,
        copybook_dirs=[sym, app / "cpy", app / "cpy-bms", _CICS_COPYBOOKS],
    )
    screens: queue.Queue = queue.Queue()
    inputs: queue.Queue = queue.Queue()
    context_holder, result_holder, start_queue = [None], [None], StartQueue()
    install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        start_queue=start_queue,
        result_holder=result_holder,
        vsam_engine=_usrsec_engine(tmp_path / "vsam"),
        screen_queue=screens,
        input_queue=inputs,
    )
    spec = build_cics_spec()
    programs = {
        p: compile_cics_program((app / "cbl" / f"{p}.cbl").read_bytes(), parser, spec)
        for p in transactions.values()
    }
    region = CicsRegion(
        programs,
        transactions,
        screens,
        inputs,
        context_holder=context_holder,
        result_holder=result_holder,
        start_queue=start_queue,
        max_steps=1_000_000,
        min_commarea_len=min_commarea_len,
    )
    return PseudoConversationalDriver(
        region, screens, frozenset(transactions)
    ), load_catalog(app / "bms", HLASM_EXPORT_BIN)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_signon_screen_positions_cursor_and_menu(tmp_path, bridge_jar):
    driver, catalog = _driver(tmp_path, bridge_jar)

    first = driver.start("CC00")
    assert isinstance(first, AwaitingInput)
    signon = TerminalScreen().apply_payload(first.screens[-1], catalog)
    assert signon.row(19)[29:42] == "User ID     :"
    assert signon.cursor == address(19, 43) + 1
    assert signon.field("PASSWD").dark

    wrong = driver.respond(
        InputEvent(
            fields={"USERID": "USER0001", "PASSWD": "WRONGPWD"},
            cursor=Cursor(address(20, 43) + 9),
        )
    )
    retry = signon.apply_payload(wrong.screens[-1], catalog)
    assert "Wrong Password" in retry.row(23)
    assert retry.cursor == address(20, 43) + 1

    menu_turn = driver.respond(
        InputEvent(fields={"USERID": "USER0001", "PASSWD": "PASS0001"})
    )
    menu = retry.apply_payload(menu_turn.screens[-1], catalog)
    assert "Main Menu" in menu.text()
    assert menu.cursor == address(20, 41) + 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_menu_reselects_a_second_option_after_pf3(tmp_path, bridge_jar):
    """PF3 out of a menu option, then picking a DIFFERENT one, must reach that
    option -- not the sign-on screen (forge-1zu.6).

    COACTUPC's PF3 branch decides on EIBAID alone and XCTLs back to COMEN01C
    with no RECEIVE MAP on that path, so the PF3 keystroke is never consumed.
    The region must drop it when that task ends; a region that lets it survive
    feeds it to COMEN01C's next RECEIVE MAP, which then reads PF3 instead of
    the operator's ENTER and exits to COSGN00C.
    """
    driver, catalog = _driver(
        tmp_path, bridge_jar, transactions=_MENU_TRANSACTIONS, min_commarea_len=2000
    )
    screen = TerminalScreen()

    driver.start("CC00")
    menu = driver.respond(
        InputEvent(fields={"USERID": "USER0001", "PASSWD": "PASS0001"})
    )
    assert "Main Menu" in screen.apply_payload(menu.screens[-1], catalog).text()

    update = driver.respond(InputEvent(fields={"OPTION": "02"}))
    assert update.screens[-1].map == "CACTUPA"

    back = driver.respond(InputEvent(eibaid=_DFHPF3, fields={}))
    assert isinstance(back, AwaitingInput)
    assert back.screens[-1].map == "COMEN1A"

    view = driver.respond(InputEvent(fields={"OPTION": "01"}))
    assert [s.map for s in view.screens] == ["CACTVWA"]
    assert driver.region.transid == "CAVW"
