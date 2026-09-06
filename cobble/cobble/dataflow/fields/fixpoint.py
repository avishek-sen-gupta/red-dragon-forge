"""Intra-program worklist over CFG node entry states.

The ujr spike measured loop fixpoints as cheap -- 11,826 loops settled in one
iteration, 1,599 in two, the 30-iteration cap never reached. The cost was
recursive PERFORM inlining re-analysing a paragraph once per call path, which
took 710.58s on the corpus's worst member. Keying on the node rather than on the
call path removes inlining entirely: a PERFORM is an edge, so a paragraph reached
from two sites is one node set joined, not two copies. That bounds the work at
O(nodes x state changes) and needs no depth cap.

Joining at the node is also what keeps a branch honest. Replaying a paragraph's
statements in declaration order would let an ELSE arm's write kill the THEN arm's
definition, and a dropped edge is invisible in the output -- exactly the failure
the lattice's may_alias/must_cover asymmetry exists to avoid.

The pass has two phases because they answer different questions. The fixpoint
settles what reaches each node; extraction then reads each statement's writes
once, at that settled state. Deriving edges by diffing the state around a
statement instead would lose every loop-carried flow -- the definition is already
in the in-state on the second visit, so the diff comes back empty.

What the settled state contributes is the defining node. A write stores, under
the target extent, the node that wrote it; so a later read of that extent
recovers where its value was last defined, and an edge carries def-use rather
than a bare field-to-field pair. A read nothing reaches is credited to the node
reading it: an uninitialised read is still a read.

Termination does not rest on the cap: every extent a transfer can construct is
fixed by the statement set before iteration begins, so the lattice has finite
height and join is monotone. The cap is a defence against a defect, not part of
the argument, and it records a reason rather than silently truncating.

The coverage counters are computed from the source, not from the answer. The 3ao
post-mortem found an acceptance suite passing while its walk reached 18% of
nodes, because the denominator was derived from what the walk had produced.
``writes`` counts write operands the statements name; ``covered`` counts those
whose extents resolved.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import accumulate, repeat
from types import MappingProxyType

from cobble.dataflow.fields.extent import CellIndex, cell_index, operand_extents
from cobble.dataflow.fields.state import EMPTY, Source, State, join, reaching
from cobble.dataflow.fields.transfer import (
    HANDLED,
    Statement,
    transfer,
    write_operands,
    writes_of,
)
from cobble.dataflow.layout import UnsizeableFieldError, program_records
from cobble.dataflow.srccfg.build import build_program, label_id, paragraph_order
from cobble.dataflow.srccfg.cfg import Cfg
from cobble.dataflow.srccfg.statements import statement_index
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent

logger = logging.getLogger(__name__)

ITERATION_FACTOR = 50

NO_INDEX = cell_index(())


@dataclass(frozen=True)
class FlowEdge:
    """One value reaching one extent: ``source.node`` defined it, ``node`` moved it."""

    source: Source
    target: FieldExtent
    node: str


@dataclass(frozen=True)
class ProgramFlow:
    """Every field-level flow in one program, with what the pass did not reach.

    ``skipped`` non-empty means the numbers describe an abandoned analysis and
    must not be counted towards a coverage floor.
    """

    program: str
    edges: tuple[FlowEdge, ...] = ()
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    nodes: int = 0
    dequeues: int = 0
    skipped: str = ""


@dataclass(frozen=True)
class _Tally:
    """What the statements ask for, counted before any of them is analysed."""

    writes: int = 0
    covered: int = 0
    unhandled: int = 0


@dataclass(frozen=True)
class _Pass:
    """One step of the worklist: entry states settled so far, and what to revisit."""

    states: Mapping[str, State]
    queue: tuple[str, ...]
    dequeues: int = 0


def _statements_at(
    cfg: Cfg, statements: Mapping[str, Statement]
) -> tuple[tuple[str, Statement], ...]:
    return tuple(
        (node.id, statements[node.id]) for node in cfg.nodes if node.id in statements
    )


def _resolved(operands: Sequence[RefModOperand], index: CellIndex) -> int:
    return sum(1 for operand in operands if operand_extents(operand, index).extents)


def _one_tally(statement: Statement, index: CellIndex) -> _Tally:
    if not isinstance(statement, HANDLED):
        return _Tally(unhandled=1)
    operands = write_operands(statement)
    return _Tally(writes=len(operands), covered=_resolved(operands, index))


def _tally(found: tuple[tuple[str, Statement], ...], index: CellIndex) -> _Tally:
    counted = tuple(_one_tally(statement, index) for _, statement in found)
    return _Tally(
        writes=sum(one.writes for one in counted),
        covered=sum(one.covered for one in counted),
        unhandled=sum(one.unhandled for one in counted),
    )


def _entry_node(asg) -> str:
    order = paragraph_order(asg)
    return label_id(order[0].name) if order else ""


def _after(
    statements: Mapping[str, Statement], node_id: str, before: State, index: CellIndex
) -> State:
    statement = statements.get(node_id)
    return transfer(statement, node_id, before, index) if statement else before


def _grown(
    cfg: Cfg, node_id: str, after: State, states: Mapping[str, State]
) -> Mapping[str, State]:
    """Successors whose entry state the state leaving ``node_id`` enlarges."""
    joined = {
        edge.target: join(states.get(edge.target, EMPTY), after)
        for edge in cfg.successors(node_id)
    }
    return {
        target: state
        for target, state in joined.items()
        if state != states.get(target, EMPTY) or target not in states
    }


def _step(
    cfg: Cfg, statements: Mapping[str, Statement], index: CellIndex, run: _Pass
) -> _Pass:
    node_id, *rest = run.queue
    after = _after(statements, node_id, run.states[node_id], index)
    grown = _grown(cfg, node_id, after, run.states)
    return _Pass(
        states=MappingProxyType({**run.states, **grown}),
        queue=(*rest, *(target for target in grown if target not in rest)),
        dequeues=run.dequeues + 1,
    )


def _done(run: _Pass, cap: int) -> bool:
    return not run.queue or run.dequeues >= cap


def _settled(
    cfg: Cfg,
    statements: Mapping[str, Statement],
    index: CellIndex,
    entry: str,
    cap: int,
) -> _Pass:
    """Iterate to a fixpoint, or to the cap if a defect keeps the state growing.

    ``accumulate`` over an endless source is lazy, so no step runs past the one
    that settles -- and ``next`` needs no default because ``dequeues`` rises by one
    per step while the queue is non-empty, so the predicate holds within ``cap``
    whether or not the fixpoint was found. Which of the two happened is read back
    off ``queue``.
    """
    start = _Pass(states=MappingProxyType({entry: EMPTY}), queue=(entry,))
    passes = accumulate(
        repeat(None), lambda run, _: _step(cfg, statements, index, run), initial=start
    )
    return next(run for run in passes if _done(run, cap))


def _definers(state: State, extent: FieldExtent, node: str) -> frozenset[str]:
    """Where the value at ``extent`` was last written, or here if nowhere was."""
    found = frozenset(source.node for source in reaching(state, extent))
    return found or frozenset({node})


def _edges_at(
    statement: Statement, node_id: str, state: State, index: CellIndex
) -> Iterator[FlowEdge]:
    return (
        FlowEdge(
            source=replace(source, node=definer), target=write.target, node=node_id
        )
        for write in writes_of(statement, node_id, index)
        for source in write.sources
        for definer in _definers(state, source.extent, node_id)
    )


def _edges(
    found: tuple[tuple[str, Statement], ...],
    states: Mapping[str, State],
    index: CellIndex,
) -> tuple[FlowEdge, ...]:
    """Every statement the CFG can reach, read once at its settled entry state."""
    return tuple(
        dict.fromkeys(
            edge
            for node_id, statement in found
            if node_id in states
            for edge in _edges_at(statement, node_id, states[node_id], index)
        )
    )


def _skip_reason(run: _Pass, cap: int, program: str, nodes: int) -> str:
    if not run.queue:
        return ""
    logger.warning(
        "fields: dequeue cap %d reached for %s (%d nodes)", cap, program, nodes
    )
    return f"dequeue cap {cap} reached"


def analyse(asg, index: CellIndex) -> ProgramFlow:
    """Every flow in one program, given an index its fields can be laid out into."""
    cfg = build_program(asg)
    statements = statement_index(asg)
    found = _statements_at(cfg, statements)
    tally = _tally(found, index)
    entry = _entry_node(asg)
    cap = ITERATION_FACTOR * max(len(cfg.nodes), 1)
    reachable = (
        _settled(cfg, statements, index, entry, cap)
        if entry in cfg.node_ids
        else _Pass(states=MappingProxyType({}), queue=())
    )
    return ProgramFlow(
        program=cfg.program,
        edges=_edges(found, reachable.states, index),
        writes=tally.writes,
        covered=tally.covered,
        unhandled=tally.unhandled,
        nodes=len(cfg.nodes),
        dequeues=reachable.dequeues,
        skipped=_skip_reason(reachable, cap, cfg.program, len(cfg.nodes)),
    )


def analysed(asg) -> tuple[ProgramFlow, CellIndex]:
    """analyse, with the index built here so an unsizeable field is a skip.

    layout raises while computing extents, which is before any statement has been
    seen, so a program that cannot be laid out has no partial answer worth
    returning -- only a recorded reason. Never silently dropped. The index that
    comes back with a skip is ``NO_INDEX``, which holds no cells.
    """
    try:
        index = cell_index(program_records(asg))
    except UnsizeableFieldError as error:
        return ProgramFlow(program=asg.program_id, skipped=str(error)), NO_INDEX
    return analyse(asg, index), index
