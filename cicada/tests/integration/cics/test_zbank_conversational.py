"""Conversational CICS benchmark — Nantero1/zBANK (cicada-lkx).

zBANK is a genuinely CONVERSATIONAL program: one task loops SEND/RECEIVE across
three screens (ZLOGIN/ZHOME/ZRGSTR), keeps its state in WORKING-STORAGE (no
COMMAREA), and issues a single bare EXEC CICS RETURN only when the user quits.

SLICE 1: vendor the program + map, prove it compiles through the ProLeap +
symbolic-copybook pipeline, render the login screen, and confirm the bare RETURN
terminates the task (driven synchronously with a single pre-staged input).

SLICE 2: drive the full conversational SEND/RECEIVE loop across screens via the
suspend/resume ConversationalRegion — login -> deposit -> quit, with
working-storage persisting across each terminal wait inside one run_cics.
"""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.conversational import ConversationalRegion
from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.interval import StartQueue
from cics.dispatcher import CicsRegion, InputEvent
from cics.types import DispatchKind
from cics.vsam.record_read import RecordRead
from cics.vsam.engine import VsamEngine
from cics.vsam.file_table import cics_files
from interpreter.cobol.features import CobolFeature
from tests.vsam_system import SeedCluster, build_test_system
from tests.covers import covers
from tests.integration.cics.bms_tools_helpers import HLASM_EXPORT_BIN
from tests.integration.cics.channel_drain import drain
from tests.integration.cobol_helpers import bridge_jar

pytestmark = pytest.mark.carddemo_e2e

_FIXTURES = Path(__file__).parent / "fixtures" / "zbank"
_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_DFHENTER = "\x7d"
_ZBNK_RECLN = 30

_ACCT = "0000000001"
_PIN = "0000001234"
_BALANCE = "0000005000"


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


def _zbnk_record(acct: str, pin: str, balance: str) -> bytes:
    # VSAMZBNK record (30 bytes): ACCNO 9(10) + PIN 9(10) + BALANCE 9(10).
    rec = _ebcdic(acct, 10) + _ebcdic(pin, 10) + _ebcdic(balance, 10)
    return rec[:_ZBNK_RECLN]


def _make_engine(tmp_path: Path) -> VsamEngine:
    clusters = (
        SeedCluster(
            "VSAMZBNK", _ZBNK_RECLN, 10, (_zbnk_record(_ACCT, _PIN, _BALANCE),)
        ),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _build_region(tmp_path: Path, bridge_jar, *, receive_timeout: float = 30.0):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    prog_path = _FIXTURES / "ZBANK.cbl"
    assert prog_path.is_file(), f"zBANK program not vendored: {prog_path}"

    sym_dir = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=_FIXTURES,
        out_dir=sym_dir,
        hlasm_export_bin=HLASM_EXPORT_BIN,
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(dirs=(sym_dir, _CICS_COPYBOOKS)),
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
        receive_timeout=receive_timeout,
    )
    spec = build_cics_spec()

    prog = compile_cics_program(prog_path.read_bytes(), parser, spec)
    region = CicsRegion(
        {"ZBANK": prog},
        {"ZBNK": "ZBANK"},
        screen_q,
        input_q,
        context_holder=context_holder,
        start_queue=start_queue,
        result_holder=result_holder,
        max_steps=2_000_000,
        builtins=runtime.builtins,
    )
    return region, screen_q, engine


def _build_conversational(tmp_path: Path, bridge_jar):
    """Wire zBANK behind the suspend/resume ConversationalRegion: the strategy is
    built with conversational=True (RECEIVE MAP -> SUSPEND), and the region drives
    via run_linked_resumable/resume_linked."""
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    sym_dir = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=_FIXTURES, out_dir=sym_dir, hlasm_export_bin=HLASM_EXPORT_BIN
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(dirs=(sym_dir, _CICS_COPYBOOKS)),
    )
    engine = _make_engine(tmp_path)
    screen_q: queue.Queue = queue.Queue()
    # input_queue is unused in conversational mode (RECEIVE suspends rather than
    # reading it), but the strategy only registers the screen builtins when an
    # input_queue is present, so pass a dummy one.
    input_q: queue.Queue = queue.Queue()
    context_holder = [None]
    result_holder: list = [None]
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_q,
    )
    spec = build_cics_spec(conversational=True)
    prog = compile_cics_program(
        (_FIXTURES / "ZBANK.cbl").read_bytes(),
        parser,
        spec,
    )
    region = ConversationalRegion(
        prog,
        "ZBNK",
        screen_queue=screen_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=2_000_000,
        builtins=runtime.builtins,
    )
    return region, engine


