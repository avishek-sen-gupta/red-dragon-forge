"""Programs joined by every call that could link them: the groups combine links one at a time."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from itertools import chain
from pathlib import Path

import networkx as nx
from cobble.dataflow.combine.jump_names import JumpNames
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.dataflow.jumps.jump_kind import JumpKind

_Pair = tuple[str, str]
_BY_NAME = frozenset({JumpKind.XCTL, JumpKind.LINK, JumpKind.CALL})
_BY_TRANSACTION = frozenset({JumpKind.RETURN_TRANSID, JumpKind.START})


def _lines(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8") as rows:
        yield from (line for line in rows if line.strip())


def _named(jump: JumpNames, transactions: Mapping[str, str]) -> tuple[str, ...]:
    if jump.kind in _BY_NAME:
        return tuple(value.rstrip() for value in jump.target.values)
    if jump.kind in _BY_TRANSACTION:
        return tuple(
            transactions[value.rstrip()]
            for value in jump.transid.values
            if value.rstrip() in transactions
        )
    return ()


def _jumped(member: Path, transactions: Mapping[str, str]) -> Iterator[_Pair]:
    return (
        (jump.program, callee)
        for jump in map(JumpNames.model_validate_json, _lines(member / "jumps.jsonl"))
        for callee in _named(jump, transactions)
    )


def _candidates(member: Path) -> Iterator[_Pair]:
    return (
        (site.caller, callee)
        for site in map(
            TargetSite.model_validate_json, _lines(member / "targets.jsonl")
        )
        if site.kind is TargetKind.PROGRAM
        for callee in site.candidates
    )


def call_groups(
    fixpoint_dir: Path, programs: frozenset[str], transactions: Mapping[str, str]
) -> tuple[frozenset[str], ...]:
    """Connected components of ``programs`` over literal and locally resolved jump
    targets, every program candidate in targets.jsonl whatever its reasons, and
    every transaction the CSD maps to a program. Largest first, then by name."""
    members = (fixpoint_dir / "members" / program for program in sorted(programs))
    pairs = chain.from_iterable(
        chain(_jumped(member, transactions), _candidates(member)) for member in members
    )
    graph: nx.Graph[str] = nx.Graph()
    graph.add_nodes_from(programs)
    graph.add_edges_from(pair for pair in pairs if pair[1] in programs)
    components = (frozenset(group) for group in nx.connected_components(graph))
    ranked = sorted((-len(group), min(group), group) for group in components)
    return tuple(group for _size, _name, group in ranked)
