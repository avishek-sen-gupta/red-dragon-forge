"""Walk every vertex reachable from a start once, joining what each one contributes."""

import logging
import time
from collections.abc import Callable
from functools import reduce
from typing import TypeVar

from cobble.dataflow.combine.walk_state import WalkState

logger = logging.getLogger(__name__)

_V = TypeVar("_V")
_C = TypeVar("_C")

_WALK_HEARTBEAT = 5.0


def _expand_frontier(
    frontier: frozenset[_V],
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
) -> tuple[tuple[tuple[_C, tuple[_V, ...]], ...], float]:
    """Expand every vertex in the frontier, returning expansions and max single-vertex time."""
    started = time.monotonic()
    expansions = tuple(expand(vertex) for vertex in frontier)
    return expansions, time.monotonic() - started


def _step(
    state: WalkState[_V, _C],
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
) -> WalkState[_V, _C]:
    expansions, _ = _expand_frontier(state.frontier, expand)
    reached = tuple(vertex for _, nexts in expansions for vertex in nexts)
    fresh = frozenset(reached) - state.seen
    return WalkState(
        state.seen | fresh,
        fresh,
        reduce(join, (found for found, _ in expansions), state.found),
        state.revisited or len(reached) != len(fresh),
    )


def _log_heartbeat(steps: int, state: WalkState[_V, _C]) -> None:
    logger.info(
        "combine:     walk step %d, %d seen, %d frontier",
        steps,
        len(state.seen),
        len(state.frontier),
    )


def walked(
    start: _V,
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
    empty: _C,
) -> WalkState[_V, _C]:
    first = WalkState(frozenset({start}), frozenset({start}), empty)
    return _walk_loop(first, expand, join, 0, time.monotonic())


def _walk_loop(
    state: WalkState[_V, _C],
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
    steps: int,
    last_log: float,
) -> WalkState[_V, _C]:
    if not state.frontier:
        return state
    stepped = _step(state, expand, join)
    now = time.monotonic()
    due = now - last_log >= _WALK_HEARTBEAT
    if due:
        _log_heartbeat(steps + 1, stepped)
    return _walk_loop(stepped, expand, join, steps + 1, now if due else last_log)
