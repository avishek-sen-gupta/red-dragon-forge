"""Integration: ASKTIME stores the region's local absolute time; FORMATTIME formats the ABSTIME it is given."""

from __future__ import annotations

import queue
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cics.dispatcher import run_cics
from cics.preprocessor import apply_cics_prepass
from cics.dat_form import DatForm
from cics.region_clock import RegionClock
from cics.runtime import install_cics_runtime
from cics.statements import CicsDialectParser
from cics.strategy import CicsLoweringStrategy
from cics.types import CicsContext, DispatchKind
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.features import CobolFeature
from interpreter.project.cobol_compile import compile_cobol
from tests.covers import covers
from tests.integration.cobol_helpers import bridge_jar, main_entry

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"

_IST = timezone(timedelta(hours=5, minutes=30))
_TWENTY_FIRST_OCTOBER = datetime(2026, 10, 21, 9, 5, 7, 250000, tzinfo=_IST)
_MS_PER_DAY = 86_400_000
_TWENTY_FIRST_OCTOBER_ABSTIME = 46_314 * _MS_PER_DAY + 32_707_250


@pytest.fixture
def cobol_parser(bridge_jar):
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        bridge_jar,
        copybooks=CopybookSearch(dirs=(_CICS_COPYBOOKS,)),
    )


def _program(abstime: int, statements: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTTIME.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-T     PIC S9(15) COMP-3 VALUE {abstime}.
       01 WS-YEAR  PIC S9(8) COMP VALUE 0.
       01 WS-OUT.
          05 O-YYYYMMDD PIC X(10) VALUE SPACES.
          05 O-DDMMYYYY PIC X(10) VALUE SPACES.
          05 O-DDMMYY   PIC X(8) VALUE SPACES.
          05 O-YYMMDD   PIC X(8) VALUE SPACES.
          05 O-MMDDYY   PIC X(8) VALUE SPACES.
          05 O-DATE     PIC X(8) VALUE SPACES.
          05 O-FULLDATE PIC X(10) VALUE SPACES.
          05 O-DATEFORM PIC X(6) VALUE SPACES.
          05 O-TIME     PIC X(8) VALUE SPACES.
          05 O-YEAR     PIC 9(4) VALUE 0.
          05 O-AGAIN    PIC X(10) VALUE SPACES.
          05 O-ABS      PIC 9(15) VALUE 0.
       PROCEDURE DIVISION.
{statements}
           MOVE WS-YEAR TO O-YEAR.
           MOVE WS-T TO O-ABS.
           EXEC CICS RETURN TRANSID('TM01') COMMAREA(WS-OUT) END-EXEC.
           STOP RUN.
"""


_EVERY_OUTPUT = """\
           EXEC CICS FORMATTIME ABSTIME(WS-T)
               YYYYMMDD(O-YYYYMMDD) DDMMYYYY(O-DDMMYYYY)
               DDMMYY(O-DDMMYY) YYMMDD(O-YYMMDD)
               MMDDYY(O-MMDDYY) DATE(O-DATE)
               FULLDATE(O-FULLDATE) DATEFORM(O-DATEFORM)
               TIME(O-TIME) YEAR(WS-YEAR)
               DATESEP('-') TIMESEP END-EXEC."""

_NO_SEPARATORS = """\
           EXEC CICS FORMATTIME ABSTIME(WS-T)
               YYYYMMDD(O-YYYYMMDD) DATE(O-DATE)
               TIME(O-TIME) END-EXEC."""

_ASKED_THEN_FORMATTED_TWICE = """\
           EXEC CICS ASKTIME ABSTIME(WS-T) END-EXEC.
           EXEC CICS FORMATTIME ABSTIME(WS-T) YYYYMMDD(O-YYYYMMDD)
               DATESEP END-EXEC.
           EXEC CICS FORMATTIME ABSTIME(WS-T) YYYYMMDD(O-AGAIN)
               DATESEP END-EXEC."""


def _run(cobol_parser, source: str, clock: RegionClock) -> bytes:
    context_holder = [CicsContext(transid="TM00", commarea=b"", eibaid="\x7d")]
    result_holder: list = [None]
    runtime = install_cics_runtime(
        context_holder,
        transid_to_program={},
        program_cache={},
        result_holder=result_holder,
        clock=clock,
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


def _out(fields: dict[str, str], year: int, abstime: int) -> bytes:
    widths = {
        "YYYYMMDD": 10,
        "DDMMYYYY": 10,
        "DDMMYY": 8,
        "YYMMDD": 8,
        "MMDDYY": 8,
        "DATE": 8,
        "FULLDATE": 10,
        "DATEFORM": 6,
        "TIME": 8,
    }
    text = "".join(fields.get(name, "").ljust(width) for name, width in widths.items())
    return (
        text + f"{year:04d}" + fields.get("AGAIN", "").ljust(10) + f"{abstime:015d}"
    ).encode("cp037")


def _stopped(datform: DatForm) -> RegionClock:
    return RegionClock(now=lambda: _TWENTY_FIRST_OCTOBER, datform=datform)


@pytest.mark.parametrize(
    "abstime, statements, datform, expected",
    [
        pytest.param(
            3160857599999,
            _EVERY_OUTPUT,
            DatForm.DDMMYY,
            _out(
                {
                    "YYYYMMDD": "2000-02-29",
                    "DDMMYYYY": "29-02-2000",
                    "DDMMYY": "29-02-00",
                    "YYMMDD": "00-02-29",
                    "MMDDYY": "02-29-00",
                    "DATE": "29-02-00",
                    "FULLDATE": "29-02-2000",
                    "DATEFORM": "DDMMYY",
                    "TIME": "23:59:59",
                },
                2000,
                3160857599999,
            ),
            id="every-output-on-a-leap-day",
        ),
        pytest.param(
            _TWENTY_FIRST_OCTOBER_ABSTIME,
            _NO_SEPARATORS,
            DatForm.MMDDYY,
            _out(
                {"YYYYMMDD": "20261021", "DATE": "102126", "TIME": "090507"},
                0,
                _TWENTY_FIRST_OCTOBER_ABSTIME,
            ),
            id="no-separators-default-datform",
        ),
    ],
)
@covers(CobolFeature.EXEC_CICS)
def test_formattime_formats_the_abstime_it_is_given(
    cobol_parser, abstime, statements, datform, expected
):
    assert _run(cobol_parser, _program(abstime, statements), _stopped(datform)) == (
        expected
    )


@covers(CobolFeature.EXEC_CICS)
def test_asktime_stores_the_regions_local_absolute_time(cobol_parser):
    out = _run(
        cobol_parser,
        _program(0, _ASKED_THEN_FORMATTED_TWICE),
        _stopped(DatForm.MMDDYY),
    )

    assert out == _out(
        {"YYYYMMDD": "2026/10/21", "AGAIN": "2026/10/21"},
        0,
        _TWENTY_FIRST_OCTOBER_ABSTIME,
    )