def _maps(screens):
    return [s.get("map") for s in screens]


def _field(screens, mapname, field):
    for s in reversed(screens):
        if s.get("map") == mapname:
            return s["fields"].get(field)
    return None


def _balance(engine) -> str:
    rec_read = engine.read("VSAMZBNK", _ACCT.encode("cp037"))
    assert isinstance(rec_read, RecordRead), "account vanished"
    rec = rec_read.record
    return bytes(rec[20:30]).decode("cp037")  # WS-BALANCE 9(10) @20


@covers(CobolFeature.EXEC_CICS)
def test_zbank_conversational_login_deposit_withdraw_quit(tmp_path, bridge_jar):
    """SLICE 2 + 4: drive the full conversational SEND/RECEIVE loop across screens
    via the suspend/resume ConversationalRegion. Working-storage persists across each
    terminal wait within ONE run_cics, so the balance READ at login is still in WS
    when deposit/withdraw REWRITE it. Ends at the single bare EXEC CICS RETURN.

      start              -> SEND login, pause at RECEIVE
      send(valid login)  -> READ ok + PIN match -> SCREEN-STATE home, SEND home
      send(deposit 100)  -> ADD + REWRITE -> balance 5000 -> 5100
      send(withdraw 50)  -> SUBTRACT + REWRITE -> balance 5100 -> 5050
      send(quit home)    -> back to login
      send(quit login)   -> EXIT-CONDITION -> bare RETURN
    """
    region, engine = _build_conversational(tmp_path, bridge_jar)
    assert _balance(engine) == "0000005000"  # pre-condition

    # Turn 1: first display.
    s = region.start(commarea=b"\x00" * 100)
    assert "ZLOGIN" in _maps(s)
    assert "PLEASE LOG IN!" in (_field(s, "ZLOGIN", "LOGINFO") or "")

    # Turn 2: valid login (correct PIN) -> advances to the home screen, which
    # shows the balance READ at login (proves working-storage persisted).
    s = region.send(
        InputEvent(eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "1234"})
    )
    assert "ZHOME" in _maps(s), f"expected ZHOME after login; got {_maps(s)}"
    assert (_field(s, "ZHOME", "BALANCE") or "").strip() in ("0000005000", "5000")

    # Turn 3: deposit 100 -> REWRITE persists 5100. zBANK's AMOUNT is ATTRB=NUM
    # but has no PICIN, so AMOUNTI is X(10) and MOVEd straight to a 9(10) field;
    # the wire form must be the full-width "0000000100" (the operator entering all
    # ten digits) — exactly as on real z/OS without a numeric PICIN.
    s = region.send(
        InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "D", "AMOUNT": "0000000100"})
    )
    assert (
        _balance(engine) == "0000005100"
    ), f"deposit not persisted: {_balance(engine)!r}"

    # Turn 4: withdraw 50 -> SUBTRACT + REWRITE persists 5050.
    s = region.send(
        InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "W", "AMOUNT": "0000000050"})
    )
    assert (
        _balance(engine) == "0000005050"
    ), f"withdrawal not persisted: {_balance(engine)!r}"

    # Turn 5: quit home -> back to login.
    s = region.send(InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "Q"}))
    assert "ZLOGIN" in _maps(s), f"expected return to ZLOGIN; got {_maps(s)}"

    # Turn 6: quit from login (valid account, wrong PIN so it does not re-advance)
    # -> EXIT-CONDITION -> the single bare RETURN ends the task.
    s = region.send(
        InputEvent(
            eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "9999", "LOGACT": "Q"}
        )
    )
    assert region.done, "task did not end after quit-from-login"
    assert region.result is not None and region.result.kind == DispatchKind.RETURN


