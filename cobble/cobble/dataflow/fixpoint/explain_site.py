"""One call site in an explain row: where it is, how it was charged, and what that alone needs."""

from __future__ import annotations

from cobble.dataflow.fixpoint.site_resolution import SiteResolution
from pydantic import BaseModel, ConfigDict


class ExplainSite(BaseModel):
    """``callees`` are the programs it was charged with: the one it names, the ones a
    dynamic site resolved to, or none when unresolved. ``bytes`` is the member's
    entry need with only this site's demand switched on. ``reasons`` says why an
    unresolved site's own program could not name its callees."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    place: str
    transfer: str
    resolution: SiteResolution
    callees: tuple[str, ...]
    bytes: int
    reasons: tuple[str, ...] = ()
