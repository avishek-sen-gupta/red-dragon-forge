"""A region assembles from a litter package: its image, mapsets, CSD tables and files, entered by program name."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from catnip.system_catalog import SystemCatalog
from cics.bms.catalog import mapset_json
from cics.bms.generate import generate_symbolic_copybooks
from cics.coprocessor import build_cics_spec
from cics.csd_parse import parse_csd, parse_csd_files
from cics.dispatcher import InputEvent
from cics.screen.driver import Abended, AwaitingInput, Ended, Returned
from cics.screen.payload import SendTextPayload
from cics.tn3270.session import _ended_screen
from cics.screen.terminal_screen import TerminalScreen
from cics.tn3270.region import CICS_COPYBOOKS, ServedRegion, assemble_region
from cics.types import DispatchKind, DispatchResult
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature
from litter.build import build
from litter.cics_file import CicsFile
from litter.open import open_package
from litter.transaction import Transaction
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

_CARDDEMO = Path(__file__).parents[4] / "vendor" / "carddemo" / "app"

_PADA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PADA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CA PIC X(4) VALUE 'PADS'.
       PROCEDURE DIVISION.
           EXEC CICS RETURN TRANSID('PADB') COMMAREA(WS-CA) END-EXEC.
           STOP RUN.
"""

_PADB = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PADB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-OUT.
          05 WS-LEN PIC 9(5).
       LINKAGE SECTION.
       01 DFHCOMMAREA PIC X(4).
       PROCEDURE DIVISION.
           MOVE EIBCALEN TO WS-LEN.
           EXEC CICS RETURN COMMAREA(WS-OUT) END-EXEC.
           STOP RUN.
"""

_RTRNA = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RTRNA.
       PROCEDURE DIVISION.
           EXEC CICS RETURN TRANSID('NOSU') END-EXEC.
           STOP RUN.
"""


_CALLX = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(11) VALUE 'HANDLER RAN'.
       PROCEDURE DIVISION.
           EXEC CICS HANDLE ABEND LABEL(ABEND-ROUTINE) END-EXEC.
           CALL 'NOSUCHPG'.
           EXEC CICS RETURN END-EXEC.
       ABEND-ROUTINE.
           EXEC CICS SEND TEXT FROM(WS-MSG) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""

_OKAY = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OKAY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(2) VALUE 'OK'.
       PROCEDURE DIVISION.
           EXEC CICS SEND TEXT FROM(WS-MSG) END-EXEC.
           EXEC CICS RETURN END-EXEC.
