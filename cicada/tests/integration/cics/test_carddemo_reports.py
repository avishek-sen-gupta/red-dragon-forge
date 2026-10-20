"""MANUAL regression test: CORPT00C transaction-reports flow (menu option 09).

CORPT00C is the online front-end for the *batch* transaction report. It does NOT
read TRANSACT; it prompts for a report type + date range, validates the dates
(CALL 'CSUTLDTC'), builds a JCL deck and submits it line-by-line to an extra-
partition Transient Data Queue via EXEC CICS WRITEQ TD QUEUE('JOBS').

This drives the deterministic *Custom* path (fixed start/end dates, so no
dependence on CURRENT-DATE) and asserts the user-visible outcome plus the fact
that the JCL deck was streamed to the TD queue.

  Turn 1-3: sign-on -> COMEN01C -> ENTER option '09' -> XCTL CORPT00C.
  Turn 4: first display (empty form).
  Turn 5: select Custom + dates, CONFIRM blank -> 'Please confirm to print...'.
  Turn 6: resend + CONFIRM='Y' -> WRITEQ TD loop -> 'Custom report submitted...'.
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

_DFHENTER = "\x7d"

_USER_ID = "USER0001"
_USER_PWD = "PASS0001"

# Custom report, fixed range so the flow is deterministic (no CURRENT-DATE).
_REPORT = {
    "CUSTOM": "X",
    "SDTMM": "01",
    "SDTDD": "01",
    "SDTYYYY": "2024",
    "EDTMM": "12",
    "EDTDD": "31",
    "EDTYYYY": "2024",
}


def _ebcdic(s: str, n: int) -> bytes:
    return s.ljust(n)[:n].encode("cp037")


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


def _make_engine(tmp_path: Path) -> VsamEngine:
    clusters = (
        SeedCluster(
            "USRSEC",
            80,
            8,
            (_usrsec_record(_USER_ID, "First1", "Last1", _USER_PWD, "U"),),
        ),
    )
    return VsamEngine(cics_files(*build_test_system(tmp_path, clusters)))


def _drive_to_reports(tmp_path: Path, bridge_jar):
    from cobol_asg.cobol_parser import ProLeapCobolParser
    from cobol_asg.copybook_search import CopybookSearch
    from cobol_asg.subprocess_runner import RealSubprocessRunner

    app = Path(_CARDDEMO_HOME)
    signon_path = app / "cbl" / "COSGN00C.cbl"
    menu_path = app / "cbl" / "COMEN01C.cbl"
    reports_path = app / "cbl" / "CORPT00C.cbl"
    assert reports_path.is_file(), f"CORPT00C not found: {reports_path}"

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
    td_queue: list[str] = []
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
        td_queue=td_queue,
    )
    spec = build_cics_spec()

    signon = compile_cics_program(signon_path.read_bytes(), parser, spec)
    menu = compile_cics_program(menu_path.read_bytes(), parser, spec)
    # CORPT00C CALLs 'CSUTLDTC' to validate the start/end dates; CSUTLDTC in turn
    # CALLs the LE service "CEEDAYS" (no COBOL source, but compile_cics_program
    # always contributes the LE-service stubs). Resolve CSUTLDTC from the app's
    # cbl dir.
    reports = compile_cics_program(
        reports_path.read_bytes(),
        parser,
        spec,
        source_search_dirs=[app / "cbl"],
    )

    program_cache.update({"COSGN00C": signon, "COMEN01C": menu, "CORPT00C": reports})
    transid_to_program = {"CC00": "COSGN00C", "CM00": "COMEN01C", "CR00": "CORPT00C"}
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
    r3 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields={"OPTION": "09"}))
    assert (
        r3.kind == DispatchKind.XCTL and (r3.program or "").strip() == "CORPT00C"
    ), f"menu option '09' XCTL'd to {r3.program!r} (kind={r3.kind}); expected CORPT00C"

    return region, screen_q, td_queue


def _last(screens, mapname):
    matches = [s for s in screens if s.get("map") == mapname]
    return matches[-1]["fields"] if matches else None


@covers(CobolFeature.EXEC_CICS)
def test_real_carddemo_custom_report_submitted(tmp_path, bridge_jar):
    """Custom report, fixed date range: select -> confirm prompt -> CONFIRM='Y'
    -> 'Custom report submitted for printing'. The date range is validated via
    CSUTLDTC; the report-submission loop runs to completion and enqueues JCL
    lines to ``td_queue`` via WRITEQ TD."""
    region, screen_q, td_queue = _drive_to_reports(tmp_path, bridge_jar)

    # Turn 4: first display (empty form).
    drain(screen_q)
    region.step()
    drain(screen_q)

    # Turn 5: select Custom + dates, CONFIRM blank -> confirm prompt.
    region.step(input_event=InputEvent(eibaid=_DFHENTER, fields=dict(_REPORT)))
    f5 = _last(drain(screen_q), "CORPT0A")
    assert f5, "no CORPT0A screen after entering the report request"
    msg5 = (f5.get("ERRMSG") or "").lower()
    assert (
        "confirm to print" in msg5 and "custom" in msg5
    ), f"expected Custom confirm prompt; got {msg5!r}"

    # Turn 6: resend + CONFIRM='Y' -> date validation + JCL-submission loop.
    confirm = dict(_REPORT)
    confirm["CONFIRM"] = "Y"
    r6 = region.step(input_event=InputEvent(eibaid=_DFHENTER, fields=confirm))
    f6 = _last(drain(screen_q), "CORPT0A")
    assert f6, "no CORPT0A screen after confirming"
    msg6 = (f6.get("ERRMSG") or "").lower()
    assert (
        "custom" in msg6 and "submitted for printing" in msg6
    ), f"report not submitted; ERRMSG={f6.get('ERRMSG')!r}"
    assert r6.kind == DispatchKind.RETURN_TRANSID
    assert (r6.transid or "").strip() == "CR00"

    # WRITEQ TD is now dispatched with real operands; JCL lines are streamed
    # to the 'JOBS' TD queue with real content (cicada-vcq).
    assert len(td_queue) > 0, f"expected JCL lines in td_queue, got: {td_queue}"
    assert all(
        line.startswith("[JOBS] ") for line in td_queue
    ), f"expected every line under the 'JOBS' queue, got: {td_queue}"
    assert any(
        "//TRNRPT00 JOB" in line for line in td_queue
    ), f"expected the JCL job card in td_queue, got: {td_queue}"
