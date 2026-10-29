"""One access row's byte extent, as the accesses table writes it."""

from pydantic import BaseModel, ConfigDict


class AccessExtentLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    region: str
    start: int
    end: int
    clamped: bool
