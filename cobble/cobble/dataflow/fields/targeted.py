"""Targeted plan construction for full branch coverage.

Phase 1: the heuristic sampler runs until its fresh queue exhausts (~93%).
Phase 2: for each still-untaken edge, a BFS plan probes toward it. The probe
may not land exactly (the walk's stack rules can diverge from the BFS path),
but it reaches new territory. The alternatives that walk generates (via
``walk.made``) are sound — they're recorded from the actual decisions — so they
go into a local queue and are drained until no new coverage comes. This
iterates: each probe opens a new subtree, and the queue explores it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import reduce
from itertools import repeat
from types import MappingProxyType

from cobble.dataflow.fields.trace import (
    Budget,
    Coverage,
    Loaded,
    Loader,
    Trace,
    _alternatives,
    _closed,
    _coverage,
    _done,
    _drained,
    _empty,
    _extended,
    _head,
    _Queue,
    _queue_stop,
    _reported,
    _Run,
    _started,
    _step,
    _walked,
)
from cobble.dataflow.srccfg.cfg import Cfg, NodeKind

logger = logging.getLogger(__name__)


def _branch_edges_for(prog: str, loader: Loader) -> frozenset[tuple[str, str, str]]:
    loaded = loader(prog)
    return frozenset(
        (prog, edge.source, edge.kind.value)
        for edge in loaded.cfg.edges
        if loaded.cfg.node(edge.source).kind is NodeKind.TEST
    )


def _all_branch_edges(
    coverage: Coverage, loader: Loader
) -> frozenset[tuple[str, str, str]]:
    return reduce(
        lambda acc, prog: acc | _branch_edges_for(prog, loader),
        coverage.programs,
        frozenset(),
    )


def _phase1_round(run: _Run, program: str, loader: Loader, budget: Budget) -> _Run:
    if _done(run, budget):
        return run
    reason = _queue_stop(run.queue)
    if reason:
        return replace(run, stopped=reason)
    stepped = _step(run, program, loader, budget)
    return replace(
        stepped.run,
        trace=replace(stepped.run.trace, deps=run.trace.deps | stepped.deps),
    )


def _probe_and_drain(
    plan: tuple[int, ...],
    run: _Run,
    program: str,
    loader: Loader,
    budget: Budget,
    max_drain: int,
) -> _Run:
    """Walk one BFS probe, feed its alternatives into a local queue, drain it."""
    walk = _walked(_started(program, loader, plan), budget.max_depth, loader)
    coverage = _coverage(run.trace.coverage, walk, loader)
    alts = _alternatives(plan, walk.made)
    queue = _extended(_Queue(fresh=(), stale=()), coverage.taken, alts)

    probed = _reported(
        _Run(
            trace=Trace(
                deps=run.trace.deps | walk.deps,
                dead_ends=run.trace.dead_ends | walk.dead_ends,
                paths=run.trace.paths + 1,
                coverage=coverage,
            ),
            queue=queue,
        ),
        walk,
        budget,
    )
    return _drain_local(probed, program, loader, budget, max_drain)


def _drain_local(
    run: _Run, program: str, loader: Loader, budget: Budget, remaining: int
) -> _Run:
    """Drain the local queue until fresh empties or the budget runs out."""
    return reduce(
        lambda r, _: _drain_one(r, program, loader, budget),
        repeat(None, remaining),
        run,
    )


def _drain_one(run: _Run, program: str, loader: Loader, budget: Budget) -> _Run:
    if _empty(run.queue) or not run.queue.fresh:
        return run
    head = _head(run.queue)
    walk = _walked(_started(program, loader, head.plan), budget.max_depth, loader)
    coverage = _coverage(run.trace.coverage, walk, loader)
    return _reported(
        _Run(
            trace=Trace(
                deps=run.trace.deps | walk.deps,
                dead_ends=run.trace.dead_ends | walk.dead_ends,
                paths=run.trace.paths + 1,
                coverage=coverage,
            ),
            queue=_extended(
                _drained(run.queue), coverage.taken, _alternatives(head.plan, walk.made)
            ),
        ),
        walk,
        budget,
    )


def _plan_for_edge(
    node_id: str, kind: str, program: str, loader: Loader
) -> tuple[int, ...]:
    """BFS on the raw CFG from entry to ``node_id``, collecting arm choices."""
    loaded = loader(program)
    if not loaded.entry:
        return ()
    initial = _BfsState(
        frontier=(loaded.entry,),
        visited=frozenset({loaded.entry}),
        predecessors=MappingProxyType({}),
    )
    return _bfs_step(node_id, kind, loaded.cfg, loaded, initial)


@dataclass(frozen=True)
class _BfsState:
    frontier: tuple[str, ...]
    visited: frozenset[str]
    predecessors: MappingProxyType


def _expand_one_edge(
    state: _BfsState, current: str, edge_target: str, edge_kind_value: str
) -> _BfsState:
    if edge_target in state.visited:
        return state
    return _BfsState(
        frontier=(*state.frontier, edge_target),
        visited=state.visited | {edge_target},
        predecessors=MappingProxyType(
            {**state.predecessors, edge_target: (current, edge_kind_value)}
        ),
    )


def _expand_frontier(cfg: Cfg, state: _BfsState) -> _BfsState:
    """Expand all edges from the current frontier, returning a new state with next frontier."""
    expanded = reduce(
        lambda st, pair: _expand_one_edge(st, pair[0], pair[1], pair[2]),
        (
            (current, edge.target, edge.kind.value)
            for current in state.frontier
            for edge in cfg.edges
            if edge.source == current and edge.target not in state.visited
        ),
        _BfsState(frontier=(), visited=state.visited, predecessors=state.predecessors),
    )
    return expanded


def _check_target(
    target: str, kind: str, cfg: Cfg, loaded: Loaded, state: _BfsState
) -> tuple[int, ...]:
    """Return the plan if ``target`` is reachable in ``state``, else ()."""
    if target in state.predecessors:
        return _path_to_plan(target, kind, state.predecessors, cfg, loaded)
    return ()


def _bfs_step(
    target: str,
    kind: str,
    cfg: Cfg,
    loaded: Loaded,
    state: _BfsState,
) -> tuple[int, ...]:
    if not state.frontier:
        return ()
    found = _check_target(target, kind, cfg, loaded, state)
    if found:
        return found
    expanded = _expand_frontier(cfg, state)
    found_after = _check_target(target, kind, cfg, loaded, expanded)
    return (
        found_after if found_after else _bfs_step(target, kind, cfg, loaded, expanded)
    )


def _path_to_plan(
    target: str,
    target_kind: str,
    predecessors: MappingProxyType,
    cfg: Cfg,
    loaded: Loaded,
) -> tuple[int, ...]:
    path_nodes = _trace_back(target, predecessors, (target,))
    choices = tuple(
        arm
        for i in range(len(path_nodes) - 1)
        for arm in _arm_at(path_nodes[i], path_nodes[i + 1], cfg, loaded)
    )
    return (*choices, *_target_arm(target, target_kind, cfg, loaded))


def _trace_back(
    current: str,
    predecessors: Mapping,
    accumulated: tuple[str, ...],
) -> tuple[str, ...]:
    if current not in predecessors:
        return tuple(reversed(accumulated))
    prev, _ = predecessors[current]
    return _trace_back(prev, predecessors, (*accumulated, prev))


def _arm_at(node_id: str, next_id: str, cfg: Cfg, loaded: Loaded) -> tuple[int, ...]:
    node = cfg.node(node_id)
    if node.kind is not NodeKind.TEST:
        return ()
    outgoing = sorted(
        (e for e in cfg.edges if e.source == node_id),
        key=lambda e: not cfg.successors(e.target),
    )
    return (
        next(
            (idx for idx, e in enumerate(outgoing) if e.target == next_id),
            0,
        ),
    )


def _target_arm(target: str, kind: str, cfg: Cfg, loaded: Loaded) -> tuple[int, ...]:
    node = cfg.node(target)
    if node.kind is not NodeKind.TEST:
        return ()
    outgoing = sorted(
        (e for e in cfg.edges if e.source == target),
        key=lambda e: not cfg.successors(e.target),
    )
    return (
        next(
            (idx for idx, e in enumerate(outgoing) if e.kind.value == kind),
            0,
        ),
    )


_DEFAULT_BUDGET = Budget()


def targeted(
    program: str,
    loader: Loader,
    budget: Budget = _DEFAULT_BUDGET,
) -> Trace:
    """Phase 1 + phase 2: heuristic then targeted probes with local draining."""
    phase1 = reduce(
        lambda r, _: _phase1_round(r, program, loader, budget),
        repeat(None, budget.paths),
        _Run(),
    )

    logger.info(
        "targeted: phase 1 done, %d paths, %d/%d branches (%d%%)",
        phase1.trace.paths,
        len(phase1.trace.coverage.taken),
        phase1.trace.coverage.total,
        round(100 * phase1.trace.coverage.fraction),
    )

    remaining = budget.paths - phase1.trace.paths
    if remaining <= 0:
        return _closed(phase1, budget).trace

    untaken = (
        _all_branch_edges(phase1.trace.coverage, loader) - phase1.trace.coverage.taken
    )

    logger.info(
        "targeted: phase 2, %d untaken edges, %d paths remaining",
        len(untaken),
        remaining,
    )

    phase2 = _phase2_loop(
        replace(phase1, stopped=""),
        sorted(untaken),
        program,
        loader,
        budget,
        remaining,
    )

    logger.info(
        "targeted: phase 2 done, %d total paths, %d/%d branches (%d%%)",
        phase2.trace.paths,
        len(phase2.trace.coverage.taken),
        phase2.trace.coverage.total,
        round(100 * phase2.trace.coverage.fraction),
    )

    return _closed(phase2, budget).trace


def _phase2_loop(
    run: _Run,
    untaken: Sequence[tuple[str, str, str]],
    program: str,
    loader: Loader,
    budget: Budget,
    remaining: int,
) -> _Run:
    return reduce(
        lambda r, edge: _try_edge(r, edge, program, loader, budget, remaining),
        untaken,
        run,
    )


def _edge_already_covered(run: _Run, edge: tuple[str, str, str]) -> bool:
    return edge in run.trace.coverage.taken


def _try_edge(
    run: _Run,
    edge: tuple[str, str, str],
    program: str,
    loader: Loader,
    budget: Budget,
    max_paths: int,
) -> _Run:
    if _edge_already_covered(run, edge):
        return run
    prog, node_id, kind = edge
    plan = _plan_for_edge(node_id, kind, prog, loader)
    if not plan:
        return run
    return _probe_and_drain(plan, run, program, loader, budget, min(50, max_paths))
