"""Fact — what the settled state says about some bytes at one node."""

from dataclasses import dataclass, field

from cobble.dataflow.fields.values import UnresolvedReason


@dataclass(frozen=True)
class Fact:
    extent: str = ""
    values: tuple[str, ...] = field(default_factory=tuple)
    writers: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[UnresolvedReason, ...] = field(default_factory=tuple)
