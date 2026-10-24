"""One NMF run at one k."""

from __future__ import annotations

from cobble.experimental.aggregates.factor import Factor
from pydantic import BaseModel, ConfigDict


class KResult(BaseModel):
    """The factor count, the reconstruction error and iterations it took, and its factors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    k: int
    reconstruction_error: float
    n_iterations: int
    factors: tuple[Factor, ...]
