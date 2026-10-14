"""A CICS file read that returned no record: only the EIBRESP saying why."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoRecord:
    resp: int
