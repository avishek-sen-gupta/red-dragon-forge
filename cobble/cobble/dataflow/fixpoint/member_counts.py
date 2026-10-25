"""MemberCounts -- what one member adds to a fixpoint run's report."""

from pydantic import BaseModel, ConfigDict


class MemberCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    member: str
    program: str = ""
    skipped: str = ""
    writes: int = 0
    covered: int = 0
    unhandled: int = 0
    unmodelled: int = 0
    sweeps: int = 0
    settled: bool = True
    edges: int = 0
    aliased: int = 0
    dead_ends: tuple[str, ...] = ()
    dynamic_sites: int = 0
    resolved_one: int = 0
    resolved_several: int = 0
    unresolved_reasons: tuple[str, ...] = ()
    file_sites: int = 0
    file_resolved_one: int = 0
    file_resolved_several: int = 0
    tracked: int = 0
    relevant: int = 0
