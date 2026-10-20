"""How a keyed READ or STARTBR matches its key against the file's keys."""

from __future__ import annotations

from enum import Enum


class KeyMatch(Enum):
    """Access-method relops, compared over the given key's length, so a generic key matches its prefix."""

    EQUAL = "="
    GTEQ = ">="
