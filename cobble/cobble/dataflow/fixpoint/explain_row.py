"""One member's explain row: its entry need, what each source alone needs, and the widest writes."""

from __future__ import annotations

from cobble.dataflow.fixpoint.explain_site import ExplainSite
from cobble.dataflow.fixpoint.explain_source import ExplainSource
from cobble.dataflow.fixpoint.explain_widening import ExplainWidening
from pydantic import BaseModel, ConfigDict


class ExplainRow(BaseModel):
    """Written as one JSONL line the moment its worker finishes it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member: str
    needed: int
    sources: tuple[ExplainSource, ...]
    sites: tuple[ExplainSite, ...]
    widening: tuple[ExplainWidening, ...]
