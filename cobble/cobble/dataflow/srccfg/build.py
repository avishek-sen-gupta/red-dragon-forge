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
from dataclasses import replace
from itertools import pairwise
from types import MappingProxyType

from cobble.dataflow.depgraph.flows import program_context
from cobble.dataflow.srccfg.cfg import (
    Cfg,
    Edge,
    EdgeKind,
    Fragment,
    Node,
    NodeKind,
    SourceSpan,
    seq,
    span_of,
)
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.paragraphs import (
    ParagraphRef,
    end_id,
    label_id,
    paragraph_order,
    sentence_end_id,
)
from cobble.dataflow.srccfg.section_span import SectionSpan
from cobble.dataflow.srccfg.whenever import Governing, governing_directives

__all__ = [
    "ParagraphRef",
    "build_program",
    "end_id",
    "label_id",
    "paragraph_order",
]
from cobble.dataflow.srccfg.desugar import (
    DISPATCH_TRANSFER,
    GOTO_TRANSFER,
    PERFORM_TRANSFER,
    RANGE_SEPARATOR,
    Ctx,
    landed,
    lower_statements,
    node_id,
)


def build_program(asg, source_file: str = "") -> Cfg:
    order = paragraph_order(asg)
    nodes, body = _lowered(asg, order, source_file)
    resumes = _resumes(nodes, body, order)
    ends = _closing_ends(nodes, order)
    return Cfg(
        program=asg.program_id,
        nodes=tuple(_annotated(node, resumes, ends) for node in nodes),
        edges=(
            *_perform_edges(nodes, body, order),
            *(edge for edge in body if not _skips_range(edge, resumes)),
            *resolve_targets(nodes, frozenset(node.id for node in nodes)),
        ),
    )


def _lowered(
    asg, order: Sequence[ParagraphRef], source_file: str
) -> tuple[tuple[Node, ...], tuple[Edge, ...]]:
    """Every paragraph and section, lowered, and the edges that hold them together --
    everything but where PERFORMs and GO TOs land."""
    context = program_context(asg)
    index = condition_index(asg)
    governing = governing_directives(asg)
    parts = tuple(
        _paragraph_cfg(ref, asg.program_id, context, index, source_file, governing)
        for ref in order
    )
    spans = _section_spans(
        order,
        {
            section.name.upper(): span_of(section, source_file)
            for section in asg.sections
        },
    )
    return (
        (*(node for part in parts for node in part[0]), *_section_nodes(spans)),
        (
            *(edge for part in parts for edge in part[1]),
            *_section_edges(spans),
            *_fallthru(order),
        ),
    )


def _resumes(
    nodes: Sequence[Node], body: Sequence[Edge], order: Sequence[ParagraphRef]
) -> Mapping[str, str]:
    """Each PERFORM that can return, and where it continues once it does: the FLOW
    edge lowering gave it, which the RETURN edges were placed by.

    The range always runs, so for a PERFORM that returns that edge is not a path -- a
    walk taking it would skip the paragraphs. It becomes the node's ``resume``
    instead. Two kinds keep the edge. A PERFORM whose range does not resolve has no
    other way on. And one whose range end nothing reaches can never return, so the
    statement after it is dead by the graph's account -- but the graph can be wrong
    (an ALTERed GO TO, control flow the parse dropped), and dead code loses every flow
    after it, so the edge stays as the deliberate over-approximation.
    """
    reached = frozenset(edge.target for edge in body)
    returning = frozenset(
        node.id
        for node in nodes
        if node.transfer == PERFORM_TRANSFER
        for ends in (_range_ends(node, order),)
        if ends and ends[1] in reached
    )
    return {
        edge.source: edge.target
        for edge in body
        if edge.kind is EdgeKind.FLOW and edge.source in returning
    }


def _closing_ends(
    nodes: Sequence[Node], order: Sequence[ParagraphRef]
) -> Mapping[str, str]:
    """Each PERFORM whose range resolves, and the range end its RETURN leaves from.

    Two PERFORMs can resume at one statement -- the two arms of an IF -- so the
    resume point alone does not say which RETURN is whose. The end it leaves from
    does, and only the build knows it without decoding the target's text."""
    return {
        node.id: ends[1]
        for node in nodes
        if node.transfer == PERFORM_TRANSFER
        for ends in (_range_ends(node, order),)
        if ends
    }


def _annotated(node: Node, resumes: Mapping[str, str], ends: Mapping[str, str]) -> Node:
    if node.id not in ends:
        return node
    return replace(node, resume=resumes.get(node.id, ""), range_end=ends[node.id])


def _skips_range(edge: Edge, resumes: Mapping[str, str]) -> bool:
    return edge.kind is EdgeKind.FLOW and edge.source in resumes


