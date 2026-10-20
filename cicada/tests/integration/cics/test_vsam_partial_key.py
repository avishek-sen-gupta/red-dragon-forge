"""Integration: partial-key access — GENERIC, KEYLENGTH and GTEQ on READ, STARTBR and DELETE."""

from __future__ import annotations

import queue
from pathlib import Path

import pytest

from cics.dispatcher import run_cics
from cics.preprocessor import apply_cics_prepass
from cics.runtime import install_cics_runtime
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy
from cics.types import CicsContext, DispatchKind
from cics.vsam.engine import VsamEngine
from cics.vsam.eibresp import RESP_NOTFND
from cics.vsam.file_table import cics_files
from cics.vsam.no_record import NoRecord
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature
from interpreter.project.cobol_compile import compile_cobol
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar, main_entry
from tests.vsam_system import SeedCluster, build_test_system

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_KEYS = ("AAAA0001", "BBBB0001", "BBBB0002", "CCCC0001")


def _record(key: str) -> bytes:
    return (key + "body").encode("cp037")


@pytest.fixture
def cobol_parser(bridge_jar):
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(dirs=(_CICS_COPYBOOKS,)),
    )


def _program(ridfld: str, statements: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTPKEY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-KEY   PIC X(8) VALUE '{ridfld}'.
       01 WS-KLEN  PIC S9(4) COMP VALUE 4.
       01 WS-RESP  PIC S9(8) COMP.
       01 WS-N     PIC S9(8) COMP VALUE 0.
       01 WS-OUT.
          05 WS-REC   PIC X(12) VALUE SPACES.
          05 WS-RCODE PIC 9(4).
          05 WS-COUNT PIC 9(4).
       PROCEDURE DIVISION.
{statements}
           MOVE WS-RESP TO WS-RCODE.
           MOVE WS-N TO WS-COUNT.
           EXEC CICS RETURN TRANSID('PK01') COMMAREA(WS-OUT) END-EXEC.
           STOP RUN.
"""


_READ_GENERIC = """\
           EXEC CICS READ FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               GENERIC KEYLENGTH(4) EQUAL RESP(WS-RESP) END-EXEC."""

_READ_GENERIC_GTEQ_BY_NAME = """\
           EXEC CICS READ FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               GENERIC KEYLENGTH(WS-KLEN) GTEQ RESP(WS-RESP) END-EXEC."""

_READ_GTEQ = """\
           EXEC CICS READ FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               GTEQ RESP(WS-RESP) END-EXEC."""

_READ_SHORT_KEYLENGTH = """\
           EXEC CICS READ FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               KEYLENGTH(4) RESP(WS-RESP) END-EXEC."""


def _browse(match: str) -> str:
    return f"""\
           EXEC CICS STARTBR FILE('KEYED') RIDFLD(WS-KEY)
               GENERIC KEYLENGTH(4) {match} RESP(WS-RESP) END-EXEC.
           EXEC CICS READNEXT FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               END-EXEC.
           EXEC CICS ENDBR FILE('KEYED') END-EXEC."""


_DELETE_GENERIC = """\
           EXEC CICS DELETE FILE('KEYED') RIDFLD(WS-KEY)
               GENERIC KEYLENGTH(4) NUMREC(WS-N) RESP(WS-RESP) END-EXEC."""


def _run(cobol_parser, engine: VsamEngine, source: str) -> bytes:
    context_holder = [CicsContext(transid="PK00", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        vsam_engine=engine,
    )
    strategy = CicsLoweringStrategy(
        conversational=False, handler_source=[], unsupported_verbs=set()
    )
    program = compile_cobol(
        apply_cics_prepass(source).encode(),
        parser=cobol_parser,
        extension_strategies=[strategy],
        dialect_parsers=[CicsDialectParser()],
    )
    result = run_cics(
        program,
        context_holder[0],
        queue.Queue(),
        queue.Queue(),
        entry=main_entry(program),
        context_holder=context_holder,
        result_holder=result_holder,
        builtins=runtime.builtins,
    )
    assert result.kind == DispatchKind.RETURN_TRANSID
    return result.commarea


def _engine(tmp_path: Path) -> VsamEngine:
    cluster = SeedCluster("KEYED", 12, 8, tuple(_record(k) for k in _KEYS))
    return VsamEngine(cics_files(*build_test_system(tmp_path, (cluster,))))


def _out(record: str, resp: int, count: int) -> bytes:
    return (record.ljust(12) + f"{resp:04d}{count:04d}").encode("cp037")


@pytest.mark.parametrize(
    "ridfld, statements, expected",
    [
        pytest.param(
            "BBBB9999", _READ_GENERIC, _out("BBBB0001body", 0, 0), id="read-generic"
        ),
        pytest.param(
            "BBBC0000",
            _READ_GENERIC_GTEQ_BY_NAME,
            _out("CCCC0001body", 0, 0),
            id="read-generic-gteq-keylength-by-name",
        ),
        pytest.param(
            "BBBB0003", _READ_GTEQ, _out("CCCC0001body", 0, 0), id="read-gteq"
        ),
        pytest.param(
            "BBBB0001",
            _READ_SHORT_KEYLENGTH,
            _out("", 16, 0),
            id="read-short-keylength-without-generic-is-invreq",
        ),
        pytest.param(
            "BBBB9999",
            _browse("EQUAL"),
            _out("BBBB0001body", 0, 0),
            id="startbr-generic-equal",
        ),
        pytest.param(
            "BBBB9999",
            _browse("GTEQ"),
            _out("BBBB0001body", 0, 0),
            id="startbr-generic-gteq",
        ),
        pytest.param(
            "DDDD0000", _DELETE_GENERIC, _out("", 13, 0), id="delete-generic-none"
        ),
    ],
)
@covers(CobolFeature.EXEC_CICS)
def test_a_partial_key_matches_on_its_leading_bytes(
    cobol_parser, tmp_path, ridfld, statements, expected
):
    engine = _engine(tmp_path)

    assert _run(cobol_parser, engine, _program(ridfld, statements)) == expected


@covers(CobolFeature.EXEC_CICS)
def test_a_generic_delete_removes_every_record_with_the_prefix(cobol_parser, tmp_path):
    engine = _engine(tmp_path)

    out = _run(cobol_parser, engine, _program("BBBB9999", _DELETE_GENERIC))

    assert out == _out("", 0, 2)
    assert [
        engine.read("KEYED", k.encode("cp037")) == NoRecord(RESP_NOTFND) for k in _KEYS
    ] == [False, True, True, False]


_RESET_TO_THE_FIRST_RECORD = """\
           EXEC CICS STARTBR FILE('KEYED') RIDFLD(WS-KEY) END-EXEC.
           EXEC CICS READNEXT FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               END-EXEC.
           EXEC CICS READNEXT FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               END-EXEC.
           MOVE 'AAAA0001' TO WS-KEY.
           EXEC CICS RESETBR FILE('KEYED') RIDFLD(WS-KEY) EQUAL
               RESP(WS-RESP) END-EXEC.
           EXEC CICS READNEXT FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               END-EXEC.
           EXEC CICS ENDBR FILE('KEYED') END-EXEC."""

_RESET_TO_A_GENERIC_KEY = """\
           EXEC CICS STARTBR FILE('KEYED') RIDFLD(WS-KEY) END-EXEC.
           MOVE 'CCCC9999' TO WS-KEY.
           EXEC CICS RESETBR FILE('KEYED') RIDFLD(WS-KEY) GENERIC
               KEYLENGTH(4) GTEQ RESP(WS-RESP) END-EXEC.
           EXEC CICS READNEXT FILE('KEYED') INTO(WS-REC) RIDFLD(WS-KEY)
               END-EXEC.
           EXEC CICS ENDBR FILE('KEYED') END-EXEC."""

_RESET_WITHOUT_A_BROWSE = """\
           EXEC CICS RESETBR FILE('KEYED') RIDFLD(WS-KEY)
               RESP(WS-RESP) END-EXEC."""


@pytest.mark.parametrize(
    "statements, expected",
    [
        pytest.param(
            _RESET_TO_THE_FIRST_RECORD,
            _out("AAAA0001body", 0, 0),
            id="back-to-an-earlier-key",
        ),
        pytest.param(
            _RESET_TO_A_GENERIC_KEY, _out("CCCC0001body", 0, 0), id="generic-key"
        ),
        pytest.param(_RESET_WITHOUT_A_BROWSE, _out("", 16, 0), id="no-browse-invreq"),
    ],
)
@covers(CobolFeature.EXEC_CICS)
def test_resetbr_repositions_the_open_browse(
    cobol_parser, tmp_path, statements, expected
):
    engine = _engine(tmp_path)

    assert _run(cobol_parser, engine, _program("AAAA0001", statements)) == expected
