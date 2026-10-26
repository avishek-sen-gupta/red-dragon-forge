"""How much of the matrix the unified classes' columns hold among the fields each threshold admits."""

from __future__ import annotations

from collections.abc import Sequence, Set

import numpy as np
from cobble.experimental.aggregates.matrix import IncidenceMatrix
from cobble.experimental.aggregates.threshold_share import ThresholdShare


def _share(
    found: IncidenceMatrix, classes: Set[str], min_occurrences: int
) -> ThresholdShare:
    entries = np.asarray(found.matrix.sum(axis=0)).ravel()
    admitted = np.array(found.occurrences) >= min_occurrences
    unified = np.array([field in classes for field in found.fields], dtype=bool)
    held = float(entries[admitted].sum())
    return ThresholdShare(
        min_occurrences=min_occurrences,
        columns=int(admitted.sum()),
        class_columns=int((admitted & unified).sum()),
        share=float(entries[admitted & unified].sum()) / held if held else 0.0,
    )


def class_shares(
    found: IncidenceMatrix, classes: Set[str], thresholds: Sequence[int]
) -> tuple[ThresholdShare, ...]:
    return tuple(_share(found, classes, threshold) for threshold in thresholds)
