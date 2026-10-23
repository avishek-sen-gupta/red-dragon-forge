"""One line of the fixpoint's defs.jsonl, as the matrix stage reads it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DefLine(BaseModel):
    """A byte range read at a node, and the nodes whose writes may reach it."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    program: str
    node: str
    extent: str
    definers: tuple[str, ...]
