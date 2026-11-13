"""Def-use over the CFG: reaching definitions, the writers and readers of a field,
and the HANDLE CONDITION handlers a CICS command can reach, added to the CFG as edges.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from functools import reduce
from itertools import groupby
from operator import itemgetter, or_

from cobble.dataflow.srccfg.build import label_id
from cobble.dataflow.srccfg.cfg import (
    Atom,
    Cfg,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
)
from cobble.dataflow.srccfg.conditions import VALUE_OPS
from cobble.dataflow.srccfg.desugar import DISPATCH_TRANSFER_CICS
from cobble.dataflow.srccfg.read import names_of
from cobble.dataflow.srccfg.synthetic import (
    HANDLER_PREFIX,
    IGNORED,
    SYSTEM_DEFAULT,
    is_synthetic,
)
from cobble.dataflow.srccfg.worklist import out_masks


@dataclass(frozen=True)
class Definition:
    """One write: the node that did it and the field it wrote.

    field is the literal write text, subscript and reference modification included
    (e.g., 'WS-TAB(1)', 'WS-FIELD(1:4)'). Match with base_field rather than == if
    you need to find all writes to a base name."""

    node: str
    field: str


Defs = frozenset[Definition]

HANDLER_SEPARATOR = ", "


def base_field(field: str) -> str:
    """The base name: strip subscripts and reference modification.

    'WS-TAB(1)' -> 'WS-TAB', 'WS-FIELD(1:4)' -> 'WS-FIELD', 'WS-X' -> 'WS-X'.
    Use this to match definitions by base name when querying reaching_definitions."""
    paren = field.find("(")
    return field[:paren] if paren >= 0 else field


def definitions_of(cfg: Cfg) -> Mapping[str, Defs]:
    """The gen set: what each node writes."""
    return {
        node.id: frozenset(Definition(node=node.id, field=name) for name in node.writes)
        for node in cfg.nodes
    }


def _def_index(cfg: Cfg) -> tuple[Definition, ...]:
    """All definitions in declaration order — the bitmask's bit layout."""
    return tuple(
        Definition(node=node.id, field=name)
        for node in cfg.nodes
        for name in node.writes
    )


def _gen_mask(defs: frozenset[Definition], index: Mapping[Definition, int]) -> int:
    return sum(1 << index[d] for d in defs if d in index)


def _reaching_masks(
    cfg: Cfg, wanted: Callable[[str], bool]
) -> tuple[Mapping[str, int], tuple[Definition, ...]]:
    """Each node's IN set as a bitmask over the definitions of ``wanted`` fields.

    Kills are per field, so the definitions of one set of fields reach exactly as
    they would among every definition: leaving the rest out changes nothing for
    these, and costs nothing for the others.
    """
    all_defs = tuple(d for d in _def_index(cfg) if wanted(d.field))
    idx: dict[Definition, int] = {d: i for i, d in enumerate(all_defs)}
    generated = {
        node_id: frozenset(d for d in defs if d in idx)
        for node_id, defs in definitions_of(cfg).items()
    }
    gen_masks: dict[str, int] = {
        node_id: reduce(or_, (1 << idx[d] for d in defs), 0)
        for node_id, defs in generated.items()
    }
    field_to_mask: dict[str, int] = {
        field: reduce(or_, (1 << position for _field, position in group), 0)
        for field, group in groupby(
            sorted((d.field, position) for position, d in enumerate(all_defs)),
            itemgetter(0),
        )
    }
    kill_masks: dict[str, int] = {
        node_id: reduce(or_, (field_to_mask.get(d.field, 0) for d in defs), 0)
        for node_id, defs in generated.items()
    }
    outs = out_masks(cfg, gen_masks, kill_masks)
    in_masks = {
        node.id: reduce(or_, (outs[e.source] for e in cfg.predecessors(node.id)), 0)
        for node in cfg.nodes
    }
    return in_masks, all_defs


def _defs_in(mask: int, all_defs: tuple[Definition, ...]) -> Defs:
    return frozenset(
        all_defs[position]
        for position, bit in enumerate(reversed(bin(mask)[2:]))
        if bit == "1"
    )


def reaching_definitions(cfg: Cfg) -> Mapping[str, Defs]:
    """A gen/kill fixpoint using integer bitmasks.

    Each Defs set is represented as a Python int where bit k is set when
    Definition k is present.  Union becomes ``|``, comparison becomes ``==``,
    and gen/kill becomes ``(in_mask & ~kill_mask) | gen_mask`` — word
    operations rather than per-element Python object allocations.
    """
    in_masks, all_defs = _reaching_masks(cfg, lambda field: True)
    return {node_id: _defs_in(mask, all_defs) for node_id, mask in in_masks.items()}


def writers_of(cfg: Cfg, field: str) -> tuple[str, ...]:
    """Every node that writes this field, in source order.

    Matches on both exact field name and base name: writers_of("WS-TAB") returns nodes
    writing WS-TAB, WS-TAB(1), WS-TAB(WS-I), and WS-TAB(1:4). A subscripted query is
    answered by base name, so writers_of("WS-TAB(1)") also returns nodes writing WS-TAB(2).
    """
    base = base_field(field)
    return tuple(
        node.id
        for node in cfg.nodes
        if any(base_field(name) == base for name in node.writes)
    )


