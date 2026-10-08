"""One dynamic site as the --sites file holds it: how its own program resolved it, and every write to its operand."""

from __future__ import annotations

from cobble.dataflow.fixpoint.site_row_definition import SiteRowDefinition
from pydantic import BaseModel, ConfigDict


class SiteRow(BaseModel):
    """``callees`` when every definition reaching the operand names them, otherwise
    ``reasons``; ``definitions`` are every write in the program touching the
    operand, reaching the site or not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member: str
    place: str
    transfer: str
    operand: str
    callees: tuple[str, ...]
    reasons: tuple[str, ...]
    definitions: tuple[SiteRowDefinition, ...]
