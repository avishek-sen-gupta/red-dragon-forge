"""What a graph node stands for."""

from __future__ import annotations

from enum import StrEnum


class NodeKind(StrEnum):
    """A field's storage, a terminal where bytes enter or leave a program, or a byte slot of a dataset record."""

    FIELD = "field"
    ORIGIN = "origin"
    SINK = "sink"
    DATASET = "dataset"
