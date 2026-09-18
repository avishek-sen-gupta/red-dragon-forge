"""Telnet option negotiation for a basic TN3270 session (RFC 1576).

The server asks for the terminal type, then agrees BINARY and EOR in both
directions. It never offers TN3270E, and refuses any option it did not ask for.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from cics.tn3270.codes import (
    DO,
    DONT,
    IAC,
    OPTION_BINARY,
    OPTION_EOR,
    OPTION_TERMINAL_TYPE,
    SB,
    SE,
    TERMINAL_TYPE_IS,
    TERMINAL_TYPE_SEND,
    WILL,
    WONT,
)


@dataclass(frozen=True)
class Command:
    verb: int
    option: int


@dataclass(frozen=True)
class Subnegotiation:
    option: int
    payload: bytes


TelnetEvent = Command | Subnegotiation


class TelnetPeer(Protocol):
    def send(self, data: bytes) -> None: ...

    def next_event(self) -> TelnetEvent: ...

    def next_record(self) -> bytes:
        """The next 3270 record, or b"" once the peer has disconnected."""
        ...


class UnsupportedTerminal(ConnectionError):
    pass


# Any 3278/3279 works: Erase/Write selects the 24x80 default screen on every model.
_SUPPORTED = re.compile(r"IBM-327[89]-[2-5](-E)?")


@dataclass(frozen=True)
class TerminalType:
    name: str

    @property
    def extended(self) -> bool:
        return self.name.endswith("-E")


_REFUSALS = MappingProxyType({DO: WONT, WILL: DONT})
# What the server offers once it knows the terminal type, and the replies that
# accept it: WILL answers DO, DO answers WILL.
_OFFER = tuple(
    Command(verb, option)
    for option in (OPTION_EOR, OPTION_BINARY)
    for verb in (DO, WILL)
)
_AGREEMENTS = frozenset(Command(WILL if c.verb == DO else DO, c.option) for c in _OFFER)
_DECLINES = frozenset(
    Command(verb, option)
    for verb in (WONT, DONT)
    for option in (OPTION_BINARY, OPTION_EOR, OPTION_TERMINAL_TYPE)
)


def _command(verb: int, option: int) -> bytes:
    return bytes((IAC, verb, option))


def _refuse(peer: TelnetPeer, event: TelnetEvent) -> None:
    reply = _REFUSALS.get(event.verb, 0) if isinstance(event, Command) else 0
    if reply:
        peer.send(_command(reply, event.option))


def _await(peer: TelnetPeer, accepts: Callable[[TelnetEvent], bool]) -> TelnetEvent:
    event = peer.next_event()
    if event in _DECLINES:
        raise UnsupportedTerminal(f"the terminal declined a required option: {event}")
    if accepts(event):
        return event
    _refuse(peer, event)
    return _await(peer, accepts)


def _await_all(peer: TelnetPeer, remaining: frozenset[Command]) -> None:
    if not remaining:
        return
    agreed = _await(peer, remaining.__contains__)
    _await_all(peer, frozenset(c for c in remaining if c != agreed))


def _is_terminal_type_reply(event: TelnetEvent) -> bool:
    return isinstance(event, Subnegotiation) and event.option == OPTION_TERMINAL_TYPE


def _terminal_type(event: TelnetEvent) -> TerminalType:
    payload = event.payload if isinstance(event, Subnegotiation) else b""
    name = (
        payload[1:].decode("ascii").upper()
        if payload[:1] == bytes((TERMINAL_TYPE_IS,))
        else ""
    )
    if not _SUPPORTED.fullmatch(name):
        raise UnsupportedTerminal(
            f"terminal type {name!r} is not a 3278/3279 model 2-5"
        )
    return TerminalType(name)


def negotiate(peer: TelnetPeer) -> TerminalType:
    peer.send(_command(DO, OPTION_TERMINAL_TYPE))
    _await(peer, Command(WILL, OPTION_TERMINAL_TYPE).__eq__)
    peer.send(bytes((IAC, SB, OPTION_TERMINAL_TYPE, TERMINAL_TYPE_SEND, IAC, SE)))
    terminal = _terminal_type(_await(peer, _is_terminal_type_reply))
    peer.send(b"".join(_command(c.verb, c.option) for c in _OFFER))
    _await_all(peer, _AGREEMENTS)
    return terminal
