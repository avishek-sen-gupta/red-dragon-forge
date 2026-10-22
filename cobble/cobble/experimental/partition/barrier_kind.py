"""The barriers a graph can be built with, resolved to a strategy at the command line."""

from __future__ import annotations

from enum import StrEnum

from cobble.experimental.partition.barrier import Barrier
from cobble.experimental.partition.fanout_barrier import FanoutBarrier
from cobble.experimental.partition.no_barrier import NoBarrier


class BarrierKind(StrEnum):
    """No barrier, or one blocking a statement that links one field to many."""

    NONE = "none"
    FANOUT = "fanout"

    def barrier(self, fanout_limit: int) -> Barrier:
        if self is BarrierKind.FANOUT:
            return FanoutBarrier(limit=fanout_limit)
        return NoBarrier()
