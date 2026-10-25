"""One defs.jsonl row: the statements that could have written an extent by the time a node reads it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReachingRow(BaseModel):
    """A defs row as the fixpoint writes it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    node: str
    extent: str
    definers: tuple[str, ...]
    values: tuple[str, ...]
    reasons: tuple[str, ...]
