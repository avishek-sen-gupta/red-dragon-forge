"""Walk every vertex reachable from a start once, joining what each one contributes."""

from collections.abc import Callable
from functools import reduce
from itertools import accumulate, count
from typing import TypeVar

from cobble.dataflow.combine.walk_state import WalkState

_V = TypeVar("_V")
_C = TypeVar("_C")


def _step(
    state: WalkState[_V, _C],
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
) -> WalkState[_V, _C]:
    expansions = tuple(expand(vertex) for vertex in state.frontier)
    reached = tuple(vertex for _, nexts in expansions for vertex in nexts)
    fresh = frozenset(reached) - state.seen
    return WalkState(
        state.seen | fresh,
        fresh,
        reduce(join, (found for found, _ in expansions), state.found),
        state.revisited or len(reached) != len(fresh),
    )


def walked(
    start: _V,
    expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
    join: Callable[[_C, _C], _C],
    empty: _C,
) -> WalkState[_V, _C]:
    """Steps until the frontier is empty. Iterated, not recursed: a walk across a
    corpus can take more steps than the interpreter allows stack frames."""
    first = WalkState(frozenset({start}), frozenset({start}), empty)
    states = accumulate(
        count(), lambda state, _: _step(state, expand, join), initial=first
    )
    return next(state for state in states if not state.frontier)
