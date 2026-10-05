"""ProgramTables — one program's facts, flows, jumps and received areas, indexed."""

from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.combine.flow import Flow
from cobble.dataflow.combine.target_site import TargetSite
from cobble.dataflow.fields.extent_text import ByteRange
from cobble.dataflow.jumps.fact import Fact
from cobble.dataflow.jumps.jump import Jump


@dataclass(frozen=True)
class ProgramTables:
    program: str
    facts: Mapping[str, tuple[tuple[ByteRange, Fact], ...]]
    flows: Mapping[str, tuple[Flow, ...]]
    jumps: Mapping[str, Jump]
    received: tuple[tuple[int, ByteRange], ...]
    sites: Mapping[str, TargetSite]

    def facts_at(self, node: str, at: ByteRange) -> tuple[tuple[ByteRange, Fact], ...]:
        return tuple(
            (where, fact)
            for where, fact in self.facts.get(node, ())
            if where.overlaps(at)
        )

    def received_param(self, at: ByteRange) -> tuple[int, ...]:
        return tuple(param for param, area in self.received if area.covers(at))[:1]
