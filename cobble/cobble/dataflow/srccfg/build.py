"""Per-program assembly: paragraphs in declaration order, and the edges between
them.

A paragraph is lowered ONCE. Every PERFORM of it and every GO TO into it points at
the same nodes, which keeps the graph the size of the source rather than the size
of the call tree -- and means a query answers about the paragraph, not about one
inlined copy of it.

Declaration order is load-bearing twice: fall-through follows it, and so does a
PERFORM THRU range. It is never sorted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from cobble.dataflow.depgraph.flows import program_context
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node, NodeKind
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER,
    GOTO_TRANSFER,
    PERFORM_TRANSFER,
    RANGE_SEPARATOR,
    Ctx,
    lower_statements,
)
from cobble.dataflow.srccfg.synthetic import IMPLICIT_FIRST


@dataclass(frozen=True)
class ParagraphRef:
    name: str
    section: str
    statements: tuple


def label_id(name: str) -> str:
    return f"{name}#label"


def end_id(name: str) -> str:
    return f"{name}#end"


def paragraph_order(asg) -> tuple[ParagraphRef, ...]:
    """Declaration order, with a synthetic paragraph wherever statements belong to
    no paragraph -- division level, or the head of a section. That code executes,
    so it needs a name; the reserved prefix keeps the name from colliding.

    A duplicate paragraph name -- legal in COBOL when in different sections -- is
    renamed on later occurrences to keep node ids unique. The first occurrence keeps
    its name unchanged; later ones become {name}%{n} where n is 2, 3, and so on.
    Comparison is case-insensitive, matching how GO TO targets are upper-cased.
    """
    raw = (
        *_implicit(IMPLICIT_FIRST, "", asg.statements),
        *(ref for section in asg.sections for ref in _of_section(section)),
        *(_of_paragraph(paragraph, "") for paragraph in asg.paragraphs),
    )
    return _dedupe_names(raw)


def _dedupe_names(refs: tuple[ParagraphRef, ...]) -> tuple[ParagraphRef, ...]:
    """Rename duplicate paragraph names to keep node ids unique. A duplicate
    paragraph name is legal in COBOL when in different sections, but would produce
    duplicate node ids and a false graph."""
    if not refs:
        return ()
    return _scan_names(refs, 0, {})


def _scan_names(
    refs: tuple[ParagraphRef, ...], position: int, seen: Mapping[str, int]
) -> tuple[ParagraphRef, ...]:
    if position >= len(refs):
        return ()
    ref = refs[position]
    key = ref.name.upper()
    count = seen.get(key, 0) + 1
    renamed = ref.name if count == 1 else f"{ref.name}%{count}"
    updated = ParagraphRef(name=renamed, section=ref.section, statements=ref.statements)
    return (updated, *_scan_names(refs, position + 1, {**seen, key: count}))


def _of_section(section) -> tuple[ParagraphRef, ...]:
    return (
        *_implicit(f"{section.name}{IMPLICIT_FIRST}", section.name, section.statements),
        *(_of_paragraph(paragraph, section.name) for paragraph in section.paragraphs),
    )


def _implicit(name: str, section: str, statements) -> tuple[ParagraphRef, ...]:
    if not statements:
        return ()
    return (ParagraphRef(name=name, section=section, statements=tuple(statements)),)


def _of_paragraph(paragraph, section: str) -> ParagraphRef:
    return ParagraphRef(
        name=paragraph.name, section=section, statements=tuple(paragraph.statements)
    )


def _error_handlers(order: Sequence[ParagraphRef]) -> tuple[str, ...]:
    """Every handler label registered by any HANDLE CONDITION in the program."""
    return tuple(
        dict.fromkeys(
            label.upper()
            for ref in order
            for statement in ref.statements
            if str(getattr(statement, "verb", "") or "").upper() == "HANDLE CONDITION"
            for name, value in getattr(statement, "options", {}).items()
            if name.upper() not in ("NOHANDLE", "RESP", "RESP2")
            for label in (str(getattr(value, "text", "") or "").strip(),)
            if label
        )
    )


def build_program(
    asg, error_handlers: tuple[str, ...] = (), source_file: str = ""
) -> Cfg:
    order = paragraph_order(asg)
    context = program_context(asg)
    index = condition_index(asg)
    handlers = error_handlers if error_handlers else ()
    parts = tuple(
        _paragraph_cfg(ref, asg.program_id, context, index, handlers, source_file)
        for ref in order
    )
    nodes = tuple(node for part in parts for node in part[0])
    body = (*(edge for part in parts for edge in part[1]), *_fallthru(order))
    known = frozenset(node.id for node in nodes)
    perform_edges = _perform_edges(nodes, body, order)
    return Cfg(
        program=asg.program_id,
        nodes=nodes,
        edges=(
            *perform_edges,
            *body,
            *resolve_targets(nodes, known),
        ),
    )


def _paragraph_cfg(
    ref: ParagraphRef,
    program: str,
    context,
    index,
    handlers: tuple[str, ...],
    source_file: str = "",
) -> tuple[tuple[Node, ...], tuple[Edge, ...]]:
    ctx = Ctx(
        program=program,
        paragraph=ref.name,
        flows=context,
        index=index,
        error_handlers=handlers,
        source_file=source_file,
    )
    body = lower_statements(ref.statements, ctx, "")
    label = Node(id=label_id(ref.name), kind=NodeKind.LABEL, paragraph=ref.name)
    end = Node(id=end_id(ref.name), kind=NodeKind.NOP, paragraph=ref.name)
    return (
        (label, *body.nodes, end),
        (
            *body.edges,
            *_enter(label, body, end),
            *(
                Edge(source=exit_.node_id, target=end.id, kind=exit_.kind)
                for exit_ in body.exits
            ),
        ),
    )


def _enter(label: Node, body, end: Node) -> tuple[Edge, ...]:
    """An empty paragraph is still a PERFORM target and a fall-through hop, so its
    label goes straight to its end rather than the paragraph being dropped."""
    target = body.entry if body.nodes else end.id
    return (Edge(source=label.id, target=target, kind=EdgeKind.FLOW),)


def _fallthru(order: Sequence[ParagraphRef]) -> tuple[Edge, ...]:
    """Every consecutive pair, unconditionally -- the paragraph that stops is named
    in ``desugar``, not here.

    STOP RUN, GOBACK and EXIT PROGRAM lower to nodes with no exit, so the ``#end``
    of a paragraph ending in one has nothing reaching it and the edge this adds to
    the next label is dead where it should be. Deciding it here instead would mean
    asking whether the LAST statement terminates, which is the wrong question: it
    may sit in one arm of an IF with the other arm running on.
    """
    return tuple(
        Edge(
            source=end_id(current.name),
            target=label_id(nxt.name),
            kind=EdgeKind.FALLTHRU,
        )
        for current, nxt in pairwise(order)
    )


def paragraph_range(
    order: Sequence[ParagraphRef], first: str, last: str
) -> tuple[str, ...]:
    """The paragraphs a PERFORM A THRU B actually runs: everything declared between
    them. The numbering convention is not the order -- declaration order is.

    Ends the wrong way round is a source defect the compiler accepts. Widening to
    the rest of the program would swamp every query, so the range is the entry
    alone.
    """
    names = tuple(ref.name for ref in order)
    if first not in names:
        return ()
    start = names.index(first)
    if last not in names or names.index(last) < start:
        return (first,)
    return names[start : names.index(last) + 1]


def _perform_edges(
    nodes: Sequence[Node], edges: Sequence[Edge], order: Sequence[ParagraphRef]
) -> tuple[Edge, ...]:
    """A PERFORM edge into the range's first label, and a RETURN edge out of the
    range's last end into whatever the call node flows to.

    Two PERFORMs of one paragraph give it two RETURN edges. That is the deliberate
    over-approximation; pruning it needs the path, which is the reaching-conditions
    pass's business.
    """
    return tuple(
        edge
        for node in nodes
        if node.transfer == PERFORM_TRANSFER
        for edge in _one_perform(node, edges, order)
    )


def _one_perform(
    node: Node, edges: Sequence[Edge], order: Sequence[ParagraphRef]
) -> tuple[Edge, ...]:
    first, _, last = node.target.partition(RANGE_SEPARATOR)
    span = paragraph_range(order, first, last)
    if not span:
        return ()
    return (
        Edge(source=node.id, target=label_id(span[0]), kind=EdgeKind.PERFORM),
        *(
            Edge(source=end_id(span[-1]), target=flow.target, kind=EdgeKind.RETURN)
            for flow in edges
            if flow.source == node.id and flow.kind is EdgeKind.FLOW
        ),
    )


def resolve_targets(nodes: Sequence[Node], known: frozenset[str]) -> tuple[Edge, ...]:
    """GO TO nodes carry a paragraph name; here it becomes an edge to that label.

    A target the program does not declare gets NO edge: it is in an unresolved
    copybook or is a section name, and an edge to a node that does not exist would
    break every walk. The unresolved target stays on the node, so nothing is lost.

    Only nodes with transfer types GO TO or GO TO DEPENDING are resolved: later
    tasks put program names in Node.target for CALL/LINK/XCTL, and without this
    check a called program whose name happens to match a paragraph label would
    silently gain a GOTO edge into that paragraph -- a wrong edge with no error.
    """
    return tuple(
        Edge(source=node.id, target=label_id(node.target), kind=EdgeKind.GOTO)
        for node in nodes
        if node.transfer in (GOTO_TRANSFER, DISPATCH_TRANSFER)
        and node.target
        and label_id(node.target) in known
    )
