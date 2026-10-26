"""A label attribute an FD can contradict, named as the conflict log names it."""

from __future__ import annotations

from enum import Enum


class LabelField(Enum):
    ORGANIZATION = "organization"
    RECFM = "RECFM"
    LRECL = "LRECL"
    KEY_OFFSET = "key offset"
    KEY_LENGTH = "key length"
