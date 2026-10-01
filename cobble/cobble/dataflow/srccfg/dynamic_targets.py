"""Which programs each dynamic call site can reach, as the fixpoint's targets.jsonl says."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cobble.dataflow.fixpoint import rows


@dataclass(frozen=True)
class DynamicSite:
    """The candidates one site resolved to, and the reasons they may be short."""

    candidates: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def proven(self) -> bool:
        return len(self.candidates) == 1 and not self.reasons


UNANSWERED = DynamicSite(candidates=(), reasons=())


@dataclass(frozen=True)
class DynamicTargets:
    """Every answered site, keyed by the caller and the node that names it."""

    sites: Mapping[tuple[str, str], DynamicSite]

    def at(self, caller: str, node: str) -> DynamicSite:
        return self.sites.get((caller, node), UNANSWERED)


NO_DYNAMIC_TARGETS = DynamicTargets(sites=MappingProxyType({}))


def dynamic_targets_of(path: Path) -> DynamicTargets:
    return DynamicTargets(
        sites=MappingProxyType(
            {
                (rows.text(row, "caller"), rows.text(row, "node")): DynamicSite(
                    candidates=rows.strings(row, "candidates"),
                    reasons=rows.strings(row, "reasons"),
                )
                for row in rows.read(path)
            }
        )
    )
