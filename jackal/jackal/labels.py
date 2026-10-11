"""A dataset's label: the record format the system holds beside its bytes, as z/OS's VTOC does."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias


class RecordFormat(Enum):
    F = "F"
    FB = "FB"
    V = "V"
    VB = "VB"


def _positive(value: int, what: str) -> None:
    if value <= 0:
        raise ValueError(f"{what} must be > 0, got {value}")


VARIABLE = frozenset({RecordFormat.V, RecordFormat.VB})


@dataclass(frozen=True)
class SequentialLabel:
    recfm: RecordFormat
    lrecl: int

    def __post_init__(self) -> None:
        _positive(self.lrecl, "LRECL")


@dataclass(frozen=True)
class KsdsLabel:
    lrecl: int
    key_offset: int
    key_length: int

    def __post_init__(self) -> None:
        _positive(self.lrecl, "LRECL")
        _positive(self.key_length, "key length")


@dataclass(frozen=True)
class LabelPending:
    """A dataset a job created, labelled at its first OPEN OUTPUT."""


Label: TypeAlias = SequentialLabel | KsdsLabel
DatasetLabel: TypeAlias = Label | LabelPending
