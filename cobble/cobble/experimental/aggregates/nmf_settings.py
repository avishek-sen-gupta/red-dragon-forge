"""How every NMF fit runs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NmfSettings:
    """The iteration cap and the random seed of each fit."""

    max_iter: int
    seed: int
