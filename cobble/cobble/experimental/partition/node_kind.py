"""What a graph node stands for."""

from __future__ import annotations

from enum import StrEnum


class NodeKind(StrEnum):
    """A field's storage, or a terminal where bytes enter or leave a program."""

    FIELD = "field"
    ORIGIN = "origin"
    SINK = "sink"
