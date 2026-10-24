"""Progress lines for long runs over rows."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from typing import TypeVar

from cobble.experimental.partition.tally import Tally

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _noted(tally: Tally, total: int, numbered: tuple[int, _T]) -> _T:
    number, item = numbered
    if number % tally.every == 0:
        logger.info("%s: %s %d/%d", tally.stage, tally.label, number, total)
    return item


def counted(items: Iterable[_T], tally: Tally, total: int) -> Iterator[_T]:
    yield from (_noted(tally, total, numbered) for numbered in enumerate(items, 1))
    logger.info("%s: %s %d/%d done", tally.stage, tally.label, total, total)
