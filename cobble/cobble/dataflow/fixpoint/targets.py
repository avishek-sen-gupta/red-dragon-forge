"""Which programs one dynamic call site can reach, read off the settled state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import reduce

from cobble.dataflow.fields.extent import CellIndex, operand_occurrence_extents
from cobble.dataflow.fields.state import EMPTY as STATE_EMPTY
from cobble.dataflow.fields.state import State, values_at
from cobble.dataflow.fields.values import EMPTY as VALUES_EMPTY
from cobble.dataflow.fields.values import UnresolvedReason, ValueSet, because, merged
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.facts import fact_at
from cobble.dataflow.jumps.facts import merged as merged_facts
from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_asg.ref_mod import RefModOperand
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class ResolvedTarget:
    """One dynamic site, what it can name, and the doubt attached.

    ``kind`` says whether the site is a call naming a program or a CICS file
    statement naming a file. ``candidates`` is sorted, so the artefact and every
    edge derived from it are the same on any machine. ``dropped`` holds values that
    resolved but cannot name a ``kind`` -- spaces, low-values -- which is a fact about
    the site and not an absence: a site provably holding spaces is answered, just not
    with a name. ``operand`` is what the settled state says about a file site's
    operand bytes, writers included, so the combine can walk back from them; a call
    site's operand fact travels in its jump instead.
    """

    caller: str
    node: str
    kind: TargetKind
    transfer: str
    expression: str
    candidates: tuple[str, ...] = ()
    reasons: tuple[UnresolvedReason, ...] = ()
    dropped: tuple[str, ...] = ()
    operand: Fact = field(default_factory=Fact)

    @property
    def complete(self) -> bool:
        return not self.reasons


def _decoded(value: bytes) -> str:
    return value.decode("utf-8", errors="replace").rstrip()


def _held(state: State, extents: Sequence[FieldExtent]) -> ValueSet:
    if not extents:
        return because(UnresolvedReason.NO_EXTENT)
    return reduce(
        merged, (values_at(state, extent) for extent in extents), VALUES_EMPTY
    )


def _with_incomplete_walk(
    reasons: frozenset[UnresolvedReason], settled: bool
) -> frozenset[UnresolvedReason]:
    if settled:
        return reasons
    return reasons | {UnresolvedReason.INCOMPLETE_WALK}


def _sorted_reasons(
    reasons: frozenset[UnresolvedReason],
) -> tuple[UnresolvedReason, ...]:
    return tuple(reason for _, reason in sorted((r.value, r) for r in reasons))


def _operand_fact(node: Node, index: CellIndex, state: State, settled: bool) -> Fact:
    if not node.file:
        return Fact()
    found = merged_facts(
        tuple(
            fact_at(state, extent)
            for extent in operand_occurrence_extents(node.file_operand, index)
        )
    )
    return replace(
        found,
        reasons=_sorted_reasons(
            _with_incomplete_walk(frozenset(found.reasons), settled)
        ),
    )


def _kind(node: Node) -> TargetKind:
    return TargetKind.FILE if node.file else TargetKind.PROGRAM


def _operand(node: Node) -> RefModOperand:
    return node.file_operand if node.file else node.target_operand


def _resolved(
    cfg: Cfg, node: Node, index: CellIndex, state: State, settled: bool
) -> ResolvedTarget:
    held = _held(state, operand_occurrence_extents(_operand(node), index))
    names = tuple(sorted({_decoded(value) for value in held.values}))
    reasons = _with_incomplete_walk(held.reasons, settled)
    kind = _kind(node)
    return ResolvedTarget(
        caller=cfg.program,
        node=node.id,
        kind=kind,
        transfer=node.transfer,
        expression=node.file or node.target,
        candidates=tuple(name for name in names if kind.can_name(name)),
        reasons=_sorted_reasons(reasons),
        dropped=tuple(name for name in names if not kind.can_name(name)),
        operand=_operand_fact(node, index, state, settled),
    )


def is_dynamic_site(node: Node) -> bool:
    """A call naming its program, or a CICS file statement naming its file, by a data item."""
    calls = node.transfer in CALL_TRANSFERS and node.target and not node.target_resolved
    return bool(calls or node.file)


def resolved_targets(
    cfg: Cfg,
    index: CellIndex,
    states: Mapping[str, State],
    settled: bool,
) -> tuple[ResolvedTarget, ...]:
    """One row per dynamic site, whether or not anything resolved.

    A site naming a literal is not here: it is already an edge. A site the
    walk never reached has no state, so it resolves to nothing with a reason, which
    is the answer and not an omission.
    """
    return tuple(
        _resolved(cfg, node, index, states.get(node.id, STATE_EMPTY), settled)
        for node in cfg.nodes
        if is_dynamic_site(node)
    )
