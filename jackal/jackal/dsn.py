"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME
temps, BackwardRef for *.STEP.DD references resolved at runtime by the
runner, InStreamDSN for instream data (DD *), DummyDSN for an explicit null
dataset (DD DUMMY), and NoDSN for a DD whose empty DSN isn't explained by any
of the above (currently: SYSOUT — has its own dd.sysout flag everywhere it
matters — or a genuine gap worth treating with suspicion)."""

from __future__ import annotations

from dataclasses import dataclass

from jackal.value_parts import Value, resolve


@dataclass(frozen=True)
class DirectDSN:
    name: Value


@dataclass(frozen=True)
class TempRef:
    alias: str  # full &&NAME string, e.g. "&&WORKIN"


@dataclass(frozen=True)
class BackwardRef:
    step: str  # step name, e.g. "STEP1"
    ddname: str  # DD name, e.g. "WRK"


@dataclass(frozen=True)
class InStreamDSN:
    """A DD fed by literal inline data (DD * / DD DATA) rather than a
    catalogued dataset. Carries no fields of its own — the actual content
    stays in DD.in_stream, which already exists for this; this is purely a
    type discriminant so callers can tell "positively identified as instream
    data" apart from NoDSN's "unexplained empty DSN"."""


@dataclass(frozen=True)
class DummyDSN:
    """An explicit null dataset (DD DUMMY): reads hit EOF immediately,
    writes are discarded. A deliberate, well-formed JCL construct — not an
    error, and not the same as NoDSN's "unexplained empty DSN"."""


@dataclass(frozen=True)
class NoDSN:
    """A DD with an empty DSN not explained by InStreamDSN or DummyDSN —
    currently SYSOUT (DD SYSOUT=*), which already has its own dd.sysout flag
    checked everywhere it matters, so nothing is lost by routing it here."""


type DSN = DirectDSN | TempRef | BackwardRef | InStreamDSN | DummyDSN | NoDSN


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN, resolving its Value.

    Raises ValueError if the DirectDSN's Value has an unresolved Symbol part.
    Raises TypeError for every other DSN variant — none of them can be used
    as a string key (TempRef/BackwardRef must first be resolved via the
    catalog / runner; InStreamDSN/DummyDSN/NoDSN have no dataset to resolve
    to at all).
    """
    match dsn:
        case DirectDSN(name=n):
            return resolve(n)
        case TempRef(alias=a):
            raise TypeError(f"TempRef '{a}' must be resolved via the catalog")
        case BackwardRef(step=s, ddname=d):
            raise TypeError(f"BackwardRef '*.{s}.{d}' must be resolved via the runner")
        case InStreamDSN():
            raise TypeError("InStreamDSN has no dataset to resolve to")
        case DummyDSN():
            raise TypeError("DummyDSN has no dataset to resolve to")
        case NoDSN():
            raise TypeError("NoDSN has no dataset to resolve to")
        case _:
            raise TypeError(f"Unhandled DSN type: {dsn!r}")
