"""
squall.connector
~~~~~~~~~~~~~~~~~
DbConnector — resolves which connection (if any) should become current,
against the connection registry passed in at call time.

One abstraction covers two cases that were previously two code paths:
* the implicit pre-run connection a CICS Db2-attached program starts with
  (the attachment facility establishes the thread before the program's first
  SQL statement; the program itself never issues EXEC SQL CONNECT), and
* EXEC SQL CONNECT TO / SET CONNECTION's own name -> backend resolution.

``NullDbConnector`` is the null-object default: a run starts disconnected
unless a caller supplies a ``NamedDbConnector``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, runtime_checkable

from squall.backend import SqlBackend


@runtime_checkable
class DbConnector(Protocol):
    def connect(self, connections: Mapping[str, SqlBackend]) -> SqlBackend | None: ...


@dataclass(frozen=True)
class NullDbConnector:
    """Null object: never resolves a connection — the faithful disconnected-start
    default for a program that issues its own EXEC SQL CONNECT."""

    def connect(self, connections: Mapping[str, SqlBackend]) -> SqlBackend | None:
        return None


@dataclass(frozen=True)
class NamedDbConnector:
    """Resolves ``name`` against the connection registry passed to ``connect``.

    Used both for the implicit pre-run connection (CICS Db2 attachment facility)
    and by EXEC SQL CONNECT TO / SET CONNECTION's own handlers — one resolution
    path, not two.
    """

    name: str

    def connect(self, connections: Mapping[str, SqlBackend]) -> SqlBackend | None:
        return connections.get(self.name)
