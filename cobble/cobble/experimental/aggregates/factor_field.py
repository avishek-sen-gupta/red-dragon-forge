"""One field and its loading on an NMF factor."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FactorField(BaseModel):
    """A field name and how strongly it loads on a factor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    loading: float
