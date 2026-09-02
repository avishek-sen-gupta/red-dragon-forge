"""Unit tests for run_cics() and the CICS dispatcher loop."""

import inspect
import queue
from unittest.mock import MagicMock

import pytest

from tests.covers import covers, NotLanguageFeature
from interpreter.run import run_linked
from cics.types import CicsContext, DispatchKind, DispatchResult
from cics.csd_parse import CsdParseError
from cics.dispatcher import (
    _run_dispatcher_with_runner,
    _advance_routing,
    CicsRegion,
    InputEvent,
    parse_csd,
    parse_csd_files,
)
import cics.dispatcher as dispatcher_mod


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_run_linked_accepts_initial_vm():
    sig = inspect.signature(run_linked)
    assert "initial_vm" in sig.parameters


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_return_stops_loop():
    calls = []

    def mock_run(program, ctx, sq, iq):
        calls.append(ctx.transid)
        return DispatchResult(kind=DispatchKind.RETURN)

    program_cache = {"PROG1": MagicMock()}
    transid_to_program = {"CC00": "PROG1"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()

    result = _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert result.kind == DispatchKind.RETURN
    assert len(calls) == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_xctl_switches_program():
    call_count = [0]

    def mock_run(program, ctx, sq, iq):
        call_count[0] += 1
        if call_count[0] == 1:
            return DispatchResult(kind=DispatchKind.XCTL, program="PROG2", commarea=b"")
        return DispatchResult(kind=DispatchKind.RETURN)

    program_cache = {"PROG1": MagicMock(), "PROG2": MagicMock()}
    transid_to_program = {"CC00": "PROG1"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()

    result = _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert call_count[0] == 2
    assert result.kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_return_transid_blocks_then_resumes():
    call_count = [0]

    def mock_run(program, ctx, sq, iq):
        call_count[0] += 1
        if call_count[0] == 1:
            return DispatchResult(
                kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b""
            )
        return DispatchResult(kind=DispatchKind.RETURN)

    program_cache = {"PROG1": MagicMock(), "PROG2": MagicMock()}
    transid_to_program = {"CC00": "PROG1", "CC01": "PROG2"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()
    iq.put(InputEvent(eibaid="\x7d", fields={}))

    result = _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert call_count[0] == 2
    assert result.kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_resume_propagates_event_eibaid_to_context():
    """On RETURN TRANSID resume, the input event's attention key flows into the
    next turn's CicsContext (which init_eib then writes to EIBAID)."""
    seen_eibaids: list[str] = []

    def mock_run(program, ctx, sq, iq):
        seen_eibaids.append(ctx.eibaid)
        if len(seen_eibaids) == 1:
            return DispatchResult(
                kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b""
            )
        return DispatchResult(kind=DispatchKind.RETURN)

    program_cache = {"PROG1": MagicMock(), "PROG2": MagicMock()}
    transid_to_program = {"CC00": "PROG1", "CC01": "PROG2"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()
    # The resumed turn's terminal input carries PF3.
    iq.put(InputEvent(eibaid="\xf3", fields={}))

    _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert seen_eibaids[0] == "\x7d"  # first turn: initial context aid
    assert seen_eibaids[1] == "\xf3"  # resumed turn: event's aid propagated


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_resume_leaves_event_on_queue_for_receive_map(monkeypatch):
    """On RETURN TRANSID resume, the loop reads the next event's eibaid but must
    NOT consume it — the resumed turn's own RECEIVE MAP (a second, separate
    input_queue.get()) still needs that same event's field values. (v2om)"""
    seen_eibaids: list[str] = []
    drained_by_receive_map: list[InputEvent] = []

    def mock_run(program, ctx, sq, iq):
        seen_eibaids.append(ctx.eibaid)
        if len(seen_eibaids) == 1:
            return DispatchResult(
                kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b""
            )
        # Mimic RECEIVE MAP's own consume on the resumed turn.
        drained_by_receive_map.append(iq.get(block=False))
        return DispatchResult(kind=DispatchKind.RETURN)

    program_cache = {"PROG1": MagicMock(), "PROG2": MagicMock()}
    transid_to_program = {"CC00": "PROG1", "CC01": "PROG2"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()
    event = InputEvent(eibaid="\xf3", fields={"USERID": "U"})
    iq.put(event)

    _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert seen_eibaids[1] == "\xf3"  # loop still learns the eibaid
    assert drained_by_receive_map == [event]  # AND RECEIVE MAP still gets the event


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_peek_input_event_raises_empty_on_timeout():
    """_peek_input_event on an empty queue raises queue.Empty after its timeout,
    rather than blocking forever (red-dragon-pz9g.14)."""
    from cics.dispatcher import _peek_input_event

    empty_queue: queue.Queue = queue.Queue()
    with pytest.raises(queue.Empty):
        _peek_input_event(empty_queue, timeout=0.05)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dispatcher_return_transid_timeout_abends_azct(monkeypatch):
    """If no further terminal input ever arrives after RETURN TRANSID, the loop
    returns ABEND/AZCT instead of hanging forever (red-dragon-pz9g.14)."""

    def mock_run(program, ctx, sq, iq):
        return DispatchResult(
            kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b""
        )

    def fake_peek(input_queue, timeout=30.0):
        raise queue.Empty

    monkeypatch.setattr(dispatcher_mod, "_peek_input_event", fake_peek)

    program_cache = {"PROG1": MagicMock(), "PROG2": MagicMock()}
    transid_to_program = {"CC00": "PROG1", "CC01": "PROG2"}
    ctx = CicsContext(transid="CC00", commarea=b"", eibaid="\x7d")
    sq, iq = queue.Queue(), queue.Queue()

    result = _run_dispatcher_with_runner(
        mock_run, program_cache, transid_to_program, ctx, sq, iq
    )
    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "AZCT"


# ─────────────────────────────────────────────────────────────────────────────
# _advance_routing — the single copy of the "which program/transid next" rule.
# ─────────────────────────────────────────────────────────────────────────────


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_advance_routing_return_transid_maps_via_csd():
    """RETURN TRANSID resolves the next program via the transid→program map and
    returns (stripped transid, that program, commarea)."""
    prog2 = object()
    program_cache = {"PROG1": object(), "PROG2": prog2}
    transid_to_program = {"CC00": "PROG1", "CC01": "PROG2"}
    result = DispatchResult(
        kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b"AB"
    )
    out = _advance_routing(result, "CC00", program_cache, transid_to_program)
    assert out == ("CC01", prog2, b"AB")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_advance_routing_return_transid_strips_and_defaults_commarea():
    """transid is stripped of trailing pad and a None commarea becomes b''."""
    prog2 = object()
    program_cache = {"PROG2": prog2}
    transid_to_program = {"CC01": "PROG2"}
    result = DispatchResult(
        kind=DispatchKind.RETURN_TRANSID, transid="CC01    ", commarea=None
    )
    out = _advance_routing(result, "CC00", program_cache, transid_to_program)
    assert out == ("CC01", prog2, b"")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_advance_routing_return_transid_unknown_abends_trni():
    """An unknown RETURN TRANSID target abends TRNI (terminal)."""
    result = DispatchResult(kind=DispatchKind.RETURN_TRANSID, transid="ZZZZ")
    out = _advance_routing(result, "CC00", {}, {"CC00": "PROG1"})
    assert isinstance(out, DispatchResult)
    assert out.kind == DispatchKind.ABEND
    assert out.abcode == "TRNI"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_advance_routing_xctl_carries_transid():
    """XCTL switches program but the transid CARRIES (same task)."""
    prog2 = object()
    program_cache = {"PROG1": object(), "COMEN01C": prog2}
    result = DispatchResult(kind=DispatchKind.XCTL, program="COMEN01C", commarea=b"X")
    out = _advance_routing(result, "CC00", program_cache, {})
    assert out == ("CC00", prog2, b"X")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_advance_routing_xctl_unknown_abends_pgmi():
    """An XCTL to an unknown program abends PGMI (terminal)."""
    result = DispatchResult(kind=DispatchKind.XCTL, program="NOPE")
    out = _advance_routing(result, "CC00", {}, {})
    assert isinstance(out, DispatchResult)
    assert out.kind == DispatchKind.ABEND
    assert out.abcode == "PGMI"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_advance_routing_return_is_terminal():
    """A plain RETURN (or any other kind) is returned unchanged (terminal)."""
    result = DispatchResult(kind=DispatchKind.RETURN)
    out = _advance_routing(result, "CC00", {}, {})
    assert out is result


# ─────────────────────────────────────────────────────────────────────────────
# CicsRegion — turn-by-turn dispatch API. Driven here with a monkeypatched
# run_cics returning scripted DispatchResults so we test the routing/advance
# state machine in isolation.
# ─────────────────────────────────────────────────────────────────────────────


def _region(program_cache, transid_to_program):
    return CicsRegion(
        program_cache,
        transid_to_program,
        queue.Queue(),
        queue.Queue(),
        context_holder=[None],
        result_holder=[None],
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_region_start_dispatches_entry_program(monkeypatch):
    seen = []

    def fake_run(program, ctx, sq, iq, **kw):
        seen.append((program, ctx.transid, ctx.eibaid))
        return DispatchResult(kind=DispatchKind.RETURN)

    monkeypatch.setattr(dispatcher_mod, "run_cics", fake_run)
    p1 = object()
    region = _region({"PROG1": p1}, {"CC00": "PROG1"})
    r = region.start("CC00", input_event=InputEvent(eibaid="\x7d", fields={}))
    assert seen == [(p1, "CC00", "\x7d")]
    assert r.kind == DispatchKind.RETURN
    assert region.done is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_region_xctl_carries_transid_and_runs_next_program_with_no_input(
    monkeypatch,
):
    """After an XCTL, step() runs the XCTL'd program under the SAME transid with
    no new terminal input (same task)."""
    signon, menu = object(), object()
    seen = []
    scripted = [
        DispatchResult(kind=DispatchKind.XCTL, program="COMEN01C", commarea=b"C1"),
        DispatchResult(
            kind=DispatchKind.RETURN_TRANSID, transid="CM00", commarea=b"C2"
        ),
    ]

    def fake_run(program, ctx, sq, iq, **kw):
        seen.append((program, ctx.transid, ctx.commarea, ctx.eibaid))
        return scripted[len(seen) - 1]

    monkeypatch.setattr(dispatcher_mod, "run_cics", fake_run)
    region = _region(
        {"COSGN00C": signon, "COMEN01C": menu}, {"CC00": "COSGN00C", "CM00": "COMEN01C"}
    )
    r1 = region.start("CC00", commarea=b"INIT", input_event=InputEvent(eibaid="\x7d"))
    assert r1.kind == DispatchKind.XCTL
    assert region.transid == "CC00"  # transid carries on XCTL
    assert region.done is False

    r2 = region.step()  # no input_event after XCTL
    # menu ran under transid CC00 (carried), commarea from the XCTL, eibaid carried.
    assert seen[1] == (menu, "CC00", b"C1", "\x7d")
    assert r2.kind == DispatchKind.RETURN_TRANSID


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_region_return_transid_then_step_with_fresh_input(monkeypatch):
    """After RETURN TRANSID, the next program comes from the CSD map, the transid
    is the returned one, and a fresh terminal input is supplied to step()."""
    menu, acct = object(), object()
    seen = []
    scripted = [
        DispatchResult(kind=DispatchKind.RETURN_TRANSID, transid="CM00", commarea=b"M"),
        DispatchResult(kind=DispatchKind.RETURN),
    ]

    def fake_run(program, ctx, sq, iq, **kw):
        seen.append((program, ctx.transid, ctx.commarea, ctx.eibaid))
        return scripted[len(seen) - 1]

    monkeypatch.setattr(dispatcher_mod, "run_cics", fake_run)
    region = _region(
        {"COMEN01C": menu, "COACTVWC": acct},
        {"CM00": "COMEN01C", "CAVW": "COACTVWC"},
    )
    # Pretend the first program already RETURN TRANSID'd to CM00 -> but to test the
    # RETURN_TRANSID branch we start on CM00 (menu) which returns RETURN_TRANSID CM00.
    r1 = region.start("CM00", input_event=InputEvent(eibaid="\x7d"))
    assert r1.kind == DispatchKind.RETURN_TRANSID
    assert region.transid == "CM00"
    assert region.done is False
    # The CSD map says CM00 -> COMEN01C, so the next program is the menu again.
    r2 = region.step(input_event=InputEvent(eibaid="\xf3", fields={"OPTION": "01"}))
    assert seen[1][0] is menu  # CM00 -> COMEN01C via map
    assert seen[1][1] == "CM00"
    assert seen[1][2] == b"M"  # commarea carried from the RETURN TRANSID
    assert seen[1][3] == "\xf3"  # fresh input event's aid
    assert r2.kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_region_input_event_is_put_on_queue_for_receive_map(monkeypatch):
    """When an input_event is supplied, it is put on the input_queue so the
    program's RECEIVE MAP can consume it."""
    drained = []

    def fake_run(program, ctx, sq, iq, **kw):
        drained.append(iq.get(block=False))
        return DispatchResult(kind=DispatchKind.RETURN)

    monkeypatch.setattr(dispatcher_mod, "run_cics", fake_run)
    region = _region({"PROG1": object()}, {"CC00": "PROG1"})
    ev = InputEvent(eibaid="\x7d", fields={"USERID": "U"})
    region.start("CC00", input_event=ev)
    assert drained == [ev]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_region_step_raises_when_done(monkeypatch):
    def fake_run(program, ctx, sq, iq, **kw):
        return DispatchResult(kind=DispatchKind.RETURN)

    monkeypatch.setattr(dispatcher_mod, "run_cics", fake_run)
    region = _region({"PROG1": object()}, {"CC00": "PROG1"})
    region.start("CC00", input_event=InputEvent())
    assert region.done is True
    try:
        region.step()
        assert False, "step() after terminal should raise"
    except RuntimeError:
        pass


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd(tmp_path):
    csd = tmp_path / "carddemo.csd"
    csd.write_text(
        "DEFINE TRANSACTION(CC00) PROGRAM(COSGN00C)\n"
        "DEFINE TRANSACTION(CC01) PROGRAM(COMEN01C)\n"
    )
    mapping = parse_csd(csd)
    assert mapping["CC00"] == "COSGN00C"
    assert mapping["CC01"] == "COMEN01C"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd_attribute_order_independent(tmp_path):
    # Real CSD: TRANSACTION and PROGRAM are not adjacent — other attributes sit
    # between them, possibly on continuation lines. The structural parse extracts
    # the pair regardless of order/position (the old regex required adjacency).
    csd = tmp_path / "region.csd"
    csd.write_text(
        "DEFINE TRANSACTION(CC00) GROUP(CARDDEMO)\n"
        "       PROGRAM(COSGN00C) TASKDATALOC(ANY)\n"
    )
    mapping = parse_csd(csd)
    assert mapping["CC00"] == "COSGN00C"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd_ignores_unrelated_defines(tmp_path):
    # A fuller CSD interleaves FILE/PROGRAM definitions (many attributes, values
    # with spaces/slashes) and TRANSACTION definitions without a PROGRAM. Only
    # TRANSACTION-with-PROGRAM yields a mapping; the rest are skipped.
    csd = tmp_path / "full.csd"
    csd.write_text(
        " DEFINE FILE(ACCTDAT) GROUP(CARDDEMO)\n"
        "        DSNAME(AWS.M2.CARDDEMO.ACCTDATA) DEFINETIME(22/05/13 12:56:44)\n"
        " DEFINE PROGRAM(COMEN01C) GROUP(CARDDEMO)\n"
        " DEFINE TRANSACTION(CAVW) GROUP(CARDDEMO)\n"
        " DEFINE TRANSACTION(CM00) PROGRAM(COMEN01C) GROUP(CARDDEMO)\n"
    )
    mapping = parse_csd(csd)
    assert mapping == {"CM00": "COMEN01C"}  # CAVW (no PROGRAM), FILE, PROGRAM skipped


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd_files(tmp_path):
    csd = tmp_path / "region.csd"
    csd.write_text(
        " DEFINE FILE(ACCTDAT) GROUP(CARDDEMO)\n"
        "        DSNAME(AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS) STATUS(ENABLED)\n"
        " DEFINE FILE(CUSTDAT) GROUP(CARDDEMO)\n"
        "        DSNAME(AWS.M2.CARDDEMO.CUSTDATA.VSAM.KSDS) STATUS(ENABLED)\n"
    )
    mapping = parse_csd_files(csd)
    assert mapping["ACCTDAT"] == "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"
    assert mapping["CUSTDAT"] == "AWS.M2.CARDDEMO.CUSTDATA.VSAM.KSDS"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd_files_ignores_defines_without_dsname(tmp_path):
    # A DEFINE FILE without DSNAME (rare, but the grammar allows an
    # attribute with no value) and DEFINE TRANSACTION/PROGRAM entries are
    # both skipped — only FILE-with-DSNAME contributes a mapping.
    csd = tmp_path / "region.csd"
    csd.write_text(
        " DEFINE FILE(NODSN) GROUP(CARDDEMO)\n"
        " DEFINE FILE(ACCTDAT) GROUP(CARDDEMO)\n"
        "        DSNAME(AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS)\n"
        " DEFINE TRANSACTION(CM00) PROGRAM(COMEN01C) GROUP(CARDDEMO)\n"
    )
    mapping = parse_csd_files(csd)
    assert mapping == {"ACCTDAT": "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd_raises_csd_parse_error_on_a_csd_that_does_not_parse(tmp_path):
    # A CSD that does not parse is corpus shape, not a bug in cicada, and the
    # caller is run_cics's bootstrap. Without a wrapper it can only tell the two
    # apart by importing lark itself and catching UnexpectedInput -- so the
    # failure it actually gets is a lark internal leaking out of the VM.
    csd = tmp_path / "broken.csd"
    csd.write_text("DEFINE TRANSACTION(CC00\n")

    with pytest.raises(CsdParseError):
        parse_csd(csd)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_csd_files_raises_csd_parse_error_on_a_csd_that_does_not_parse(tmp_path):
    csd = tmp_path / "broken.csd"
    csd.write_text("DEFINE FILE(ACCTDAT) DSNAME(\n")

    with pytest.raises(CsdParseError):
        parse_csd_files(csd)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_csd_parse_error_keeps_the_lark_failure_as_its_cause(tmp_path):
    # The wrapper narrows what callers must catch; it must not cost whoever is
    # diagnosing the CSD the position lark found the problem at.
    csd = tmp_path / "broken.csd"
    csd.write_text("DEFINE TRANSACTION(CC00\n")

    with pytest.raises(CsdParseError) as excinfo:
        parse_csd(csd)

    assert excinfo.value.__cause__ is not None


# ─────────────────────────────────────────────────────────────────────────────
# _run_dispatcher_with_runner + interval control — a started task needs no
# terminal input, so the blocking loop must dispatch it BEFORE it waits.
# ─────────────────────────────────────────────────────────────────────────────

_REAL_PEEK = dispatcher_mod._peek_input_event


def _logged_bounded_peek(monkeypatch, log):
    """Log every terminal wait, and bound it so a scheduling regression fails in
    milliseconds instead of hanging the suite for the production 30s timeout."""

    def fake_peek(input_queue, timeout=30.0):
        log.append("peek")
        return _REAL_PEEK(input_queue, timeout=0.05)

    monkeypatch.setattr(dispatcher_mod, "_peek_input_event", fake_peek)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_runs_a_started_task_without_waiting_for_terminal_input(monkeypatch):
    """A START issued by a task that then RETURNs runs on this driver, and runs
    without any terminal input — its data comes from RETRIEVE."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        if ctx.transid == "SRTA":
            start_queue.queue(StartRequest(transid="SRTB", termid="T001"))
        return DispatchResult(kind=DispatchKind.RETURN)

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTA": MagicMock(), "STARTB": MagicMock()},
        {"SRTA": "STARTA", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
    )

    assert log == ["run:SRTA", "run:SRTB"]
    assert result.kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_runs_a_started_task_before_a_parked_next_transid(monkeypatch):
    """A pending start runs BEFORE the RETURN TRANSID target — the peek that
    target needs would otherwise strand the started task behind terminal input
    nobody sends. The parked next-transid still runs afterwards."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        if ctx.transid == "SRTA":
            start_queue.queue(StartRequest(transid="SRTB", termid="T001"))
            return DispatchResult(
                kind=DispatchKind.RETURN_TRANSID, transid="CC01", commarea=b"NEXT"
            )
        return DispatchResult(kind=DispatchKind.RETURN)

    iq: queue.Queue = queue.Queue()
    iq.put(InputEvent(eibaid="\xf3", fields={}))

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTA": MagicMock(), "STARTB": MagicMock(), "PROG2": MagicMock()},
        {"SRTA": "STARTA", "SRTB": "STARTB", "CC01": "PROG2"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        iq,
        start_queue=start_queue,
        region_termid="T001",
    )

    assert log == ["run:SRTA", "run:SRTB", "peek", "run:CC01"]
    assert result.kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_started_task_gets_start_data_no_commarea_and_the_start_termid(
    monkeypatch,
):
    """The started task is dispatched with EIBCALEN 0, the terminal the START
    named, and its data in the queue's slot for RETRIEVE."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)
    seen: dict[str, object] = {}

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        if ctx.transid == "SRTA":
            start_queue.queue(
                StartRequest(transid="SRTB", data=b"PAYLOAD", termid="T009")
            )
            return DispatchResult(kind=DispatchKind.RETURN)
        seen["commarea"] = ctx.commarea
        seen["termid"] = ctx.termid
        seen["data"] = start_queue.take_start_data()
        return DispatchResult(kind=DispatchKind.RETURN)

    _run_dispatcher_with_runner(
        mock_run,
        {"STARTA": MagicMock(), "STARTB": MagicMock()},
        {"SRTA": "STARTA", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"OLD", eibaid="\x7d", termid="T009"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T009",
    )

    assert log == ["run:SRTA", "run:SRTB"]
    assert seen["commarea"] == b""
    assert seen["termid"] == "T009"
    assert seen["data"] == (b"PAYLOAD",)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_xctl_does_not_dispatch_a_pending_start(monkeypatch):
    """An XCTL transfers control within the SAME task, so it is not a task end
    and must not let a started task in ahead of the XCTL'd program."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)
    prog1, prog2 = MagicMock(), MagicMock()
    ran_programs: list[str] = []

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        ran_programs.append("PROG1" if program is prog1 else "OTHER")
        if program is prog1:
            start_queue.queue(StartRequest(transid="SRTB", termid="T001"))
            return DispatchResult(kind=DispatchKind.XCTL, program="PROG2", commarea=b"")
        return DispatchResult(kind=DispatchKind.RETURN)

    result = _run_dispatcher_with_runner(
        mock_run,
        {"PROG1": prog1, "PROG2": prog2, "STARTB": MagicMock()},
        {"SRTA": "PROG1", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
    )

    assert log == ["run:SRTA", "run:SRTA", "run:SRTB"]
    assert ran_programs == ["PROG1", "OTHER", "OTHER"]
    assert result.kind == DispatchKind.RETURN


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_abend_discards_pending_starts(monkeypatch):
    """START is recoverable: an abending task's pending starts back out with it."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        start_queue.queue(StartRequest(transid="SRTB", termid="T001"))
        return DispatchResult(kind=DispatchKind.ABEND, abcode="ASRA")

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTA": MagicMock(), "STARTB": MagicMock()},
        {"SRTA": "STARTA", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
    )

    assert log == ["run:SRTA"]
    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "ASRA"
    assert start_queue.pending == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_runaway_started_tasks_abend_astl(monkeypatch):
    """A transaction that STARTs itself never waits for terminal input, so this
    blocking driver has nothing to break the cycle — the same runaway guard the
    region has must stop it rather than spin forever."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        start_queue.queue(StartRequest(transid="SRTL", termid="T001"))
        return DispatchResult(kind=DispatchKind.RETURN)

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTLP": MagicMock()},
        {"SRTL": "STARTLP"},
        CicsContext(transid="SRTL", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
        max_consecutive_starts=3,
    )

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "ASTL"
    # The cap counts started tasks ADOPTED; the entry task is not one, and the
    # adoption that would exceed the cap is refused instead of dispatched.
    assert log == ["run:SRTL"] * 4
    assert start_queue.pending == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_next_transid_turn_resets_the_runaway_guard(monkeypatch):
    """Interleaving started tasks with next-transid turns is legitimate work:
    the terminal input each next-transid turn waits for breaks the chain, so the
    guard must not fire however long the region runs."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)
    cycles = [0]

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        if ctx.transid == "SRTB":
            return DispatchResult(kind=DispatchKind.RETURN)
        cycles[0] = cycles[0] + 1
        if cycles[0] > 6:
            return DispatchResult(kind=DispatchKind.RETURN)
        start_queue.queue(StartRequest(transid="SRTB", termid="T001"))
        return DispatchResult(
            kind=DispatchKind.RETURN_TRANSID, transid="SRTA", commarea=b""
        )

    iq: queue.Queue = queue.Queue()
    iq.put(InputEvent(eibaid="\x7d", fields={}))

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTA": MagicMock(), "STARTB": MagicMock()},
        {"SRTA": "STARTA", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        iq,
        start_queue=start_queue,
        region_termid="T001",
        max_consecutive_starts=2,
    )

    assert result.kind == DispatchKind.RETURN
    assert log == ["run:SRTA", "run:SRTB", "peek"] * 6 + ["run:SRTA"]
    assert cycles[0] == 7


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_start_for_another_terminal_never_runs(monkeypatch):
    """A START naming a terminal this region does not emulate stays pending —
    the region has no channel for it — and must not be dispatched here."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)
    elsewhere = StartRequest(transid="SRTB", termid="T099")

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        start_queue.queue(elsewhere)
        return DispatchResult(kind=DispatchKind.RETURN)

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTA": MagicMock(), "STARTB": MagicMock()},
        {"SRTA": "STARTA", "SRTB": "STARTB"},
        CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
    )

    assert log == ["run:SRTA"]
    assert result.kind == DispatchKind.RETURN
    assert start_queue.pending == (elsewhere,)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_given_no_start_queue_makes_its_own():
    """The default is an identity sentinel, not a ``StartQueue()`` evaluated once
    at def time: the loop must drain a queue of its own, so a request sitting on
    the shared sentinel is never scheduled by anybody."""
    from cics.interval import StartRequest

    stray = StartRequest(transid="SRTB", termid="T001")
    ran: list[str] = []

    def mock_run(program, ctx, sq, iq):
        ran.append(ctx.transid)
        return DispatchResult(kind=DispatchKind.RETURN)

    dispatcher_mod._OWN_START_QUEUE.queue(stray)
    try:
        result = _run_dispatcher_with_runner(
            mock_run,
            {"STARTA": MagicMock(), "STARTB": MagicMock()},
            {"SRTA": "STARTA", "SRTB": "STARTB"},
            CicsContext(transid="SRTA", commarea=b"", eibaid="\x7d", termid="T001"),
            queue.Queue(),
            queue.Queue(),
        )

        assert ran == ["SRTA"]
        assert result.kind == DispatchKind.RETURN
        assert dispatcher_mod._OWN_START_QUEUE.pending == (stray,)
    finally:
        # The sentinel is process-wide: leaving `stray` on it after a failing
        # assert would corrupt every later test in the session.
        dispatcher_mod._OWN_START_QUEUE.discard_for_abend()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_start_xctl_cycle_hits_the_runaway_guard(monkeypatch):
    """Guard evasion case, the loop's copy of the region's
    test_a_start_xctl_cycle_hits_the_runaway_guard: an XCTL is a transfer within
    the same task and waits for no terminal input, so it must NOT reset the
    count. Only the terminal wait on a next-transid turn does."""
    from cics.interval import StartQueue, StartRequest

    start_queue = StartQueue()
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)
    startlx, xctlend = MagicMock(), MagicMock()

    def mock_run(program, ctx, sq, iq):
        if len(log) > 20:
            # Without a bound, a reset moved above the XCTL branch's `continue`
            # would spin here forever instead of failing.
            raise AssertionError(f"runaway guard never fired: {log}")
        if program is startlx:
            log.append("run:STARTLX")
            start_queue.queue(StartRequest(transid="SRTL", termid="T001"))
            return DispatchResult(
                kind=DispatchKind.XCTL, program="XCTLEND", commarea=b""
            )
        log.append("run:XCTLEND")
        return DispatchResult(kind=DispatchKind.RETURN)

    result = _run_dispatcher_with_runner(
        mock_run,
        {"STARTLX": startlx, "XCTLEND": xctlend},
        {"SRTL": "STARTLX"},
        CicsContext(transid="SRTL", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
        start_queue=start_queue,
        region_termid="T001",
        max_consecutive_starts=2,
    )

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "ASTL"
    # Two runs per cycle — STARTLX's XCTL, then XCTLEND's RETURN — with the
    # entry task's own cycle preceding the first adoption, so the cap-th
    # adoption is refused on the (cap + 1)-th cycle.
    assert log == ["run:STARTLX", "run:XCTLEND"] * 3
    assert start_queue.pending == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_loop_unknown_return_transid_abends_trni_without_waiting(monkeypatch):
    """Routing is resolved before the terminal wait, so an unknown RETURN TRANSID
    target abends TRNI immediately instead of burning the 30s peek and reporting
    the AZCT read-time-out for what is really a CSD error."""
    log: list[str] = []
    _logged_bounded_peek(monkeypatch, log)

    def mock_run(program, ctx, sq, iq):
        log.append(f"run:{ctx.transid}")
        return DispatchResult(kind=DispatchKind.RETURN_TRANSID, transid="ZZZZ")

    result = _run_dispatcher_with_runner(
        mock_run,
        {"PROG1": MagicMock()},
        {"CC00": "PROG1"},
        CicsContext(transid="CC00", commarea=b"", eibaid="\x7d", termid="T001"),
        queue.Queue(),
        queue.Queue(),
    )

    assert result.kind == DispatchKind.ABEND
    assert result.abcode == "TRNI"
    assert log == ["run:CC00"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_production_runaway_cap_is_256_on_both_drivers():
    """The tests above lower ``max_consecutive_starts`` to 2-3 so proving the
    guard fires (and resets) costs a handful of runs, not hundreds — but that
    means nothing exercises the real production default. A typo shrinking
    ``_MAX_CONSECUTIVE_STARTS`` would fail no test; pin the constant each driver
    actually defaults to."""
    assert dispatcher_mod._MAX_CONSECUTIVE_STARTS == 256

    loop_default = (
        inspect.signature(_run_dispatcher_with_runner)
        .parameters["max_consecutive_starts"]
        .default
    )
    assert loop_default == 256

    region_default = (
        inspect.signature(CicsRegion.__init__)
        .parameters["max_consecutive_starts"]
        .default
    )
    assert region_default == 256
