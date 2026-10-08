"""A jumps.jsonl row naming a transaction, as far as the area need reads it."""

from __future__ import annotations

from cobble.dataflow.fixpoint.jump_fact_row import JumpFactRow
from pydantic import BaseModel, ConfigDict

_NEXT_TRANSACTION = "RETURN_TRANSID"


class TransidJump(BaseModel):
    """A RETURN TRANSID is resolved when its transaction id has values and nothing
    says it may hold others."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    program: str
    node: str
    kind: str
    transid: JumpFactRow = JumpFactRow()

    @property
    def resolved(self) -> bool:
        return (
            self.kind == _NEXT_TRANSACTION
            and bool(self.transid.values)
            and not self.transid.reasons
        )
