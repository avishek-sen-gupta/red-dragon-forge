"""One TN3270 connection: paint what the region sends, hand it what the operator
enters, and start transactions typed on an empty screen."""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass
from functools import partial, reduce

from cics.bms.catalog import MapCatalog
from cics.screen.driver import Abended, AwaitingInput, Outcome, RegionDriver, Turn
from cics.screen.terminal_screen import TerminalScreen
from cics.tn3270.codes import frame_record
from cics.tn3270.decoder import Inbound, decode_inbound
from cics.tn3270.encoder import encode_screen
from cics.tn3270.negotiation import TelnetPeer, TerminalType, negotiate


@dataclass(frozen=True)
class Terminal:
    peer: TelnetPeer
    kind: TerminalType
    driver: RegionDriver
    catalog: MapCatalog


@dataclass(frozen=True)
class SessionState:
    screen: TerminalScreen
    in_task: bool


def _paint(terminal: Terminal, state: SessionState) -> SessionState:
    record = encode_screen(state.screen, terminal.kind.extended)
    terminal.peer.send(frame_record(record))
    return state


def _ended_screen(outcome: Outcome, shown: TerminalScreen) -> TerminalScreen:
    if isinstance(outcome, Abended):
        return TerminalScreen(unformatted=f"Transaction abended: {outcome.abcode}")
    return shown


def _after(turn: Turn, shown: TerminalScreen) -> SessionState:
    if isinstance(turn, AwaitingInput):
        return SessionState(shown, in_task=True)
    return SessionState(_ended_screen(turn.outcome, shown), in_task=False)


def _present(terminal: Terminal, screen: TerminalScreen, turn: Turn) -> SessionState:
    shown = reduce(
        lambda s, payload: s.apply_payload(payload, terminal.catalog),
        turn.screens,
        screen,
    )
    return _paint(terminal, _after(turn, shown))


def _first_word(text: str) -> str:
    words = text.split()
    return words[0][:4].upper() if words else ""


def _idle(terminal: Terminal, transid: str) -> SessionState:
    notice = f"Transaction {transid} is not recognized." if transid else ""
    return _paint(terminal, SessionState(TerminalScreen(unformatted=notice), False))


def _start_task(terminal: Terminal, transid: str) -> SessionState:
    if not terminal.driver.knows(transid):
        return _idle(terminal, transid)
    return _present(terminal, TerminalScreen(), terminal.driver.start(transid))


def _continue_task(
    terminal: Terminal, state: SessionState, inbound: Inbound
) -> SessionState:
    event = inbound.event
    typed = state.screen.with_input(event.fields, event.cursor)
    return _present(terminal, typed, terminal.driver.respond(event))


def _on_record(terminal: Terminal, state: SessionState, record: bytes) -> SessionState:
    inbound = decode_inbound(record, state.screen)
    if state.in_task:
        return _continue_task(terminal, state, inbound)
    return _start_task(terminal, _first_word(inbound.unformatted_text))


def run_session(
    peer: TelnetPeer, driver: RegionDriver, catalog: MapCatalog, initial_transid: str
) -> SessionState:
    """Serve one connection until the peer disconnects; returns the last state."""
    terminal = Terminal(peer, negotiate(peer), driver, catalog)
    first = _start_task(terminal, initial_transid)
    records = iter(peer.next_record, b"")
    states = itertools.accumulate(records, partial(_on_record, terminal), initial=first)
    return deque(states, maxlen=1)[0]