@covers(CobolFeature.EXEC_CICS)
def test_zbank_compiles_renders_login_and_returns(tmp_path, bridge_jar):
    """SLICE 1 (retires R2 + R4): the conversational program compiles through the
    ProLeap + symbolic-copybook pipeline, runs, renders its login map, and reaches
    the single bare EXEC CICS RETURN (task end).

    This asserts only what is provable WITHOUT a conversational driver. A short
    receive_timeout bounds the run: the synchronous region can satisfy only the
    first RECEIVE, so the SEND/RECEIVE loop spins briefly and ends at RETURN.

    KNOWN GAPS surfaced here, owned by later slices:
      * RECEIVE MAP field delivery does not land for this program — an input of
        LOGACT='R'/'Q' does not reach ZLOGINI, so login mis-validates and the
        loop cannot be driven/terminated by input. This is the SLICE 2 lead.
      * EXEC CICS UNLOCK is unimplemented (logs 'unimplemented verb'); SLICE 3.
    """
    region, screen_q, _ = _build_region(tmp_path, bridge_jar, receive_timeout=0.05)

    r = region.start(
        "ZBNK",
        commarea=b"\x00" * 100,
        input_event=InputEvent(eibaid=_DFHENTER, fields={"LOGACT": "Q"}),
        max_steps=80_000,
    )
    screens = drain(screen_q)
    maps = [s.get("map") for s in screens]

    # Compiles + runs + renders the login map with the program's initial prompt.
    first_login = next((s for s in screens if s.get("map") == "ZLOGIN"), None)
    assert first_login is not None, f"no ZLOGIN rendered; saw maps={sorted(set(maps))}"
    assert "PLEASE LOG IN!" in (first_login["fields"].get("LOGINFO") or "")

    # The bare EXEC CICS RETURN (no TRANSID) is reachable — the task terminates.
    assert r.kind == DispatchKind.RETURN, f"expected task-end RETURN, got {r.kind}"


@covers(CobolFeature.EXEC_CICS)
def test_zbank_conversational_extended_session(tmp_path, bridge_jar):
    """SLICE 2 (stress): one long conversation with many turns — multiple
    deposits/withdrawals, the no-op transfer, a register-screen detour, and a
    RE-LOGIN that proves the balance persisted in VSAM across logins. Everything
    runs inside ONE task (suspend/resume), so this exercises the driver and
    working-storage persistence over ~16 terminal exchanges before the bare
    RETURN.
    """
    region, engine = _build_conversational(tmp_path, bridge_jar)
    assert _balance(engine) == "0000005000"

    region.start(commarea=b"\x00" * 100)  # login screen
    s = region.send(  # valid login -> home
        InputEvent(eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "1234"})
    )
    assert "ZHOME" in _maps(s)

    # A run of deposits/withdrawals; balance accumulates in WS and is REWRITTEN
    # each time (AMOUNT sent full-width, as zBANK has no PICIN on it).
    for act, amount, expected in [
        ("D", "0000000100", "0000005100"),
        ("D", "0000000200", "0000005300"),
        ("W", "0000000050", "0000005250"),
        ("D", "0000001000", "0000006250"),
        ("W", "0000000250", "0000006000"),
    ]:
        region.send(
            InputEvent(eibaid=_DFHENTER, fields={"HOMACT": act, "AMOUNT": amount})
        )
        assert _balance(engine) == expected, f"{act} {amount}: {_balance(engine)!r}"

    # Transfer is a no-op in zBANK: stays on home, balance unchanged.
    s = region.send(InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "T"}))
    assert "ZHOME" in _maps(s)
    assert _balance(engine) == "0000006000"

    # Quit home -> login, then take the REGISTER detour and come back.
    s = region.send(InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "Q"}))
    assert "ZLOGIN" in _maps(s)
    s = region.send(
        InputEvent(
            eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "1234", "LOGACT": "R"}
        )
    )
    assert "ZRGSTR" in _maps(s), f"expected register screen; got {_maps(s)}"
    s = region.send(InputEvent(eibaid=_DFHENTER, fields={"REGACT": "Q"}))
    assert "ZLOGIN" in _maps(s)

    # Re-login: the balance changed earlier in this session must still be in VSAM.
    s = region.send(
        InputEvent(eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "1234"})
    )
    assert "ZHOME" in _maps(s)
    assert (_field(s, "ZHOME", "BALANCE") or "").strip() == "0000006000"

    # Quit all the way out -> bare RETURN.
    region.send(InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "Q"}))
    region.send(
        InputEvent(
            eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "9999", "LOGACT": "Q"}
        )
    )
    assert region.done
    assert region.result is not None and region.result.kind == DispatchKind.RETURN
    assert _balance(engine) == "0000006000"
