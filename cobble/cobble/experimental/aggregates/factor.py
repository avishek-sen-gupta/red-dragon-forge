"""One NMF factor: its strongest fields, the name prefixes they span, and the paragraphs that use it most."""

from __future__ import annotations

from cobble.experimental.aggregates.factor_field import FactorField
from cobble.experimental.aggregates.factor_paragraph import FactorParagraph
from pydantic import BaseModel, ConfigDict


class Factor(BaseModel):
    """A factor's index, its top loading fields, the distinct name prefixes among them, and its top loading paragraphs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factor_id: int
    top_fields: tuple[FactorField, ...]
    n_record_prefixes: int
    record_prefixes: tuple[str, ...]
    top_paragraphs: tuple[FactorParagraph, ...]
