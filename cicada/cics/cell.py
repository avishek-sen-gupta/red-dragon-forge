"""A single mutable slot holding an immutable value."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, MutableSequence
from typing import Generic, Never, Protocol, TypeVar, cast

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class Cell(Generic[T]):
    def __init__(self, value: T) -> None:
        self._value = value

    def get(self) -> T:
        return self._value

    def set(self, value: T) -> None:
        self._value = value


class _Slot(Protocol[T_co]):
    def __getitem__(self, index: int, /) -> T_co: ...

    def __setitem__(self, index: int, value: Never, /) -> None: ...


Holder = _Slot[T | None]
"""A one-element list the builtins close over, read covariantly so a caller's
``[None]`` or ``list[CicsContext]`` both qualify; ``None`` means nothing held."""


def hold(holder: Holder[T], value: T | None) -> None:
    # The builtins' holder protocol predates typing: a list created as [None]
    # later carries a CicsContext or DispatchResult, which no invariant list
    # type admits, so the store is the one place that says so.
    cast(MutableSequence[T | None], holder)[0] = value


def held_or(holder: Holder[T], default: T) -> T:
    value = holder[0]
    return default if value is None else value


def fill(cache: MutableMapping[str, T], entries: Mapping[str, T]) -> None:
    """Fill a cache the builtins already close over. The region's program cache
    is handed to the CICS spec before the programs exist -- compiling them needs
    the spec -- and every EXEC CICS LINK resolves against that same object, so it
    is filled in place, never replaced."""
    cache.update(entries)
