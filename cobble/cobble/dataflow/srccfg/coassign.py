"""Co-assignment: which fields are written together with this one.

A query-time relation, in tiers, because the strong evidence is rare and the weak
evidence is everywhere. Storing one blended answer would hide which kind a given
candidate rests on -- and the weak tier is exactly the one a reader must be able to
discount.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from functools import reduce

from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.dataflow import base_field, writers_of
from cobble.dataflow.srccfg.literals import is_literal
from cobble.dataflow.srccfg.read import copied_names


class Tier(IntEnum):
    SAME_STATEMENT = 1
    SAME_SOURCE = 2
    SAME_PARAGRAPH = 3
    UNRELATED = 9


@dataclass(frozen=True)
class Candidate:
    field: str
    tier: Tier
    nodes: tuple[str, str]
    shared: tuple[str, ...] = ()


def co_assigned(
    cfg: Cfg,
    field: str,
    min_tier: Tier = Tier.SAME_PARAGRAPH,
) -> tuple[Candidate, ...]:
    """The fields written together with this one, best tier per field.

    Writers are found through ``writers_of``, which is what every other query in this
    package uses, so a query for WS-TAB finds the writes of WS-TAB(1) here as it does
    there. Matching on the exact spelling meant a subscripted write was a co-assignment
    for nobody, and the same field name answered two questions two ways -- with nothing
    in either report to say which rule had been applied.
    """
    writers = tuple(cfg.node(node_id) for node_id in writers_of(cfg, field))
    best = reduce(
        lambda acc, source: _folded(acc, _pairs(cfg, source, field, min_tier)),
        writers,
        {},
    )
    return tuple(sorted(best.values(), key=lambda c: (c.tier, c.field)))


def _better(existing: Candidate, found: Candidate) -> Candidate:
    return existing if existing.tier < found.tier else found


def _folded(
    best: Mapping[str, Candidate], found: tuple[Candidate, ...]
) -> dict[str, Candidate]:
    return {
        **best,
        **{
            candidate.field: (
                _better(best[candidate.field], candidate)
                if candidate.field in best
                else candidate
            )
            for candidate in found
        },
    }


def _pairs(cfg: Cfg, source: Node, field: str, min_tier: Tier) -> tuple[Candidate, ...]:
    return tuple(
        candidate
        for other in cfg.nodes
        for candidate in _candidate(source, other, field)
        if candidate.tier <= min_tier
    )


def _candidate(source: Node, other: Node, field: str) -> tuple[Candidate, ...]:
    written = tuple(
        name for name in other.writes if base_field(name) != base_field(field)
    )
    tier = _tier(source, other)
    return tuple(
        Candidate(
            field=name,
            tier=tier,
            nodes=(source.id, other.id),
            shared=_shared(source, other),
        )
        for name in written
        if tier != Tier.UNRELATED
    )


def _tier(source: Node, other: Node) -> Tier:
    if source.id == other.id:
        return Tier.SAME_STATEMENT
    if other.paragraph == source.paragraph:
        return _in_paragraph(source, other)
    return Tier.UNRELATED


def _in_paragraph(source: Node, other: Node) -> Tier:
    return Tier.SAME_SOURCE if _shared(source, other) else Tier.SAME_PARAGRAPH


def _shared(source: Node, other: Node) -> tuple[str, ...]:
    common = set(copied_names(source.reads)) & set(copied_names(other.reads))
    filtered = tuple(sorted(name for name in common if not is_literal(name)))
    return filtered
