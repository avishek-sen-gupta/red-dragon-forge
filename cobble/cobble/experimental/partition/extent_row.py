"""One member field's declared extents, as the extents table stores them."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ExtentRow(BaseModel):
    """A field's extents with, per extent, its record, declaration path and picture."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    program: str
    extents: tuple[str, ...]
    records: tuple[str, ...]
    paths: tuple[tuple[str, ...], ...]
    pics: tuple[str, ...]
