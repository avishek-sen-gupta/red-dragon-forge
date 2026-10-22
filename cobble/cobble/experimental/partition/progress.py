"""Progress lines for the graph stage's long passes over rows."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import TypeVar

logger = logging.getLogger(__name__)

PROGRESS_EVERY = 1000

_T = TypeVar("_T")


def _noted(label: str, total: int, numbered: tuple[int, _T]) -> _T:
    number, item = numbered
    if number % PROGRESS_EVERY == 0:
        logger.info("partition graph: %s %d/%d", label, number, total)
    return item


def counted(items: Iterable[_T], label: str, total: int) -> Iterator[_T]:
    yield from (_noted(label, total, numbered) for numbered in enumerate(items, 1))
    logger.info("partition graph: %s %d/%d done", label, total, total)
