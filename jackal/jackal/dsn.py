"""What a DD names: a dataset, a temporary, a referback to an earlier step's DD, in-stream data, DUMMY, or nothing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeAlias, TypeVar

from jackal.value_parts import Value, resolve

R = TypeVar("R")
S = TypeVar("S")


@dataclass(frozen=True)
class DdName:
    text: str


@dataclass(frozen=True)
class DirectDSN:
    name: Value

    def dataset_name(self) -> str:
        return resolve(self.name)

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DSN[R]:
        return name(self.name)


@dataclass(frozen=True)
class TempRef:
    name: str

    def dataset_name(self) -> str:
        raise TypeError(f"temporary dataset &&{self.name} is allocated by the catalog")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class BackwardRef(Generic[R]):
    step: R
    ddname: DdName

    def dataset_name(self) -> str:
        raise TypeError(f"referback to {self.ddname.text} is resolved by the runner")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return backref(self)

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class InStreamDSN:
    def dataset_name(self) -> str:
        raise TypeError("in-stream data has no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class DummyDSN:
    def dataset_name(self) -> str:
        raise TypeError("DUMMY has no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DSN[R]:
        return self


@dataclass(frozen=True)
class NoDSN:
    def dataset_name(self) -> str:
        raise TypeError("a DD with no DSN has no dataset")

    def mapped(self, backref: Callable[[BackwardRef[R]], BackwardRef[S]]) -> DSN[S]:
        return self

    def substituted(self, name: Callable[[Value], DSN[R]]) -> DSN[R]:
        return self


DSN: TypeAlias = DirectDSN | TempRef | BackwardRef[R] | InStreamDSN | DummyDSN | NoDSN
