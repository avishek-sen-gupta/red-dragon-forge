"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME temps."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectDSN:
    name: str


@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"


type DSN = DirectDSN | TempRef


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN.

    Raises TypeError for TempRef — temp aliases must be resolved via the catalog
    before they can be used as a string key.
    """
    match dsn:
        case DirectDSN(name=n):
            return n
        case TempRef(alias=a):
            raise TypeError(f"TempRef '{a}' must be resolved via the catalog")
