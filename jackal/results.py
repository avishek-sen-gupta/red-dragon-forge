"""Execution results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepResult:
    name: str
    return_code: int
    ran: bool


@dataclass(frozen=True)
class JobResult:
    steps: tuple[StepResult, ...]
