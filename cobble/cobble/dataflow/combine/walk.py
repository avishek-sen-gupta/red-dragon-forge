"""Walk every vertex reachable from a start once, joining what each one contributes."""

import logging
import time
from collections.abc import Callable
from functools import reduce
from itertools import accumulate, count
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


def _no_spread(seen: frozenset[_V]) -> str:
    return ""


def _log_heartbeat(
    label: str,
    spread: Callable[[frozenset[_V]], str],
    steps: int,
    state: WalkState[_V, _C],
) -> None:
    logger.info(
        "combine:     %swalk step %d, %d seen%s, %d frontier",
        f"{label}: " if label else "",
        steps,
        len(state.seen),
        spread(state.seen),
        len(state.frontier),
    )


def walked(
    start: _V,
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
    empty: _C,
    label: str = "",
    heartbeat: float = _WALK_HEARTBEAT,
    spread: Callable[[frozenset[_V]], str] = _no_spread,
) -> WalkState[_V, _C]:
    """Steps until the frontier is empty, with a heartbeat at most every
    ``heartbeat`` seconds naming ``label`` -- where the walk sits in its round --
    and what ``spread`` says of the vertices seen so far.
    Iterated, not recursed: a walk across a corpus can take more steps than the
    interpreter allows stack frames."""
    first = WalkState(frozenset({start}), frozenset({start}), empty)
    runs = accumulate(
        count(1),
        lambda run, steps: _stepped(
            run, steps, expand, join, (label, heartbeat, spread)
        ),
        initial=(first, time.monotonic()),
    )
    return next(state for state, _ in runs if not state.frontier)


def _stepped(
    run: tuple[WalkState[_V, _C], float],
    steps: int,
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
    beat: tuple[str, float, Callable[[frozenset[_V]], str]],
) -> tuple[WalkState[_V, _C], float]:
    state, last = run
    label, heartbeat, spread = beat
    stepped = _step(state, expand, join)
    now = time.monotonic()
    if now - last < heartbeat:
        return stepped, last
    _log_heartbeat(label, spread, steps, stepped)
    return stepped, now
