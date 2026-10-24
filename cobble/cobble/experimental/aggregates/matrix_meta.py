"""meta.json: what the matrix's rows and columns stand for, and how often each field occurs."""

from __future__ import annotations

from cobble.experimental.aggregates.paragraph_ref import ParagraphRef
from pydantic import BaseModel, ConfigDict


class MatrixMeta(BaseModel):
    """The field each column stands for, in order, the paragraph each row stands for, how many paragraphs each field is written in, and the fewest a field needed to be kept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[str, ...]
    paragraphs: tuple[ParagraphRef, ...]
    occurrences: tuple[int, ...]
    min_occurrences: int
