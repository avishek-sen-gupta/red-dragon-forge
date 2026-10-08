"""Every vertex's join over all it reaches, answered once per round and shared by every start."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

_V = TypeVar("_V")
_C = TypeVar("_C")

_HEARTBEAT = 5.0


class Closures(Generic[_V, _C]):
    """What a walk from a vertex would find -- the join of every reachable vertex's
    own contribution -- kept per vertex, so a start reaching an answered vertex
    stops there instead of walking everything behind it again.

    The graph is fixed for as long as one of these lives: a combine round builds
    one and drops it, since the edges change between rounds. Strongly connected
    components are solved together, Tarjan's algorithm with an explicit stack:
    every vertex in a component reaches every other, so all of them get one
    answer. Mutable by design, and the only mutation in the combine: the memo and
    the stack are what make it cost each vertex once rather than once per start
    reaching it, and threading them through as values copies them per step.
    """

    def __init__(
        self,
        expand: Callable[[_V], tuple[_C, tuple[_V, ...]]],
        join: Callable[[_C, _C], _C],
        empty: _C,
        heartbeat: float = _HEARTBEAT,
    ) -> None:
        self._expand = expand
        self._join = join
        self._empty = empty
        self._heartbeat = heartbeat
        self._answers: dict[_V, _C] = {}
        self._nexts: dict[_V, tuple[_V, ...]] = {}
        self._revisits: dict[_V, bool] = {}
        self._last = time.monotonic()

    @property
    def answered(self) -> int:
        return len(self._answers)

    def of(self, start: _V, label: str = "") -> _C:
        if start not in self._answers:
            self._solve(start, label)
        return self._answers[start]

    def revisits(self, start: _V) -> bool:
        """Whether a walk from ``start`` reaches some vertex twice -- exactly when
        what it reaches is not a tree rooted at ``start``. A cycle, a repeated
        edge, or a successor that revisits settles it at once; only a vertex with
        several successors that do not is checked by walking the successor lists
        already kept, expanding nothing."""
        if start not in self._revisits:
            self._revisits[start] = self._walked_revisits(start)
        return self._revisits[start]

    def _walked_revisits(self, start: _V) -> bool:
        reached: set[_V] = {start}
        frontier: list[_V] = [start]
        edges = 0
        while frontier:
            vertex = frontier.pop()
            for following in self._nexts[vertex]:
                edges += 1
                if following not in reached:
                    reached.add(following)
                    frontier.append(following)
        return edges != len(reached) - 1

    def _solve(self, start: _V, label: str) -> None:
        index: dict[_V, int] = {}
        low: dict[_V, int] = {}
        local: dict[_V, tuple[_C, tuple[_V, ...]]] = {}
        stack: list[_V] = []
        on_stack: set[_V] = set()
        visiting: list[_V] = []
        positions: list[int] = []

        def visit(vertex: _V) -> None:
            index[vertex] = low[vertex] = len(index)
            local[vertex] = self._expand(vertex)
            stack.append(vertex)
            on_stack.add(vertex)
            visiting.append(vertex)
            positions.append(0)

        visit(start)
        while visiting:
            vertex = visiting[-1]
            position = positions[-1]
            nexts = local[vertex][1]
            if position < len(nexts):
                positions[-1] = position + 1
                following = nexts[position]
                if following in self._answers:
                    continue
                if following not in index:
                    visit(following)
                elif following in on_stack:
                    low[vertex] = min(low[vertex], index[following])
                continue
            visiting.pop()
            positions.pop()
            if visiting:
                parent = visiting[-1]
                low[parent] = min(low[parent], low[vertex])
            if low[vertex] == index[vertex]:
                self._settle(vertex, stack, on_stack, local)
            self._beat(label, len(stack))

    def _settle(
        self,
        root: _V,
        stack: list[_V],
        on_stack: set[_V],
        local: dict[_V, tuple[_C, tuple[_V, ...]]],
    ) -> None:
        """The component whose root is ``root``: every member's own contribution,
        joined with the answers of everything the component points out to."""
        component: list[_V] = []
        while True:
            member = stack.pop()
            on_stack.discard(member)
            component.append(member)
            if member == root:
                break
        members = set(component)
        held = self._empty
        for member in component:
            found, nexts = local[member]
            held = self._join(held, found)
            for following in nexts:
                if following not in members:
                    held = self._join(held, self._answers[following])
        for member in component:
            self._answers[member] = held
            self._nexts[member] = local[member][1]
        self._mark(component)

    def _mark(self, component: list[_V]) -> None:
        """Revisit flags the component settles without walking: every member of a
        cycle revisits, and so does a vertex with a repeated edge or a successor
        that revisits; one with at most one successor, which does not, does not.
        A vertex whose successors are not all settled is left for ``revisits``."""
        if len(component) > 1:
            for member in component:
                self._revisits[member] = True
            return
        (vertex,) = component
        nexts = self._nexts[vertex]
        if vertex in nexts or len(set(nexts)) != len(nexts):
            self._revisits[vertex] = True
        elif any(self._revisits.get(following, False) for following in nexts):
            self._revisits[vertex] = True
        elif len(nexts) <= 1 and all(
            following in self._revisits for following in nexts
        ):
            self._revisits[vertex] = False

    def _beat(self, label: str, depth: int) -> None:
        now = time.monotonic()
        if now - self._last < self._heartbeat:
            return
        self._last = now
        logger.info(
            "combine:     %s%d vertices answered this round, %d on the stack",
            f"{label}: " if label else "",
            len(self._answers),
            depth,
        )
