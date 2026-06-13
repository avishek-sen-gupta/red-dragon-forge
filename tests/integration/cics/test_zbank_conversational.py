"""Conversational CICS benchmark — Nantero1/zBANK (cicada-lkx).

zBANK is a genuinely CONVERSATIONAL program: one task loops SEND/RECEIVE across
three screens (ZLOGIN/ZHOME/ZRGSTR), keeps its state in WORKING-STORAGE (no
COMMAREA), and issues a single bare EXEC CICS RETURN only when the user quits.

SPIKE SLICE 1 (this file): vendor the program + map, prove it compiles through
the ProLeap + symbolic-copybook pipeline, render the login screen, and confirm
the bare RETURN terminates the task. The conversational SEND→RECEIVE loop is
driven here with a single pre-staged 'quit' input (so one RECEIVE is consumed
and the pass runs synchronously); true multi-screen driving needs the
greenlet-based ConversationalRegion (slice 2).
"""

from __future__ import annotations

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
