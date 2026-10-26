"""One decompose round's scorecard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoundScore:
    """The round's threshold and k; held-out AUC; relative reconstruction error; share of entries inside some factor's top block; matched-factor similarity across subsampled refits; largest similarity between two factors; median share of a factor's loading in its top fields; share of factors whose top fields span programs, and the median programs they span; and the classes' share of the round's entries."""

    min_occurrences: int
    k: int
    auc: float
    fidelity: float
    coverage: float
    stability: float
    distinctness: float
    focus: float
    reach: float
    programs: float
    class_share: float
