"""Unit: StartQueue — FIFO, terminal routing, and the record of what was refused."""

from __future__ import annotations

from cics.interval import RejectReason, StartQueue, StartRequest


def test_pop_runnable_returns_matching_terminal_request_fifo():
    q = StartQueue()
    q.queue(StartRequest(transid="SRTB", data=b"first", termid="T001"))
    q.queue(StartRequest(transid="SRTC", data=b"second", termid="T001"))

    assert q.pop_runnable("T001") == (
        StartRequest(transid="SRTB", data=b"first", termid="T001"),
    )
    assert q.pop_runnable("T001") == (
        StartRequest(transid="SRTC", data=b"second", termid="T001"),
    )
    assert q.pop_runnable("T001") == ()


def test_pop_runnable_returns_non_terminal_request():
    """No TERMID means a non-terminal task, which is still runnable."""
    q = StartQueue()
    q.queue(StartRequest(transid="SRTD", termid=""))

    assert q.pop_runnable("T001") == (StartRequest(transid="SRTD", termid=""),)


def test_pop_runnable_skips_another_terminals_request():
    q = StartQueue()
    q.queue(StartRequest(transid="PRNT", termid="P001"))
    q.queue(StartRequest(transid="SRTB", termid="T001"))

    assert q.pop_runnable("T001") == (StartRequest(transid="SRTB", termid="T001"),)
    assert q.pending == (StartRequest(transid="PRNT", termid="P001"),)


def test_start_data_is_consumed_once():
    q = StartQueue()
    q.put_start_data(b"payload")

    assert q.take_start_data() == (b"payload",)
    assert q.take_start_data() == ()


def test_take_start_data_is_empty_for_a_task_nobody_started():
    assert StartQueue().take_start_data() == ()


def test_rejected_records_the_reason_and_does_not_queue():
    q = StartQueue()
    req = StartRequest(transid="ZZZZ", termid="T001")
    q.reject(req, RejectReason.UNKNOWN_TRANSID)

    assert q.pending == ()
    assert q.rejected == ((req, RejectReason.UNKNOWN_TRANSID),)


def test_ignored_delays_records_every_queued_request_carrying_timing():
    q = StartQueue()
    timed = StartRequest(transid="SRTB", termid="T001", timing_text="000005")
    q.queue(timed)
    q.queue(StartRequest(transid="SRTC", termid="T001"))

    assert q.ignored_delays == (timed,)


def test_discard_for_abend_clears_pending_but_keeps_the_record():
    q = StartQueue()
    timed = StartRequest(transid="SRTB", termid="T001", timing_text="000005")
    q.queue(timed)
    q.reject(StartRequest(transid="ZZZZ"), RejectReason.UNKNOWN_TRANSID)

    q.discard_for_abend()

    assert q.pending == ()
    assert len(q.rejected) == 1
    assert q.ignored_delays == (timed,)


def test_peek_does_not_remove():
    q = StartQueue()
    req = StartRequest(transid="SRTB", termid="T001")
    q.queue(req)

    assert q.pop_runnable_peek("T001") == (req,)
    assert q.pending == (req,)


def test_peek_is_empty_when_only_another_terminals_request_is_pending():
    q = StartQueue()
    q.queue(StartRequest(transid="SRTB", termid="T002"))

    assert q.pop_runnable_peek("T001") == ()
