"""Each matrix row's program, and the round's columns each program owns, laid end to end per program."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ProgramColumns:
    """``rows`` is each paragraph row's program index, -1 for a program that owns no column; program ``p``'s columns are ``columns[starts[p] : starts[p] + counts[p]]``."""

    rows: NDArray[np.int64]
    starts: NDArray[np.int64]
    counts: NDArray[np.int64]
    columns: NDArray[np.int64]
