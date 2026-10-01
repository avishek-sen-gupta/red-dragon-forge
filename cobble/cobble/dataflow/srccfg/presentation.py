"""What a CFG node is called, and which CALLs resolve inside a bundle.

Shared by every renderer, and shared rather than copied for one reason: two pictures
of the same program that label a node differently are two pictures of different
programs. Colour and shape are not here -- those are each renderer's own, because a
graphviz fill and a WebGL node colour answer to different backgrounds.

The label of each kind is the thing a reader is looking for when they find that node
on the page: a TEST's predicate, what an ASSIGN writes and the verb that wrote it, a
CALL's target, a paragraph's name. A NOP has nothing to say about itself and falls
back to its id, because a blank node reads as a bug in the drawing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Cfg, Node, NodeKind
from cobble.dataflow.srccfg.link import BundleCall, bundle_calls

QUALIFIER = "::"


def qualified(program: str, node_id: str) -> str:
    """The node id a picture can use: every member of a corpus has a MAIN/0."""
    return f"{program}{QUALIFIER}{node_id}"


def _test_label(node: Node) -> str:
    return node.atom.text


def _assign_label(node: Node) -> str:
    return " ".join(part for part in (node.transfer, *node.writes) if part)


def _call_label(node: Node) -> str:
    return " ".join(part for part in (node.transfer, node.target) if part)


def _paragraph_label(node: Node) -> str:
    return node.paragraph


def _id_label(node: Node) -> str:
    return node.id


LABELS: Mapping[NodeKind, Callable[[Node], str]] = {
    NodeKind.TEST: _test_label,
    NodeKind.ASSIGN: _assign_label,
    NodeKind.CALL: _call_label,
    NodeKind.LABEL: _paragraph_label,
    NodeKind.NOP: _id_label,
}


def label_of(node: Node) -> str:
    """The node's text, never empty: an unnamed paragraph still reads as its id."""
    return LABELS[node.kind](node) or node.id


@dataclass(frozen=True)
class CrossCall:
    """One CALL that lands inside the bundle: the edge a closure is drawn for.

    Both ends are qualified ids, so a renderer joins them without knowing which
    program either belongs to.
    """

    source: str
    target: str
    transfer: str
    certain: bool = True


def call_nodes(cfg: Cfg) -> tuple[Node, ...]:
    return tuple(node for node in cfg.nodes if node.kind is NodeKind.CALL)


def cross_calls(
    cfgs: Sequence[Cfg], calls: Sequence[BundleCall] = ()
) -> tuple[CrossCall, ...]:
    """The file's own calls, derived from the CFGs when it carries none.

    A single member has no cross-program calls to record and writes ``[]``, and a
    drawing of it still has to show what its CALL sites reach -- the alternative is a
    row of disconnected islands, which is the one thing the picture must not show.
    """
    return _drawable(cfgs, calls) if calls else resolved_calls(cfgs)


def resolved_calls(cfgs: Sequence[Cfg]) -> tuple[CrossCall, ...]:
    """Every CALL whose target is a program in this bundle, derived from the CFGs."""
    return _drawable(cfgs, bundle_calls(cfgs))


def _drawable(
    cfgs: Sequence[Cfg], calls: Sequence[BundleCall]
) -> tuple[CrossCall, ...]:
    """The calls that join two programs drawn here, and only those.

    A call with no entry -- a dynamic site nothing answered, or a callee not in this
    drawing -- yields nothing: an edge to a node that does not exist draws a program
    that looks built and is not. A dynamic site's candidates are drawn, each saying
    whether it is certain, so a doubtful hop is visible as one.
    """
    drawn = {cfg.program for cfg in cfgs}
    return tuple(
        CrossCall(
            source=qualified(call.caller, call.node),
            target=qualified(call.program, call.entry),
            transfer=call.transfer,
            certain=call.certain,
        )
        for call in calls
        if call.entry and {call.caller, call.program} <= drawn
    )
