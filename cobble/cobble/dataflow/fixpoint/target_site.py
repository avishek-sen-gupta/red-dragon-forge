"""Dynamic call sites the combined run resolved completely; file sites are not calls."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dataflow.fixpoint.transid_jump import TransidJump
from pydantic import BaseModel, ConfigDict

Sites = tuple[tuple[str, str, tuple[str, ...]], ...]


class TargetSite(BaseModel):
    """The fields of a combined targets row this stage reads. A site is resolved
    when nothing says its candidates may be incomplete: no reasons, and no caller
    outside the corpus that could have written the name."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    caller: str
    node: str
    kind: TargetKind = TargetKind.PROGRAM
    candidates: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    outside: tuple[str, ...] = ()

    @property
    def resolved_call(self) -> bool:
        return (
            self.kind is TargetKind.PROGRAM
            and bool(self.candidates)
            and not self.reasons
            and not self.outside
        )


def _rows(path: Path) -> tuple[str, ...]:
    return tuple(line for line in path.read_text(encoding="utf-8").splitlines() if line)


def _targets(combined_dir: Path) -> Sites:
    return tuple(
        (site.caller, site.node, site.candidates)
        for line in _rows(combined_dir / "targets.jsonl")
        for site in (TargetSite.model_validate_json(line),)
        if site.resolved_call
    )


def _transactions(fixpoint_dir: Path, programs: Mapping[str, str]) -> Sites:
    """Each RETURN TRANSID whose transaction id resolved in its own program, with
    the programs the CSD defines those transactions to run. A transaction the CSD
    does not define runs no program; a site left with none stays unresolved."""
    return tuple(
        (jump.program, jump.node, callees)
        for line in _rows(fixpoint_dir / "jumps.jsonl")
        for jump in (TransidJump.model_validate_json(line),)
        if jump.resolved
        for callees in (
            tuple(
                sorted(
                    {
                        programs[value.rstrip()]
                        for value in jump.transid.values
                        if value.rstrip() in programs
                    }
                )
            ),
        )
        if callees
    )


def resolved_sites(
    fixpoint_dir: Path, combined_dir: Path, programs: Mapping[str, str]
) -> Sites:
    """Each dynamic site resolved completely, by caller and node, with the programs
    it can reach: XCTL, LINK and CALL from the combined targets, RETURN TRANSID
    from its own program's jumps and the CSD."""
    return (*_targets(combined_dir), *_transactions(fixpoint_dir, programs))
