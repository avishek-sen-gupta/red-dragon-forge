"""The programs a dynamic call site may enter, as the combined run's targets.jsonl names them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.target_site import TargetSite


@dataclass(frozen=True)
class CallTargets:
    """Each dynamic call site by caller and CFG node, with its candidate callees."""

    sites: tuple[tuple[str, str, tuple[str, ...]], ...] = ()

    def of(self, caller: str, node: str) -> tuple[str, ...]:
        return next(
            (
                candidates
                for at_caller, at_node, candidates in self.sites
                if (at_caller, at_node) == (caller, node)
            ),
            (),
        )


NO_CALL_TARGETS = CallTargets()


def read_call_targets(path: Path) -> CallTargets:
    rows = (
        TargetSite.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return CallTargets(
        sites=tuple(
            (row.caller, row.node, row.candidates)
            for row in rows
            if row.kind is TargetKind.PROGRAM and row.candidates
        )
    )
