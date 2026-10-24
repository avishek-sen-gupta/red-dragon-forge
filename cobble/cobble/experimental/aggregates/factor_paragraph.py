"""One paragraph and its loading on an NMF factor."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FactorParagraph(BaseModel):
    """A program, one of its paragraphs, and how strongly the paragraph uses a factor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    paragraph: str
    loading: float
