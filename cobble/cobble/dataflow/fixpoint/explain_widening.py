"""One write in an explain row that makes more live than its target keeps."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ExplainWidening(BaseModel):
    """``kept`` live bytes of ``target``; ``keeps_old`` when the write may leave the
    target as it was, so all of it stays live; ``read`` bytes made live from
    ``sources``, in region and offset order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    place: str
    target: str
    kept: int
    keeps_old: bool
    read: int
    sources: tuple[str, ...]
