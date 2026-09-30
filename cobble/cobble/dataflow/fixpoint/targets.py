"""Which programs one dynamic call site can reach, read off the settled state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce

from cobble.dataflow.fields.extent import CellIndex, operand_occurrence_extents
from cobble.dataflow.fields.state import EMPTY as STATE_EMPTY
from cobble.dataflow.fields.state import State, values_at
from cobble.dataflow.fields.values import EMPTY as VALUES_EMPTY
from cobble.dataflow.fields.values import UnresolvedReason, ValueSet, because, merged
from cobble.dataflow.srccfg.cfg import Cfg, Node
from cobble.dataflow.srccfg.desugar import CALL_TRANSFERS
from cobol_memory.field_extent import FieldExtent


@dataclass(frozen=True)
class ResolvedTarget:
    """One dynamic call site, the programs it can reach, and the doubt attached.

    ``candidates`` is sorted, so the artefact and every edge derived from it are the
    same on any machine. ``dropped`` holds values that resolved but are not program
    names -- spaces, low-values -- which is a fact about the site and not an absence:
    a site provably holding spaces is answered, just not with a program.
    """

    caller: str
    node: str
    transfer: str
    expression: str
    candidates: tuple[str, ...] = ()
    reasons: tuple[UnresolvedReason, ...] = ()
    dropped: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.reasons


def _is_program_name(name: str) -> bool:
    """A resolved value that could name a load module.

    Not a pattern standing in for a type: every candidate here is already known to
    be the content of a program-name operand, and this only rejects content that
    cannot name anything at all.
    """
    return bool(name) and name.isprintable() and not name.isspace()


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


def _resolved(
    cfg: Cfg, node: Node, index: CellIndex, state: State, settled: bool
) -> ResolvedTarget:
    held = _held(state, operand_occurrence_extents(node.target_operand, index))
    names = tuple(sorted({_decoded(value) for value in held.values}))
    reasons = _with_incomplete_walk(held.reasons, settled)
    return ResolvedTarget(
        caller=cfg.program,
        node=node.id,
        transfer=node.transfer,
        expression=node.target,
        candidates=tuple(name for name in names if _is_program_name(name)),
        reasons=tuple(
            reason for _, reason in sorted((reason.value, reason) for reason in reasons)
        ),
        dropped=tuple(name for name in names if not _is_program_name(name)),
    )


def resolved_targets(
    cfg: Cfg,
    index: CellIndex,
    states: Mapping[str, State],
    settled: bool,
) -> tuple[ResolvedTarget, ...]:
    """One row per dynamic call site, whether or not anything resolved.

    A site whose target is a literal is not here: it is already an edge. A site the
    walk never reached has no state, so it resolves to nothing with a reason, which
    is the answer and not an omission.
    """
    return tuple(
        _resolved(cfg, node, index, states.get(node.id, STATE_EMPTY), settled)
        for node in cfg.nodes
        if node.transfer in CALL_TRANSFERS and node.target and not node.target_resolved
    )
