"""Telnet over blocking sockets: the byte-stream half of the TN3270 adapter.

Excluded from fp-lint (see fp.json): a socket delivers an unframed stream, and
turning it into telnet events and EOR-delimited records needs read buffers filled
in place and an accept loop that runs until the process is stopped.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from cics.tn3270.codes import DO, DONT, EOR, IAC, SB, SE, WILL, WONT
from cics.tn3270.negotiation import (
    Command,
    Subnegotiation,
    TelnetEvent,
    TelnetPeer,
    UnsupportedTerminal,
)

logger = logging.getLogger(__name__)

_VERBS = frozenset({DO, DONT, WILL, WONT})


class ConnectionClosed(ConnectionError):
    pass


@dataclass(frozen=True)
class EndOfRecord:
    pass


Token = int | Command | Subnegotiation | EndOfRecord


def _octets(sock: socket.socket) -> Iterator[int]:
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return
        yield from chunk


def _subnegotiation(octets: Iterator[int]) -> Subnegotiation:
    option = next(octets, 0)
    payload = bytearray()
    for octet in octets:
        if octet != IAC:
            payload.append(octet)
            continue
        following = next(octets, SE)
        if following == SE:
            break
        payload.append(following)
    return Subnegotiation(option, bytes(payload))


def _after_iac(octets: Iterator[int]) -> Iterator[Token]:
    verb = next(octets, SE)
    if verb == IAC:
        yield IAC
    elif verb in _VERBS:
        yield Command(verb, next(octets, 0))
    elif verb == SB:
        yield _subnegotiation(octets)
    elif verb == EOR:
        yield EndOfRecord()


def _tokens(octets: Iterator[int]) -> Iterator[Token]:
    for octet in octets:
        if octet == IAC:
            yield from _after_iac(octets)
        else:
            yield octet


class SocketTelnetPeer:
    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._tokens = _tokens(_octets(sock))

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def next_event(self) -> TelnetEvent:
        for token in self._tokens:
            if isinstance(token, Command | Subnegotiation):
                return token
        raise ConnectionClosed("the terminal disconnected during negotiation")

    def next_record(self) -> bytes:
        record = bytearray()
        for token in self._tokens:
            if isinstance(token, EndOfRecord):
                return bytes(record)
            if isinstance(token, int):
                record.append(token)
        return b""


def bind(host: str, port: int) -> socket.socket:
    return socket.create_server((host, port))


def serve_forever(
    server: socket.socket, handle: Callable[[TelnetPeer], object]
) -> None:
    """Serve one connection at a time. A terminal that disconnects or cannot be
    served ends only its own session."""
    while True:
        conn, peer_address = server.accept()
        with conn:
            try:
                handle(SocketTelnetPeer(conn))
            except (
                ConnectionClosed,
                UnsupportedTerminal,
                OSError,
                LookupError,
                ValueError,
            ) as error:
                logger.warning(
                    "session with %s ended: %s: %s",
                    peer_address,
                    type(error).__name__,
                    error,
                )
