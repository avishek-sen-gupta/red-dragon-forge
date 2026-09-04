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

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, Node
from cobble.dataflow.srccfg.dataflow import (
    Reaching,
    base_field,
    guard_set,
    guards_of,
    writers_of,
)
from cobble.dataflow.srccfg.literals import is_literal


class Tier(IntEnum):
    SAME_STATEMENT = 1
    SAME_SOURCE = 2
    SAME_GUARD = 3
    SAME_PARAGRAPH = 4
    UNRELATED = 9


@dataclass(frozen=True)
class Candidate:
    field: str
    tier: Tier
    nodes: tuple[str, str]
    shared: tuple[str, ...] = ()


def guard_signature(
    reaching: Reaching, node_id: str
) -> frozenset[frozenset[tuple[str, EdgeKind]]]:
    """The set of guard sets reaching a node, order and duplicates discarded.

    Three values, three meanings, and they are not interchangeable. An EMPTY signature
    is no answer at all -- either the walk gave up (``abandoned``) or nothing reaches
    the node. A signature holding only the EMPTY guard set says the node is reached
    unconditionally. Anything else is a real condition. Only the third is evidence of
    anything about how a write is guarded.
    """
    return frozenset(guard_set(guard) for guard in guards_of(reaching, node_id))


def co_assigned(
    cfg: Cfg,
    field: str,
    reaching: Reaching,
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
        lambda acc, source: _folded(
            acc, _pairs(cfg, source, field, reaching, min_tier)
        ),
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


def _pairs(
    cfg: Cfg, source: Node, field: str, reaching: Reaching, min_tier: Tier
) -> tuple[Candidate, ...]:
    return tuple(
        candidate
        for other in cfg.nodes
        for candidate in _candidate(source, other, field, reaching)
        if candidate.tier <= min_tier
    )


def _candidate(
    source: Node, other: Node, field: str, reaching: Reaching
) -> tuple[Candidate, ...]:
    written = tuple(
        name for name in other.writes if base_field(name) != base_field(field)
    )
    tier = _tier(source, other, reaching)
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


def _tier(source: Node, other: Node, reaching: Reaching) -> Tier:
    same_paragraph = other.paragraph == source.paragraph
    if source.id == other.id:
        return Tier.SAME_STATEMENT
    if same_paragraph and _shared(source, other):
        return Tier.SAME_SOURCE
    if not same_paragraph and _same_guard(reaching, source.id, other.id):
        return Tier.SAME_GUARD
    return Tier.SAME_PARAGRAPH if same_paragraph else Tier.UNRELATED


def _same_guard(reaching: Reaching, source_id: str, other_id: str) -> bool:
    """Whether two writes in different paragraphs are guarded by the same conditions.

    Equality of signatures is not enough, because two of the three signature values
    mean "there is nothing here to match". Two nodes the walk abandoned both have the
    empty signature, so comparing raw equality turned the absence of an answer into
    tier-3 evidence -- the strongest tier this relation offers, awarded for knowing
    nothing. Two unconditional writes match just as vacuously: being written under no
    condition at all is not something a pair of fields shares, it is the default, and
    every unconditional write in the program would pair with every other.

    So a real condition on at least one path is required before equality is consulted.
    R79/R82 keep this restricted to different-paragraph pairs; that is untouched.
    """
    signature = guard_signature(reaching, source_id)
    return any(signature) and signature == guard_signature(reaching, other_id)


def _shared(source: Node, other: Node) -> tuple[str, ...]:
    common = set(source.reads) & set(other.reads)
    filtered = tuple(sorted(name for name in common if not is_literal(name)))
    return filtered


NO_ROUTE = "no guards found by the walk, so no tier-3 comparison was made for it"
SUBSET = "guards are a subset of the real ones, so a tier-3 match is not established"


@dataclass(frozen=True)
class Caveat:
    """A writer of the queried field whose guards do not support a tier-3 answer."""

    node: str
    reason: str


def caveats(cfg: Cfg, field: str, reaching: Reaching) -> tuple[Caveat, ...]:
    """Why a SAME_GUARD answer about this field may be missing or unproven.

    Declining to compare is the right call and a silent one: the reader sees a shorter
    candidate list and no reason to doubt it, which is a partial answer wearing the
    shape of a complete one. Naming the writer and the reason is what makes the gap a
    finding rather than a nothing.
    """
    return tuple(
        Caveat(node=node_id, reason=reason)
        for node_id in writers_of(cfg, field)
        for reason in (_caveat(reaching, node_id),)
        if reason
    )


def _caveat(reaching: Reaching, node_id: str) -> str:
    """``abandoned`` first: it is the stronger statement, and the two overlap."""
    if node_id in reaching.abandoned:
        return NO_ROUTE
    if node_id in reaching.truncated:
        return SUBSET
    return ""
