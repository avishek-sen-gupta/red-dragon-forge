"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME temps,
BackwardRef for *.STEP.DD references resolved at runtime by the runner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectDSN:
    name: str


@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"


@dataclass(frozen=True)
class BackwardRef:
    step: str  # step name, e.g. "STEP1"
    ddname: str  # DD name, e.g. "WRK"


type DSN = DirectDSN | TempRef | BackwardRef


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN.

    Raises TypeError for TempRef or BackwardRef — both must be resolved via
    the catalog / runner before they can be used as a string key.
    """
    match dsn:
        case DirectDSN(name=n):
            return n
        case TempRef(alias=a):
            raise TypeError(f"TempRef '{a}' must be resolved via the catalog")
        case BackwardRef(step=s, ddname=d):
            raise TypeError(f"BackwardRef '*.{s}.{d}' must be resolved via the runner")
        case _:
            raise TypeError(f"Unhandled DSN type: {dsn!r}")
