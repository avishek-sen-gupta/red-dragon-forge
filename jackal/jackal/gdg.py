"""A generation data group's base: its limit, its roll-off rules and its active generations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Empty(Enum):
    EMPTY = "EMPTY"
    NOEMPTY = "NOEMPTY"


class Scratch(Enum):
    SCRATCH = "SCRATCH"
    NOSCRATCH = "NOSCRATCH"


class GdgOrder(Enum):
    FIFO = "FIFO"
    LIFO = "LIFO"


class RequestedOrder(Enum):
    USECATLG = "USECATLG"
    FIFO = "FIFO"
    LIFO = "LIFO"


_CODED_ORDERS: dict[RequestedOrder, GdgOrder] = {
    RequestedOrder.FIFO: GdgOrder.FIFO,
    RequestedOrder.LIFO: GdgOrder.LIFO,
}


def relative_generation(active: tuple[int, ...], relative: int) -> tuple[int, ...]:
    if relative > 0:
        return (max(active, default=0) + relative,)
    index = len(active) - 1 + relative
    return active[index : index + 1] if index >= 0 else ()


@dataclass(frozen=True)
class GdgBase:
    name: str
    limit: int
    empty: Empty
    scratch: Scratch
    order: GdgOrder
    generations: tuple[int, ...]

    def dataset_name(self, number: int) -> str:
        return f"{self.name}.G{number:04d}V00"

    def all_relatives(
        self, active: tuple[int, ...], requested: RequestedOrder
    ) -> tuple[int, ...]:
        oldest_first = tuple(range(1 - len(active), 1))
        if self._order(requested) is GdgOrder.FIFO:
            return oldest_first
        return oldest_first[::-1]

    def _order(self, requested: RequestedOrder) -> GdgOrder:
        return _CODED_ORDERS.get(requested, self.order)

    def without(self, number: int) -> GdgBase:
        return replace(
            self, generations=tuple(g for g in self.generations if g != number)
        )

    def rolled_in(self, number: int) -> tuple[GdgBase, tuple[int, ...]]:
        if number in self.generations:
            return (self, ())
        off = self._rolled_off(len(self.generations) + 1 - self.limit)
        kept = tuple(g for g in self.generations if g not in off)
        return (replace(self, generations=(*kept, number)), off)

    def scratched(self, rolled_off: tuple[int, ...]) -> tuple[str, ...]:
        if self.scratch is Scratch.NOSCRATCH:
            return ()
        return tuple(map(self.dataset_name, rolled_off))

    def _rolled_off(self, excess: int) -> tuple[int, ...]:
        if excess <= 0:
            return ()
        if self.empty is Empty.EMPTY:
            return self.generations
        return self.generations[:excess]