"""


def _noop() -> None:
    return None


def _region(
    tmp_path: Path,
    bridge_jar: str,
    sources: Mapping[str, Path],
    transactions: Sequence[Transaction],
    files: Sequence[CicsFile],
    mapsets: Mapping[str, Path],
    copybook_dirs: Sequence[Path],
    on_abend: Callable[[], None] = _noop,
    permit_unresolved_call_targets: bool = True,
) -> ServedRegion:
    programs = tuple(sources)
    package = build(
        name="region",
        programs=programs,
        link=programs,
        sources=sources,
        parser=ProLeapCobolParser(
            RealSubprocessRunner(),
            bridge_jar,
            copybooks=CopybookSearch(dirs=tuple(copybook_dirs)),
        ),
        specs=(build_cics_spec(),),
        copybook_dirs=copybook_dirs,
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        transactions=transactions,
        files=files,
        mapsets=mapsets,
        tolerant=False,
    )
    return assemble_region(
        open_package(package),
        SystemCatalog(tmp_path / "system"),
        on_abend=on_abend,
        permit_unresolved_call_targets=permit_unresolved_call_targets,
    )


def _written(tmp_path: Path, programs: Mapping[str, str]) -> dict[str, Path]:
    (tmp_path / "src").mkdir()
    return {
        name: _write(tmp_path / "src" / f"{name}.cbl", text)
        for name, text in programs.items()
    }


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


@pytest.mark.carddemo_e2e
@covers(CobolFeature.EXEC_CICS)
def test_sign_on_screen_from_a_package(
    tmp_path: Path, bridge_jar: str, carddemo_system: Path
) -> None:
    sym = tmp_path / "sym"
    hlasm = os.environ["HLASM_EXPORT"]
    generate_symbolic_copybooks(
        bms_dir=_CARDDEMO / "bms", out_dir=sym, hlasm_export_bin=hlasm
    )
    exported = tmp_path / "COSGN00.json"
    exported.write_text(mapset_json(_CARDDEMO / "bms" / "COSGN00.bms", hlasm))
    csd = _CARDDEMO / "csd" / "CARDDEMO.CSD"
    served = _region(
        tmp_path,
        bridge_jar,
        {"COSGN00C": _CARDDEMO / "cbl" / "COSGN00C.cbl"},
        tuple(Transaction(t, p) for t, p in sorted(parse_csd(csd).items())),
        tuple(CicsFile(n, d) for n, d in parse_csd_files(csd).items()),
        {"COSGN00": exported},
        (sym, _CARDDEMO / "cpy", CICS_COPYBOOKS),
    )

    turn = served.driver.start("CC00")
    (sent,) = turn.screens
    screen = TerminalScreen().apply_payload(sent, served.catalog)

    assert (
        type(turn),
        [screen.row(n) for n in range(5, 6)] + [screen.row(n) for n in range(17, 21)],
    ) == (
        AwaitingInput,
        [
            "      This is a Credit Card Demo Application for Mainframe Modernization        ",
            "                Type your User ID and Password, then press ENTER:               ",
            "                                                                                ",
            "                             User ID     :          (8 Char)                    ",
            "                             Password    :          (8 Char)                    ",
        ],
    )


@covers(CobolFeature.EXEC_CICS)
def test_min_commarea_len_defaults_to_the_cics_maximum(
    tmp_path: Path, bridge_jar: str
) -> None:
    served = _region(
        tmp_path,
        bridge_jar,
        _written(tmp_path, {"PADA": _PADA, "PADB": _PADB}),
        (Transaction("PADA", "PADA"), Transaction("PADB", "PADB")),
        (),
        {},
        (CICS_COPYBOOKS,),
    )
    region = served.driver.region

    first = region.start("PADA", input_event=InputEvent())
    second = region.step(input_event=InputEvent())

    assert (first.kind, second) == (
        DispatchKind.RETURN_TRANSID,
        DispatchResult(kind=DispatchKind.RETURN, commarea="32763".encode("cp037")),
    )


@covers(CobolFeature.EXEC_CICS)
def test_a_dispatcher_abend_reaches_the_regions_on_abend(
    tmp_path: Path, bridge_jar: str
) -> None:
    calls: list[str] = []
    served = _region(
        tmp_path,
        bridge_jar,
        _written(tmp_path, {"RTRNA": _RTRNA}),
        (Transaction("RTNA", "RTRNA"),),
        (),
        {},
        (CICS_COPYBOOKS,),
        on_abend=lambda: calls.append("rolled back"),
    )

    result = served.driver.region.start("RTNA", input_event=InputEvent())

    assert (result.kind, calls) == (DispatchKind.RETURN_TRANSID, ["rolled back"])


@covers(CobolFeature.EXEC_CICS)
def test_a_dispatcher_abend_without_an_on_abend_ends_the_task_quietly(
    tmp_path: Path, bridge_jar: str, caplog: pytest.LogCaptureFixture
) -> None:
    served = assemble_region(
        open_package(
            build(
                name="region",
                programs=("RTRNA",),
                link=("RTRNA",),
                sources=_written(tmp_path, {"RTRNA": _RTRNA}),
                parser=ProLeapCobolParser(
                    RealSubprocessRunner(),
                    bridge_jar,
                    copybooks=CopybookSearch(dirs=(CICS_COPYBOOKS,)),
                ),
                specs=(build_cics_spec(),),
                copybook_dirs=(CICS_COPYBOOKS,),
                work_dir=tmp_path / "work",
                out_dir=tmp_path / "out",
                transactions=(Transaction("RTNA", "RTRNA"),),
                files=(),
                mapsets={},
                tolerant=False,
            )
        ),
        SystemCatalog(tmp_path / "system"),
    )

    with caplog.at_level(logging.ERROR, logger="cics.dispatcher"):
        result = served.driver.region.start("RTNA", input_event=InputEvent())

    dispatcher = [r.getMessage() for r in caplog.records if r.name == "cics.dispatcher"]

    assert (result.kind, served.driver.region.done, dispatcher) == (
        DispatchKind.RETURN_TRANSID,
        True,
        ["Unknown transid 'NOSU' from RETURN TRANSID"],
    )


@covers(CobolFeature.EXEC_CICS)
def test_a_call_to_an_unlinked_program_abends_the_task_4038_and_the_terminal_goes_on(
    tmp_path: Path, bridge_jar: str, caplog: pytest.LogCaptureFixture
) -> None:
    rollbacks: list[str] = []
    served = _region(
        tmp_path,
        bridge_jar,
        _written(tmp_path, {"CALLX": _CALLX, "OKAY": _OKAY}),
        (Transaction("CALX", "CALLX"), Transaction("OKAY", "OKAY")),
        (),
        {},
        (CICS_COPYBOOKS,),
        on_abend=lambda: rollbacks.append("rolled back"),
        permit_unresolved_call_targets=False,
    )

    with caplog.at_level(logging.ERROR, logger="cics.dispatcher"):
        abended = served.driver.start("CALX")
    logged = [r.getMessage() for r in caplog.records if r.name == "cics.dispatcher"]
    shown = _ended_screen(
        abended.outcome if isinstance(abended, Ended) else Returned(),
        TerminalScreen(),
    )
    after = served.driver.start("OKAY")

    assert (
        abended,
        shown.row(1),
        logged,
        rollbacks,
        after,
    ) == (
        Ended((), Abended("4038")),
        "Transaction abended: 4038".ljust(80),
        [
            "CALX: CALL to __entry_NOSUCHPG, but nothing in this run unit is"
            " registered under it — abending 4038"
        ],
        ["rolled back"],
        Ended((SendTextPayload("OK"),), Returned()),
    )