def condition_operands(atom: Atom) -> tuple[str, ...]:
    """The fields one guard step examines, and only the fields.

    ``atom.right`` is a second operand for a relation between two things and a VALUE
    for everything else -- a class name for IS NUMERIC, an 88's list of values for IN,
    the keyword RAISED for the handler test. Harvesting those reports ``NUMERIC`` and
    ``RAISED`` as fields the member never wrote, which spends the credibility of that
    line where it is genuinely true, as it is for a commarea or a file-read source.

    A synthetic left-hand side is the same case reached differently: the right of
    ``%HANDLER[ANY] RAISED`` or ``%IOSTATUS[F] == AT END`` is the state being tested
    for, not a field. The left IS kept -- whatever the test guards does depend on it --
    and the caller then labels it rather than claiming the member never wrote it.
    """
    if atom.op in VALUE_OPS or is_synthetic(atom.left):
        return (atom.left,)
    return (atom.left, atom.right)


def readers_of(cfg: Cfg, field: str) -> tuple[str, ...]:
    """Every node that reads this field, in source order.

    The mirror of ``writers_of``, and it has to look in two places to be one. An
    ASSIGN records its read operands in ``node.reads``, but a TEST holds the field it
    examines in its atom -- so a field that only ever decides a branch reads as unused
    when ``node.reads`` is the whole search, which is the opposite of true. Base-name
    matched, like ``writers_of``: a read of ``WS-TAB(1)`` answers a query for ``WS-TAB``.
    """
    base = base_field(field)
    return tuple(node.id for node in cfg.nodes if base in _read_bases(node))


def _read_bases(node: Node) -> frozenset[str]:
    examined = condition_operands(node.atom) if node.kind is NodeKind.TEST else ()
    return frozenset(
        base_field(name) for name in (*names_of(node.reads), *examined) if name
    )


def live_handlers(cfg: Cfg) -> Mapping[str, tuple[str, ...]]:
    """The paragraphs a raise at each dispatch node can reach.

    Any %HANDLER[...] definition reaching the dispatch is a candidate, whatever the
    condition: the dispatch reads %HANDLER[ANY] because the CFG does not model which
    condition a command raises."""
    dispatches = tuple(
        node for node in cfg.nodes if node.transfer == DISPATCH_TRANSFER_CICS
    )
    if not dispatches:
        return {}
    in_masks, handler_defs = _reaching_masks(
        cfg, lambda field: field.startswith(HANDLER_PREFIX)
    )
    return {
        node.id: _targets(cfg, _defs_in(in_masks[node.id], handler_defs))
        for node in dispatches
    }


def _targets(cfg: Cfg, definitions: Defs) -> tuple[str, ...]:
    """The paragraph names to which a dispatch can transfer.

    Over-approximates: takes every read from any node holding a surviving handler
    definition. So HANDLE CONDITION MAPFAIL(H-M) ERROR(H-E) followed by HANDLE
    CONDITION MAPFAIL(H-M2) yields H-E, H-M, H-M2 even though H-M was killed. The
    alternative -- pairing writes[i] with reads[i] positionally -- breaks the moment
    Task 10's _dedupe collapses two conditions armed to the same paragraph, or anything
    else re-orders the node's field lists. Over-approximating a handler target is safe;
    silently dropping one is not."""
    return tuple(
        sorted(
            {
                value
                for definition in definitions
                if definition.field.startswith(HANDLER_PREFIX)
                for value in names_of(cfg.node(definition.node).reads)
                if value not in (IGNORED, SYSTEM_DEFAULT)
            }
        )
    )


def with_handler_edges(cfg: Cfg) -> Cfg:
    """Resolve every dispatch node, so a walk reaches the handler paragraph and an
    assignment there carries the guard of the command that raised.

    Unresolvable handler targets (armed but the paragraph does not exist) are kept
    visible on the dispatch node's target field rather than silently dropped.

    Applying this twice is applying it once: the edges it would add a second time are
    already present and are filtered out. It runs in the corpus build, so a consumer
    that reads an artefact and applies it again -- reasonably, having no way to know --
    must not end up with a doubled GOTO out of every dispatch, which would double the
    paths out of it and bring the guard cap down that much sooner."""
    handlers = live_handlers(cfg)
    added = tuple(
        edge
        for node_id, targets in handlers.items()
        for target in targets
        if label_id(target) in cfg.node_ids
        for edge in (Edge(source=node_id, target=label_id(target), kind=EdgeKind.GOTO),)
        if edge not in cfg.edges
    )
    unresolved_by_node = {
        node_id: tuple(t for t in targets if label_id(t) not in cfg.node_ids)
        for node_id, targets in handlers.items()
    }
    updated_nodes = tuple(
        (
            node
            if node.id not in unresolved_by_node or not unresolved_by_node[node.id]
            else replace(
                node, target=HANDLER_SEPARATOR.join(unresolved_by_node[node.id])
            )
        )
        for node in cfg.nodes
    )
    return (
        cfg
        if not added and not any(unresolved_by_node.values())
        else Cfg(
            program=cfg.program,
            nodes=updated_nodes,
            edges=(*cfg.edges, *added),
            entry=cfg.entry,
        )
    )
