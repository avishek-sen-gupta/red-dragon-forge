"""A jumps.jsonl row, as far as the names it could transfer to."""

from __future__ import annotations

from cobble.dataflow.fixpoint.jump_fact_row import JumpFactRow
from cobble.dataflow.jumps.jump_kind import JumpKind
from pydantic import BaseModel, ConfigDict


class JumpNames(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    program: str
    kind: JumpKind
    target: JumpFactRow = JumpFactRow()
    transid: JumpFactRow = JumpFactRow()
