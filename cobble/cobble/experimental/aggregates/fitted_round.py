"""One decompose round as it ran: its step, the columns it kept, the matrix it factored, its factors and its result."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from cobble.experimental.aggregates.round_result import RoundResult
from cobble.experimental.aggregates.round_step import RoundStep
from numpy.typing import NDArray
from scipy.sparse import csr_matrix


@dataclass(frozen=True)
class FittedRound:
    """The round's step and result, the matrix columns it kept, what it factored after earlier rounds, and its paragraph and field loadings."""

    step: RoundStep
    keep: NDArray[np.int64]
    residual: csr_matrix
    used: NDArray[np.float64]
    made_of: NDArray[np.float64]
    result: RoundResult
