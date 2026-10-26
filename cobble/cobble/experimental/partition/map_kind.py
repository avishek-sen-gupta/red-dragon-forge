"""What a node of the program map stands for."""

from __future__ import annotations

from enum import StrEnum


class MapKind(StrEnum):
    """A program, or a dataset record its slots belong to."""

    PROGRAM = "program"
    DATASET = "dataset"
