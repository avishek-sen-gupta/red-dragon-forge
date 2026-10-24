"""One round's outcome, as rounds.json stores it."""

from __future__ import annotations

from cobble.experimental.aggregates.k_result import KResult
from pydantic import BaseModel, ConfigDict


class RoundResult(BaseModel):
    """The round's threshold, the share of its matrix that earlier rounds already explained, and its fit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_occurrences: int
    explained_by_earlier: float
    fit: KResult
