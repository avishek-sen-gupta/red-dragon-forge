"""Independent work over items, run in this process or in a pool, consumed in item order."""

from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

_A = TypeVar("_A")
_R = TypeVar("_R")
_T = TypeVar("_T")


def consumed_in_order(
    work: Callable[[_A], _R],
    items: Sequence[_A],
    max_workers: int,
    consume: Callable[[Iterator[_R]], _T],
) -> _T:
    """``consume`` sees one result per item, in item order, whatever order the
    workers finish in. One worker runs the work here; more run it in worker
    processes, so ``work`` and each item must be picklable."""
    if max_workers == 1:
        return consume(map(work, items))
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        return consume(pool.map(work, items))
