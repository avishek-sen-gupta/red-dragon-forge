"""One non-site demand source in an explain row, and the entry bytes it alone needs."""

from __future__ import annotations

from cobble.dataflow.fixpoint.explain_source_kind import ExplainSourceKind
from pydantic import BaseModel, ConfigDict


class ExplainSource(BaseModel):
    """``bytes`` is the member's entry need with only this demand switched on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ExplainSourceKind
    bytes: int