def _paragraph_cfg(
    ref: ParagraphRef,
    program: str,
    context,
    index,
    source_file: str = "",
    governing: Mapping[str, Governing] = MappingProxyType({}),
) -> tuple[tuple[Node, ...], tuple[Edge, ...]]:
    ctx = Ctx(
        program=program,
        paragraph=ref.name,
        flows=context,
        index=index,
        source_file=source_file,
        section=ref.section,
        whenever=governing,
    )
    body = seq(
        tuple(
            _sentence(ref, ctx, position, first, statements)
            for position, (first, statements) in enumerate(_sentences(ref))
        ),
        nop_id=node_id(ctx, "empty"),
    )
    located = replace(ref.span, source_file=source_file)
    label = Node(
        id=label_id(ref.name), kind=NodeKind.LABEL, paragraph=ref.name, span=located
    )
    end = Node(id=end_id(ref.name), kind=NodeKind.NOP, paragraph=ref.name, span=located)
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
    in ``desugar``, not here. Across a section boundary the edge runs from the
    section's end, or into the next section's label.

    STOP RUN, GOBACK and EXIT PROGRAM lower to nodes with no exit, so the ``#end``
    of a paragraph ending in one has nothing reaching it and the edge this adds to
    the next label is dead where it should be. Deciding it here instead would mean
    asking whether the LAST statement terminates, which is the wrong question: it
    may sit in one arm of an IF with the other arm running on.
    """
    return tuple(
        Edge(
            source=_leaving(current, nxt),
            target=_entering(current, nxt),
            kind=EdgeKind.FALLTHRU,
        )
        for current, nxt in pairwise(order)
    )


def _leaving(current: ParagraphRef, nxt: ParagraphRef) -> str:
    if current.section and current.section != nxt.section:
        return end_id(current.section)
    return end_id(current.name)


def _entering(current: ParagraphRef, nxt: ParagraphRef) -> str:
    if nxt.section and nxt.section != current.section:
        return label_id(nxt.section)
    return label_id(nxt.name)


def _section_spans(
    order: Sequence[ParagraphRef], located: Mapping[str, SourceSpan]
) -> tuple[SectionSpan, ...]:
    sections = tuple(dict.fromkeys(ref.section for ref in order if ref.section))
    return tuple(
        SectionSpan(
            section=section,
            first=next(ref.name for ref in order if ref.section == section),
            last=next(ref.name for ref in reversed(order) if ref.section == section),
            span=located[section],
        )
        for section in sections
    )


def _section_nodes(spans: Sequence[SectionSpan]) -> tuple[Node, ...]:
    """A label and an end per section, as a paragraph has: what PERFORM, GO TO and a
    WHENEVER's GO TO land on when they name a section, and where a PERFORM of one
    returns from."""
    return tuple(
        node
        for span in spans
        for node in (
            Node(
                id=label_id(span.section),
                kind=NodeKind.LABEL,
                paragraph=span.section,
                span=span.span,
            ),
            Node(
                id=end_id(span.section),
                kind=NodeKind.NOP,
                paragraph=span.section,
                span=span.span,
            ),
        )
    )


def _section_edges(spans: Sequence[SectionSpan]) -> tuple[Edge, ...]:
    return tuple(
        edge
        for span in spans
        for edge in (
            Edge(
                source=label_id(span.section),
                target=label_id(span.first),
                kind=EdgeKind.FLOW,
            ),
            Edge(
                source=end_id(span.last),
                target=end_id(span.section),
                kind=EdgeKind.FLOW,
            ),
        )
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
    starts = _starts(order)
    if first not in starts:
        return ()
    return names[starts[first] : _ends(order)[_closing(order, first, last)] + 1]


def _starts(order: Sequence[ParagraphRef]) -> Mapping[str, int]:
    """Where each name's range begins: a paragraph at itself, a section at its first
    paragraph."""
    return {
        **{
            ref.section: at
            for at, ref in reversed(tuple(enumerate(order)))
            if ref.section
        },
        **{ref.name: at for at, ref in enumerate(order)},
    }


def _ends(order: Sequence[ParagraphRef]) -> Mapping[str, int]:
    """Where each name's range ends: a paragraph at itself, a section at its last."""
    return {
        **{ref.section: at for at, ref in enumerate(order) if ref.section},
        **{ref.name: at for at, ref in enumerate(order)},
    }


def _closing(order: Sequence[ParagraphRef], first: str, last: str) -> str:
    """The name whose end the range stops at: ``last``, unless it is absent or
    declared before ``first``."""
    ends = _ends(order)
    return last if last in ends and ends[last] >= _starts(order)[first] else first


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
    ends = _range_ends(node, order)
    if not ends:
        return ()
    entry, leaving = ends
    return (
        Edge(source=node.id, target=entry, kind=EdgeKind.PERFORM),
        *(
            Edge(source=leaving, target=flow.target, kind=EdgeKind.RETURN)
            for flow in edges
            if flow.source == node.id and flow.kind is EdgeKind.FLOW
        ),
    )


def _range_ends(node: Node, order: Sequence[ParagraphRef]) -> tuple[str, ...]:
    """The node a PERFORM enters its range at and the one it returns from, or
    nothing when the range does not resolve."""
    first, _, last = node.target.partition(RANGE_SEPARATOR)
    span = paragraph_range(order, first, last)
    if not span:
        return ()
    sections = frozenset(ref.section for ref in order if ref.section)
    closing = _closing(order, first, last)
    return (
        label_id(first) if first in sections else label_id(span[0]),
        end_id(closing) if closing in sections else end_id(span[-1]),
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


def _sentences(ref: ParagraphRef) -> tuple[tuple[int, tuple], ...]:
    """Each sentence's first position and statements; one sentence when the ASG
    records none, as a synthetic paragraph does."""
    ends = ref.sentence_ends or (len(ref.statements) - 1,)
    firsts = (0, *(end + 1 for end in ends[:-1]))
    return tuple(
        (first, ref.statements[first : end + 1])
        for first, end in zip(firsts, ends, strict=True)
    )


def _sentence(
    ref: ParagraphRef, ctx: Ctx, position: int, first: int, statements: tuple
) -> Fragment:
    """One sentence, and the node after its period when a NEXT SENTENCE in it
    jumps there -- only then, so a program without one builds unchanged."""
    end = sentence_end_id(ref.name, position)
    body = lower_statements(statements, replace(ctx, sentence=end), "", first)
    return landed(body, end, ref.name, replace(ref.span, source_file=ctx.source_file))
