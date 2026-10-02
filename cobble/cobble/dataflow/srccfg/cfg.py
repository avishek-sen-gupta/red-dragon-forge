"""The graph vocabulary, with no knowledge of COBOL or of the ASG beyond the one
structured operand a dynamic call target carries.

Two node kinds carry meaning. A TEST holds ONE atomic predicate and has exactly
two out-edges, TRUE and FALSE; an ASSIGN holds what it writes, what it reads and
which verb transferred the data. Everything else -- LABEL, CALL, NOP -- is
plumbing that a query walks through.

That split is what removes the need for a condition language: AND and OR are
lowered into chains of TESTs by the caller, and NOT is lowered by swapping a
fragment's TRUE and FALSE exits. So a reaching condition is a path, and there is
no formula to normalise and no solver to run.

A Fragment is a partly built graph: its exits are out-edges that have no target
yet, and sequencing is the act of giving them one. Absent values are empty
tuples and empty strings throughout -- never None -- so a caller never has to
ask whether a field is there before reading it. ``Node.target_operand`` follows
the same rule with its own null object, ``NO_TARGET_OPERAND``: a dynamic call's
subscripted operand is kept structured rather than folded into ``target``'s
rendered text, so a reader of the operand never has to re-parse a subscript back
out of a string.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cached_property

from cobol_asg.ref_mod import RefModOperand


class NodeKind(Enum):
    TEST = "TEST"
    ASSIGN = "ASSIGN"
    LABEL = "LABEL"
    CALL = "CALL"
    NOP = "NOP"


class EdgeKind(Enum):
    FLOW = "FLOW"
    TRUE = "TRUE"
    FALSE = "FALSE"
    PERFORM = "PERFORM"
    RETURN = "RETURN"
    FALLTHRU = "FALLTHRU"
    GOTO = "GOTO"


@dataclass(frozen=True)
class Atom:
    """One atomic predicate: no AND, no OR, no NOT.

    ``resolved`` False means the ASG gave text this pass could not decompose, and
    the parts are empty. Such an atom still gets a TEST node, because a path
    through an unreadable predicate is a real path.
    """

    text: str
    left: str = ""
    op: str = ""
    right: str = ""
    resolved: bool = True


UNRESOLVED = Atom(text="UNRESOLVED", resolved=False)


@dataclass(frozen=True)
class SourceSpan:
    """Source location of one CFG node: lines and columns from the ASG statement."""

    line_start: int = 0
    col_start: int = 0
    line_end: int = 0
    col_end: int = 0
    source_file: str = ""


NO_SPAN = SourceSpan()

NO_TARGET_OPERAND = RefModOperand(name="")


@dataclass(frozen=True)
class Node:
    id: str
    kind: NodeKind
    paragraph: str
    atom: Atom = UNRESOLVED
    writes: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    transfer: str = ""
    target: str = ""
    target_resolved: bool = True
    target_operand: RefModOperand = NO_TARGET_OPERAND
    transfer_operand: str = ""
    using: tuple[str, ...] = ()
    span: SourceSpan = NO_SPAN
    resume: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: EdgeKind


@dataclass(frozen=True)
class Exit:
    """An out-edge with no target yet: the node it leaves and the kind it will be."""

    node_id: str
    kind: EdgeKind


@dataclass(frozen=True)
class Fragment:
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    entry: str = ""
    exits: tuple[Exit, ...] = ()


EMPTY_FRAGMENT = Fragment()


@dataclass(frozen=True)
class Cfg:
    program: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    @cached_property
    def _by_id(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    @cached_property
    def node_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    @cached_property
    def _out(self) -> dict[str, tuple[Edge, ...]]:
        return _group(self.edges, lambda edge: edge.source)

    @cached_property
    def _in(self) -> dict[str, tuple[Edge, ...]]:
        return _group(self.edges, lambda edge: edge.target)

    def node(self, node_id: str) -> Node:
        return self._by_id[node_id]

    def successors(self, node_id: str) -> tuple[Edge, ...]:
        return self._out.get(node_id, ())

    def predecessors(self, node_id: str) -> tuple[Edge, ...]:
        return self._in.get(node_id, ())


def _group(edges: Sequence[Edge], key) -> dict[str, tuple[Edge, ...]]:
    keys = tuple(dict.fromkeys(key(edge) for edge in edges))
    return {k: tuple(edge for edge in edges if key(edge) == k) for k in keys}


def merge(fragments: Sequence[Fragment]) -> Fragment:
    """Union nodes and edges, wire nothing. Used where targets are not known yet."""
    present = tuple(f for f in fragments if f.nodes or f.edges)
    if not present:
        return EMPTY_FRAGMENT
    return Fragment(
        nodes=tuple(node for f in present for node in f.nodes),
        edges=tuple(edge for f in present for edge in f.edges),
        entry=present[0].entry,
        exits=tuple(exit_ for f in present for exit_ in f.exits),
    )


def seq(fragments: Sequence[Fragment], nop_id: str) -> Fragment:
    """Chain fragments, giving every exit of each one the next one's entry.

    ``nop_id`` is reserved for callers that need a landing node when a chain has
    no statements of its own; it is unused when the chain is non-empty.
    """
    present = tuple(f for f in fragments if f is not EMPTY_FRAGMENT and f.nodes)
    if not present:
        return EMPTY_FRAGMENT
    return _fold(present[0], present[1:])


def _fold(acc: Fragment, rest: Sequence[Fragment]) -> Fragment:
    if not rest:
        return acc
    return _fold(_join(acc, rest[0]), rest[1:])


def _join(left: Fragment, right: Fragment) -> Fragment:
    return Fragment(
        nodes=(*left.nodes, *right.nodes),
        edges=(
            *left.edges,
            *right.edges,
            *(
                Edge(source=exit_.node_id, target=right.entry, kind=exit_.kind)
                for exit_ in left.exits
            ),
        ),
        entry=left.entry,
        exits=right.exits,
    )
