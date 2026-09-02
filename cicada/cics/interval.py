"""CICS interval control — the region's queue of START requests.

A START asks CICS to run a transaction as a separate task while the issuing task
carries on. This module holds the requests and the record of the ones the region
could not honour; scheduling lives in the dispatcher drivers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class StartRequest:
    """One EXEC CICS START. ``termid`` is "" for a non-terminal task (no TERMID
    coded), which is a distinct case from a START naming another terminal."""

    transid: str
    data: bytes = b""
    termid: str = ""
    reqid: str = ""
    timing_text: str = ""


class RejectReason(Enum):
    UNKNOWN_TRANSID = "unknown_transid"
    NO_SUCH_TERMINAL = "no_such_terminal"


class StartQueue:
    """FIFO of pending START requests, plus what this region refused or ignored.

    ``rejected`` and ``ignored_delays`` exist so a caller can ASSERT on what the
    runtime could not honour instead of reading logs for it (forge-p9t).
    """

    def __init__(self) -> None:
        self._pending: tuple[StartRequest, ...] = ()
        self._rejected: tuple[tuple[StartRequest, RejectReason], ...] = ()
        self._ignored_delays: tuple[StartRequest, ...] = ()
        self._start_data: tuple[bytes, ...] = ()

    def queue(self, req: StartRequest) -> None:
        self._pending = (*self._pending, req)
        if req.timing_text:
            self._ignored_delays = (*self._ignored_delays, req)

    def reject(self, req: StartRequest, reason: RejectReason) -> None:
        self._rejected = (*self._rejected, (req, reason))

    def pop_runnable(self, region_termid: str) -> tuple[StartRequest, ...]:
        """The first request this region can run, removed. Empty when there is none.

        Runnable means the request names this region's terminal, or names no
        terminal at all (a non-terminal task). One naming another terminal stays
        pending forever — this region has no channel for it.
        """
        runnable = [req for req in self._pending if req.termid in ("", region_termid)]
        if not runnable:
            return ()
        taken = runnable[0]
        index = self._pending.index(taken)
        self._pending = self._pending[:index] + self._pending[index + 1 :]
        return (taken,)

    def pop_runnable_peek(self, region_termid: str) -> tuple[StartRequest, ...]:
        """Like pop_runnable, without removing — a driver has to know whether a
        start will run before it decides what to do with a next-transid."""
        runnable = [req for req in self._pending if req.termid in ("", region_termid)]
        return (runnable[0],) if runnable else ()

    def put_start_data(self, data: bytes) -> None:
        self._start_data = (data,)

    def take_start_data(self) -> tuple[bytes, ...]:
        """The started task's data, consumed. Empty for a task nobody started."""
        taken = self._start_data
        self._start_data = ()
        return taken

    def discard_for_abend(self) -> None:
        """START requests are recoverable in CICS and back out with the unit of
        work. The rejected/ignored records are history, not pending work, and stay."""
        self._pending = ()
        self._start_data = ()

    @property
    def pending(self) -> tuple[StartRequest, ...]:
        return self._pending

    @property
    def rejected(self) -> tuple[tuple[StartRequest, RejectReason], ...]:
        return self._rejected

    @property
    def ignored_delays(self) -> tuple[StartRequest, ...]:
        return self._ignored_delays
