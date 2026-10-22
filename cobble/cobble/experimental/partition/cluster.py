"""One cluster of fields inside one program."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Cluster(BaseModel):
    """A community of fields, and the connected component of its program it was found in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    component: int
    program: str
    members: tuple[str, ...]
