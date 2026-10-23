"""meta.json: what the matrix's rows and columns are, and the paragraphs they were counted over."""

from __future__ import annotations

from cobble.experimental.aggregates.paragraph_ref import ParagraphRef
from pydantic import BaseModel, ConfigDict


class MatrixMeta(BaseModel):
    """The field each row and column stands for, in order, and the paragraphs counted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[str, ...]
    paragraphs: tuple[ParagraphRef, ...]
