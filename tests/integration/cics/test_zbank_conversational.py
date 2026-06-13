"""Conversational CICS benchmark — Nantero1/zBANK (cicada-lkx).

zBANK is a genuinely CONVERSATIONAL program: one task loops SEND/RECEIVE across
three screens (ZLOGIN/ZHOME/ZRGSTR), keeps its state in WORKING-STORAGE (no
COMMAREA), and issues a single bare EXEC CICS RETURN only when the user quits.

SLICE 1: vendor the program + map, prove it compiles through the ProLeap +
symbolic-copybook pipeline, render the login screen, and confirm the bare RETURN
terminates the task (driven synchronously with a single pre-staged input).

SLICE 2: drive the full conversational SEND/RECEIVE loop across screens via the
greenlet-based ConversationalRegion — login -> deposit -> quit, with
working-storage persisting across each terminal wait inside one run_cics.
"""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.bootstrap import compile_cics_program
from cics.bms.generate import generate_symbolic_copybooks
from cics.conversational import ConversationalRegion, GreenletInputChannel
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


_FCT_YAML = """\
datasets:
  VSAMZBNK:
    record_length: 30
    file: VSAMZBNK.dat
    key_length: 10
"""


def _make_engine(tmp_path: Path) -> VsamEngine:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    write_flat_file(
        data_dir / "VSAMZBNK.dat",
        [_zbnk_record(_ACCT, _PIN, _BALANCE)],
        _ZBNK_RECLN,
    )
    fct_path = tmp_path / "fct.yaml"
    fct_path.write_text(_FCT_YAML)
    seed = load_vsam_seed(fct_path, data_dir)
    fct = FctConfig.from_yaml(fct_path)
    engine = VsamEngine(fct, backend=InMemoryBackend(seed=seed))
    engine.load_all()
    return engine


def _build_region(tmp_path: Path, *, receive_timeout: float = 30.0):
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.cobol.subprocess_runner import RealSubprocessRunner

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
        JAR_PATH,
        copybook_dirs=[sym_dir, _CICS_COPYBOOKS],
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
        receive_timeout=receive_timeout,
    )

    prog = compile_cics_program(
        apply_cics_prepass(prog_path.read_text()).encode(), parser, strategy
    )
    region = CicsRegion(
        {"ZBANK": prog},
        {"ZBNK": "ZBANK"},
        screen_q,
        input_q,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=2_000_000,
    )
    return region, screen_q, engine


def _build_conversational(tmp_path: Path):
    """Wire zBANK behind a greenlet ConversationalRegion (RECEIVE cooperatively
    suspends instead of blocking)."""
    from interpreter.cobol.cobol_parser import ProLeapCobolParser
    from interpreter.cobol.subprocess_runner import RealSubprocessRunner

    sym_dir = tmp_path / "sym"
    generate_symbolic_copybooks(
        bms_dir=_FIXTURES, out_dir=sym_dir, hlasm_export_bin=HLASM_EXPORT_BIN
    )
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), JAR_PATH, copybook_dirs=[sym_dir, _CICS_COPYBOOKS]
    )
    engine = _make_engine(tmp_path)
    screen_q: queue.Queue = queue.Queue()
    input_channel = GreenletInputChannel()
    context_holder = [None]
    result_holder: list = [None]
    strategy = CicsLoweringStrategy(
        context_holder=context_holder,
        result_holder=result_holder,
        vsam_engine=engine,
        screen_queue=screen_q,
        input_queue=input_channel,
    )
    prog = compile_cics_program(
        apply_cics_prepass((_FIXTURES / "ZBANK.cbl").read_text()).encode(),
        parser,
        strategy,
    )
    region = ConversationalRegion(
        prog,
        "ZBNK",
        screen_queue=screen_q,
        input_channel=input_channel,
        context_holder=context_holder,
        result_holder=result_holder,
        max_steps=2_000_000,
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
    rec, _ = engine.read("VSAMZBNK", _ACCT.encode("cp037"), 10)
    assert rec is not None, "account vanished"
    return bytes(rec[20:30]).decode("cp037")  # WS-BALANCE 9(10) @20


@covers(CobolFeature.EXEC_CICS)
def test_zbank_conversational_login_deposit_quit(tmp_path):
    """SLICE 2: drive the conversational SEND/RECEIVE loop across screens via the
    greenlet ConversationalRegion. Working-storage persists across each terminal
    wait within ONE run_cics, so the balance read at login is still in WS when the
    deposit REWRITEs it. Ends at the single bare EXEC CICS RETURN.

      start            -> SEND login, pause at RECEIVE
      send(valid login)-> READ ok + PIN match -> SCREEN-STATE home, SEND home
      send(deposit 100)-> ADD + REWRITE -> balance 5000 -> 5100
      send(quit home)  -> back to login
      send(quit login) -> EXIT-CONDITION -> bare RETURN
    """
    region, engine = _build_conversational(tmp_path)
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

    # Turn 3: deposit 100 -> REWRITE persists 5100. A 3270 NUM field transmits
    # right-justified, zero-filled, so the wire form of "100" in AMOUNT(10) is
    # "0000000100" (sending it left-justified would read as 1_000_000_000).
    s = region.send(
        InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "D", "AMOUNT": "0000000100"})
    )
    assert (
        _balance(engine) == "0000005100"
    ), f"deposit not persisted: {_balance(engine)!r}"

    # Turn 4: quit home -> back to login.
    s = region.send(InputEvent(eibaid=_DFHENTER, fields={"HOMACT": "Q"}))
    assert "ZLOGIN" in _maps(s), f"expected return to ZLOGIN; got {_maps(s)}"

    # Turn 5: quit from login (valid account, wrong PIN so it does not re-advance)
    # -> EXIT-CONDITION -> the single bare RETURN ends the task.
    s = region.send(
        InputEvent(
            eibaid=_DFHENTER, fields={"LOGACC": _ACCT, "LOGPIN": "9999", "LOGACT": "Q"}
        )
    )
    assert region.done, "task did not end after quit-from-login"
    assert region.result is not None and region.result.kind == DispatchKind.RETURN


@covers(CobolFeature.EXEC_CICS)
def test_zbank_compiles_renders_login_and_returns(tmp_path):
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
    region, screen_q, _ = _build_region(tmp_path, receive_timeout=0.05)

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
