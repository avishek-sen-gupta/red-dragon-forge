"""One fact of a jumps.jsonl row, as far as resolved sites read it."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class JumpFactRow(BaseModel):
    """The values a jump's operand can hold, and why there may be others."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    values: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
