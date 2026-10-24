"""One NMF factor: its strongest fields and the name prefixes they span."""

from __future__ import annotations

from cobble.experimental.aggregates.factor_field import FactorField
from pydantic import BaseModel, ConfigDict


class Factor(BaseModel):
    """A factor's index, its top loading fields, and the distinct name prefixes among them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factor_id: int
    top_fields: tuple[FactorField, ...]
    n_record_prefixes: int
    record_prefixes: tuple[str, ...]
