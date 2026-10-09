"""Driving a CICS region one terminal turn at a time.

A turn runs until the region waits on the terminal or the task ends, and hands
back every screen sent on the way. Headless tests and the TN3270 session drive a
region through this one protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cics.dispatcher import CicsRegion, InputEvent
from cics.screen.channel import drain_screens
from cics.screen.payload import ScreenPayload
from cics.terminal import ScreenChannel
from cics.types import DispatchKind, DispatchResult

Screens = tuple[ScreenPayload, ...]


@dataclass(frozen=True)
class Returned:
    pass


@dataclass(frozen=True)
class Abended:
    abcode: str


Outcome = Returned | Abended


@dataclass(frozen=True)
class AwaitingInput:
    screens: Screens


@dataclass(frozen=True)
class Ended:
    screens: Screens
    outcome: Outcome


Turn = AwaitingInput | Ended


class RegionDriver(Protocol):
    def knows(self, transid: str) -> bool: ...

    def start(self, transid: str) -> Turn: ...

    def respond(self, event: InputEvent) -> Turn: ...


def _outcome(result: DispatchResult) -> Outcome:
    if result.kind is DispatchKind.ABEND:
        return Abended(result.abcode if result.abcode else "")
    return Returned()


def _finished(result: DispatchResult, screens: Screens) -> Turn:
    if result.kind is DispatchKind.RETURN_TRANSID:
        return AwaitingInput(screens)
    return Ended(screens, _outcome(result))


@dataclass(frozen=True)
class PseudoConversationalDriver:
    """XCTL continues the task with no terminal input; RETURN TRANSID waits for
    the terminal; RETURN or an abend ends the task -- UNLESS the ending task's
    own RETURN (not RETURN TRANSID) also had a START queued for this same
    terminal: ``CicsRegion._settle_terminal`` silently adopts it (position
    advances, ``region.done`` stays False) without changing ``result.kind``
    away from RETURN, so a RETURN alone is not sufficient to tell "truly
    idle" apart from "a freshly adopted task is positioned and ready, same
    as an XCTL, needing no terminal input before its first step." Confirmed
    by reproducing it directly against a real multi-program COBOL/CICS
    region served over TN3270: a program's ``EXEC CICS START
    TRANSID('XXXX') ... EXEC CICS RETURN`` adopted the started transaction
    (``region.transid`` changed, ``region.done`` stayed False) while this
    method, checking only ``result.kind is XCTL``, still called
    ``_finished`` and reported `Ended` -- which the TN3270 session layer
    (``session.py``'s ``_after``) then reads as "no longer in a task," so
    the NEXT physical keystroke gets treated as a fresh transid typed on a
    blank screen instead of continuing the adopted task, and the operator's
    screen goes blank. ``region.done`` (true only once
    ``CicsRegion._terminate`` actually runs -- never set by ``_adopt``/
    ``_adopt_started``/``_adopt_next_transid``) is the authoritative signal,
    checked in addition to ``result.kind``, not instead of it: RETURN_TRANSID
    always stops to await real terminal input regardless of ``done``
    (``_adopt_next_transid`` doesn't set it either), while a RETURN/ABEND
    that leaves ``done`` False means a task was adopted and must run before
    anything goes back to the terminal."""

    region: CicsRegion
    screen_channel: ScreenChannel
    transids: frozenset[str]

    def knows(self, transid: str) -> bool:
        return transid in self.transids

    def start(self, transid: str) -> Turn:
        return self._settle(self.region.start(transid), ())

    def respond(self, event: InputEvent) -> Turn:
        return self._settle(self.region.step(input_event=event), ())

    def _settle(self, result: DispatchResult, earlier: Screens) -> Turn:
        screens = (*earlier, *drain_screens(self.screen_channel))
        continuing = result.kind is DispatchKind.XCTL or (
            result.kind is not DispatchKind.RETURN_TRANSID and not self.region.done
        )
        if continuing:
            return self._settle(self.region.step(), screens)
        return _finished(result, screens)
