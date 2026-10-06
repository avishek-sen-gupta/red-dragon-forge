"""Execution-order walk over a CFG: what actually runs, in control-flow
order, from one PERFORM until it returns.

`cobble-srccfg-reachability-walk` (``walk.py``/``reachability_cli.py``) answers
a different question: reachability, level by level, grouped by distance
from the seed. This module drives the exact same stepper
(``expand()``/``start()``, see ``expand.py``) depth-first instead --
nothing about PERFORM/RANGE_END/recursive-PERFORM handling is
reimplemented here, only the traversal order changes, which is what makes
it the faithful tool for an execution-*order* question rather than a
reachability one.

A TEST node has two live successors in general (branch outcome depends on
runtime data this walk doesn't have), so there is no single "the" execution
order for a program with any conditional in its reachable set. This module
gives two views:

``tree_walk``
    every paragraph that COULD run on some path (both arms of every
    branch, recursed), as an indented tree. Loops are cut off at the point
    a ``(node, open-PERFORM-stack)`` state repeats, noted as such -- the
    same reachable SET as `cobble-srccfg-reachability-walk`, shown in real
    order instead of BFS levels.

``primary_walk``
    one straight line: the FIRST arm at every branch (COBOL's own
    THEN-before-ELSE / first-WHEN-before-next source order), with every
    untaken alternate noted inline rather than expanded. A readable
    "normal path" skeleton -- cross-check its branch points against source
    before calling any single arm "the" answer; it is one of several real
    paths, not the only one.

Both report every ``outcome`` event (RETURNS/CICS_RETURN/XCTL/ABEND-
equivalent) at the node where it fires -- read these before claiming "it
returns to the caller": a GOTO deep in the reachable set can leave the
task entirely and never come back, same program, different path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import reduce

from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.reach.expand import expand, start
from cobble.dataflow.srccfg.reach.reach_state import ReachState
from cobble.dataflow.srccfg.reach.reach_step import ReachStep
from cobble.dataflow.srccfg.rows.cfg_row import CfgRow

_Key = tuple[str, tuple]


def _para(node_id: str) -> str:
    return node_id.split("/")[0].split("#")[0]


def _indent(depth: int) -> str:
    return "  " * depth


def _event_line(event: CfgRow, node: str) -> str:
    kind = event.model_dump().get("kind", event.model_dump().get("type"))
    return f"[[ outcome: {kind}  at {node} ]]"


@dataclass(frozen=True)
class _Trace:
    """What a walk has produced so far: the lines, and each paragraph noted
    once, in the order it was first reached."""

    lines: tuple[str, ...] = ()
    seen: frozenset[str] = frozenset()
    order: tuple[str, ...] = ()

    def said(self, line: str) -> _Trace:
        return replace(self, lines=(*self.lines, line))

    def noted(self, node_id: str) -> _Trace:
        paragraph = _para(node_id)
        if paragraph in self.seen:
            return self
        return replace(
            self, seen=self.seen | {paragraph}, order=(*self.order, paragraph)
        )


def _with_events(
    trace: _Trace, depth: int, node: str, events: tuple[CfgRow, ...]
) -> _Trace:
    return reduce(
        lambda t, ev: t.said(_indent(depth) + _event_line(ev, node)), events, trace
    )


def _opened(seed: str, events: tuple[CfgRow, ...]) -> _Trace:
    return _with_events(_Trace().noted(seed).said(seed), 0, seed, events)


# --- tree_walk -------------------------------------------------------------


@dataclass(frozen=True)
class _TreeState:
    trace: _Trace
    visited: frozenset[_Key]
    remaining: int


def _loop_line(depth: int, node: str) -> str:
    return (
        _indent(depth)
        + f"{node}  (loop/converge -- already walked this exact state, stopping)"
    )


def _branch_label(index: int, total: int, step: ReachStep) -> str:
    if total <= 1:
        return ""
    return f"  <-- branch {index}/{total} ({step.edge.kind})"


def _branch_line(depth: int, index: int, total: int, step: ReachStep) -> str:
    return _indent(depth) + f"-> {step.state.node}{_branch_label(index, total, step)}"


def _tree_branch(
    cfg: Cfg, depth: int, total: int, index: int, step: ReachStep, acc: _TreeState
) -> _TreeState:
    noted = replace(
        acc,
        trace=acc.trace.noted(step.state.node).said(
            _branch_line(depth, index, total, step)
        ),
    )
    return _tree_step(cfg, step.state, depth + 1, noted)


def _tree_branches(
    cfg: Cfg, depth: int, steps: tuple[ReachStep, ...], acc: _TreeState
) -> _TreeState:
    total = len(steps)
    return reduce(
        lambda a, indexed: _tree_branch(cfg, depth, total, indexed[0], indexed[1], a),
        enumerate(steps, start=1),
        acc,
    )


def _tree_expanded(
    cfg: Cfg, state: ReachState, depth: int, acc: _TreeState
) -> _TreeState:
    visit = expand(cfg, state)
    told = replace(acc, trace=_with_events(acc.trace, depth, state.node, visit.events))
    return _tree_branches(cfg, depth, visit.steps, told)


def _tree_step(cfg: Cfg, state: ReachState, depth: int, acc: _TreeState) -> _TreeState:
    key = (state.node, state.stack)
    if key in acc.visited:
        return replace(acc, trace=acc.trace.said(_loop_line(depth, state.node)))
    stepped = replace(acc, visited=acc.visited | {key}, remaining=acc.remaining - 1)
    if stepped.remaining <= 0:
        return replace(
            stepped, trace=stepped.trace.said(_indent(depth) + "[budget exhausted]")
        )
    return _tree_expanded(cfg, state, depth, stepped)


def tree_walk(cfg: Cfg, seed: str, budget: int = 50_000) -> tuple[list[str], list[str]]:
    """Both arms of every branch, recursed; loops cut off at state repeat.

    Returns ``(indented_lines, distinct_paragraphs_in_first_visit_order)``.
    """
    first = start(cfg, seed)
    opened = _TreeState(
        trace=_opened(seed, first.events), visited=frozenset(), remaining=budget
    )
    settled = _tree_branches(cfg, 0, first.steps, opened)
    return list(settled.trace.lines), list(settled.trace.order)


# --- primary_walk ------------------------------------------------------------


@dataclass(frozen=True)
class _PrimaryState:
    trace: _Trace
    visited: frozenset[_Key]


def _primary_line(from_node: str, head: ReachStep, rest: tuple[ReachStep, ...]) -> str:
    if not rest:
        return f"-> {head.state.node}"
    alts = ", ".join(f"{s.edge.kind}->{s.state.node}" for s in rest)
    return f"-> {head.state.node}   [decision at {from_node}; alt: {alts}]"


def _primary_branch(
    cfg: Cfg, from_node: str, steps: tuple[ReachStep, ...], acc: _PrimaryState
) -> _PrimaryState:
    head, rest = steps[0], steps[1:]
    noted = replace(
        acc,
        trace=acc.trace.noted(head.state.node).said(
            _primary_line(from_node, head, rest)
        ),
    )
    return _primary_step(cfg, head.state, noted)


def _primary_expanded(cfg: Cfg, state: ReachState, acc: _PrimaryState) -> _PrimaryState:
    visit = expand(cfg, state)
    told = replace(acc, trace=_with_events(acc.trace, 0, state.node, visit.events))
    if not visit.steps:
        return told
    return _primary_branch(cfg, state.node, visit.steps, told)


def _primary_step(cfg: Cfg, state: ReachState, acc: _PrimaryState) -> _PrimaryState:
    key = (state.node, state.stack)
    if key in acc.visited:
        return replace(
            acc,
            trace=acc.trace.said(
                f"-> {state.node}  (back to an already-walked point: loop closes here)"
            ),
        )
    return _primary_expanded(cfg, state, replace(acc, visited=acc.visited | {key}))


def primary_walk(cfg: Cfg, seed: str) -> tuple[list[str], list[str]]:
    """First arm only at every branch; alternates noted, not expanded.

    Returns ``(lines, distinct_paragraphs_in_order)``.
    """
    first = start(cfg, seed)
    opened = _PrimaryState(trace=_opened(seed, first.events), visited=frozenset())
    if not first.steps:
        return list(opened.trace.lines), list(opened.trace.order)
    settled = _primary_branch(cfg, seed, first.steps, opened)
    return list(settled.trace.lines), list(settled.trace.order)
