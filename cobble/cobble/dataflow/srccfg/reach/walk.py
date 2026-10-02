"""The breadth-first reachability walk, written out as src-cfg rows level by level.

Each level writes the nodes first reached in it, then the edges first taken in it
-- so every edge follows both its nodes -- then what it found. The summary row
comes last, so its presence says the walk finished. The levels are produced lazily,
one from the last, so rows reach the reader as the walk goes.
"""

from collections.abc import Iterator
from dataclasses import replace
from itertools import accumulate, chain, repeat, takewhile
from typing import TypeVar

from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.reach.expand import expand, start
from cobble.dataflow.srccfg.reach.reach_progress import ReachProgress
from cobble.dataflow.srccfg.reach.reach_visit import ReachVisit
from cobble.dataflow.srccfg.rows.cfg_row import (
    CfgRow,
    edge_row,
    node_row,
    program_row,
    summary_row,
)

ItemT = TypeVar("ItemT")


def reach_rows(cfg: Cfg, seed: str) -> Iterator[CfgRow]:
    """Everything that can run from ``seed`` until it returns, as rows.

    Raises ``ReachError`` here, before any row, for a seed the walk cannot start
    from: the seed is checked and its range entered now, and every later level is
    walked only when the reader asks for its rows.
    """
    return _rows(cfg, seed, start(cfg, seed))


def _rows(cfg: Cfg, seed: str, first: ReachVisit) -> Iterator[CfgRow]:
    levels = accumulate(
        repeat(seed),
        lambda progress, _: _after(cfg, seed, progress),
        initial=_advanced(cfg, _begun(seed), (first,)),
    )
    return chain(
        (program_row(cfg.program), node_row(cfg.program, cfg.node(seed))),
        chain.from_iterable(
            level.written for level in takewhile(_still_writing, levels)
        ),
    )


def _after(cfg: Cfg, seed: str, progress: ReachProgress) -> ReachProgress:
    """The next level: another BFS level while there is a frontier, then one level
    holding the summary, then nothing."""
    if progress.frontier:
        visits = tuple(expand(cfg, state) for state in progress.frontier)
        return _advanced(cfg, progress, visits)
    if not progress.finished:
        return replace(
            progress, written=(summary_row(seed, len(progress.seen)),), finished=True
        )
    return replace(progress, written=())


def _still_writing(level: ReachProgress) -> bool:
    return not level.finished or bool(level.written)


def _begun(seed: str) -> ReachProgress:
    return ReachProgress(
        frontier=(),
        seen=frozenset(),
        nodes=frozenset({seed}),
        edges=frozenset(),
        events=frozenset(),
    )


def _advanced(
    cfg: Cfg, progress: ReachProgress, visits: tuple[ReachVisit, ...]
) -> ReachProgress:
    steps = tuple(step for visit in visits for step in visit.steps)
    states = _fresh(tuple(step.state for step in steps), progress.seen)
    nodes = _fresh(tuple(step.state.node for step in steps), progress.nodes)
    edges = _fresh(tuple(step.edge for step in steps), progress.edges)
    events = _fresh(
        tuple(event for visit in visits for event in visit.events), progress.events
    )
    rows = (
        *(node_row(cfg.program, cfg.node(node)) for node in nodes),
        *(edge_row(cfg.program, edge) for edge in edges),
        *events,
    )
    return ReachProgress(
        frontier=states,
        seen=progress.seen | frozenset(states),
        nodes=progress.nodes | frozenset(nodes),
        edges=progress.edges | frozenset(edges),
        events=progress.events | frozenset(events),
        written=rows,
    )


def _fresh(items: tuple[ItemT, ...], known: frozenset[ItemT]) -> tuple[ItemT, ...]:
    """The items not yet known, once each, in the order they arrived."""
    return tuple(dict.fromkeys(item for item in items if item not in known))
