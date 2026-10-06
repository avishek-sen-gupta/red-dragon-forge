"""The fixpoint's CFG, less the fall-throughs only a returning PERFORM reaches."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import accumulate, permutations, repeat

from cobble.dataflow.srccfg.build import ParagraphRef, label_id
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Node
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER_CICS,
    GOTO_TRANSFER,
    PERFORM_TRANSFER,
)

ALTER_TRANSFER = "ALTER"
NOWHERE = ""
NOT_FOLLOWED = frozenset({EdgeKind.PERFORM, EdgeKind.RETURN})

Unresolved = Callable[[Node, frozenset[EdgeKind]], bool]

UNRESOLVED_WHEN: Mapping[str, Unresolved] = {
    GOTO_TRANSFER: lambda node, kinds: EdgeKind.GOTO not in kinds,
    PERFORM_TRANSFER: lambda node, kinds: EdgeKind.PERFORM not in kinds,
    ALTER_TRANSFER: lambda node, kinds: True,
    DISPATCH_TRANSFER_CICS: lambda node, kinds: bool(node.target),
}


@dataclass(frozen=True)
class _Activation:
    """One PERFORM range: the label it enters at and the end it returns from."""

    entry: str
    closing: str


@dataclass(frozen=True)
class _Reach:
    """The nodes a walk has reached, and those it reached on its latest step."""

    seen: frozenset[str]
    frontier: frozenset[str]


@dataclass(frozen=True)
class _Span:
    """Declaration-order positions of a range's first and last paragraph."""

    first: int
    last: int


def fallthroughs_pruned(cfg: Cfg, order: Sequence[ParagraphRef]) -> Cfg:
    if not order or _unresolved(cfg):
        return cfg
    kept = _falling(cfg, order)
    return replace(
        cfg,
        edges=tuple(
            edge
            for edge in cfg.edges
            if edge.kind is not EdgeKind.FALLTHRU or edge.source in kept
        ),
    )


def _unresolved(cfg: Cfg) -> bool:
    return any(
        UNRESOLVED_WHEN.get(node.transfer, _resolved)(
            node, frozenset(edge.kind for edge in cfg.successors(node.id))
        )
        for node in cfg.nodes
    )


def _resolved(node: Node, kinds: frozenset[EdgeKind]) -> bool:
    return False


def _falling(cfg: Cfg, order: Sequence[ParagraphRef]) -> frozenset[str]:
    activations = _activations(cfg)
    return frozenset[str]().union(
        _reached(cfg, label_id(order[0].name), NOWHERE),
        *(
            _reached(cfg, activation.entry, activation.closing) - {activation.closing}
            for activation in activations
        ),
        _overlapped(cfg, order, activations),
    )


def _activations(cfg: Cfg) -> frozenset[_Activation]:
    return frozenset(
        _Activation(entry=edge.target, closing=node.range_end)
        for node in cfg.nodes
        for edge in cfg.successors(node.id)
        if edge.kind is EdgeKind.PERFORM
    )


def _reached(cfg: Cfg, start: str, closing: str) -> frozenset[str]:
    steps = accumulate(
        repeat(None),
        lambda reach, _: _step(cfg, reach, closing),
        initial=_Reach(seen=frozenset({start}), frontier=frozenset({start})),
    )
    return next(reach.seen for reach in steps if not reach.frontier)


def _step(cfg: Cfg, reach: _Reach, closing: str) -> _Reach:
    found = (
        frozenset(
            target
            for node_id in reach.frontier
            for target in _onward(cfg, node_id, closing)
        )
        - reach.seen
    )
    return _Reach(seen=reach.seen | found, frontier=found)


def _onward(cfg: Cfg, node_id: str, closing: str) -> tuple[str, ...]:
    if node_id == closing:
        return ()
    resume = cfg.node(node_id).resume
    return (
        *(
            edge.target
            for edge in cfg.successors(node_id)
            if edge.kind not in NOT_FOLLOWED
        ),
        *((resume,) if resume else ()),
    )


def _overlapped(
    cfg: Cfg, order: Sequence[ParagraphRef], activations: frozenset[_Activation]
) -> frozenset[str]:
    starts, ends = _starts(order), _ends(order)
    spans = frozenset(
        _Span(
            first=starts[cfg.node(activation.entry).paragraph],
            last=ends[cfg.node(activation.closing).paragraph],
        )
        for activation in activations
    )
    overlaps = tuple(
        _Span(first=later.first, last=earlier.last)
        for earlier, later in permutations(spans, 2)
        if earlier.first < later.first <= earlier.last < later.last
    )
    return frozenset(
        edge.source
        for edge in cfg.edges
        if edge.kind is EdgeKind.FALLTHRU
        and any(
            span.first <= ends[cfg.node(edge.source).paragraph] <= span.last
            for span in overlaps
        )
    )


def _starts(order: Sequence[ParagraphRef]) -> Mapping[str, int]:
    return {
        **{
            ref.section: at
            for at, ref in reversed(tuple(enumerate(order)))
            if ref.section
        },
        **{ref.name: at for at, ref in enumerate(order)},
    }


def _ends(order: Sequence[ParagraphRef]) -> Mapping[str, int]:
    return {
        **{ref.section: at for at, ref in enumerate(order) if ref.section},
        **{ref.name: at for at, ref in enumerate(order)},
    }
