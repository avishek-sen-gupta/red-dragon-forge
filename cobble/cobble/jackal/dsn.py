"""DSN type hierarchy: DirectDSN for permanent datasets, TempRef for &&NAME
temps, BackwardRef for *.STEP.DD references resolved at runtime by the
runner, InStreamDSN for instream data (DD *), DummyDSN for an explicit null
dataset (DD DUMMY), and NoDSN for a DD whose empty DSN isn't explained by any
of the above (currently: SYSOUT — has its own dd.sysout flag everywhere it
matters — or a genuine gap worth treating with suspicion)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeAlias

from jackal.value_parts import Symbol, Value, resolve


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


# ``TypeAlias`` rather than a 3.12 ``type`` statement because the lint config
# still parses this package as 3.11.
DSN: TypeAlias = "DirectDSN | TempRef | BackwardRef | InStreamDSN | DummyDSN | NoDSN"

# A temporary dataset name is a data set name qualifier: at most 8 characters.
_MAX_TEMP_NAME = 8


def temp_if_unresolved(dsn: DSN) -> DSN:
    """Re-read a DSN that is one lone unresolved symbol as a temporary dataset.

    z/OS reads ``DSN=&NAME`` as ``DSN=&&NAME`` when NAME is no defined symbol,
    so one ampersand and two name the same temporary file, and real JCL relies
    on it: a job writes ``DSN=&WORK`` in the step that creates the file and
    ``DSN=&&WORK`` in the step that reads it back.

    Only a whole DSN that is a single symbol short enough to be a temp name
    qualifies. A longer symbol, or a symbol glued to literal text
    (``&HLQ..DATA``), is an unbound parameter rather than a temp file, and
    stays what it is so :func:`dsn_key` still reports it.
    """
    match dsn:
        case DirectDSN(name=(Symbol(name=n),)) if len(n) <= _MAX_TEMP_NAME:
            return TempRef(f"&{n}")
        case _:
            return dsn


def _temp_ref_unresolvable(dsn: TempRef) -> str:
    return f"TempRef '{dsn.alias}' must be resolved via the catalog"


def _backward_ref_unresolvable(dsn: BackwardRef) -> str:
    return f"BackwardRef '*.{dsn.step}.{dsn.ddname}' must be resolved via the runner"


def _no_dataset(dsn: InStreamDSN | DummyDSN | NoDSN) -> str:
    return f"{type(dsn).__name__} has no dataset to resolve to"


_UNRESOLVABLE: Mapping[type, Callable[..., str]] = {
    TempRef: _temp_ref_unresolvable,
    BackwardRef: _backward_ref_unresolvable,
    InStreamDSN: _no_dataset,
    DummyDSN: _no_dataset,
    NoDSN: _no_dataset,
}


def dsn_key(dsn: DSN) -> str:
    """Extract the string DSN name from a DirectDSN, resolving its Value.

    Raises ValueError if the DirectDSN's Value has an unresolved Symbol part.
    Raises TypeError for every other DSN variant — none of them can be used
    as a string key (TempRef/BackwardRef must first be resolved via the
    catalog / runner; InStreamDSN/DummyDSN/NoDSN have no dataset to resolve
    to at all).
    """
    if isinstance(dsn, DirectDSN):
        return resolve(dsn.name)
    if type(dsn) not in _UNRESOLVABLE:
        raise TypeError(f"Unhandled DSN type: {type(dsn).__name__}")
    raise TypeError(_UNRESOLVABLE[type(dsn)](dsn))
