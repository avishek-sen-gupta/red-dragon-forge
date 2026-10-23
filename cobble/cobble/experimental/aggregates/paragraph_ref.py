"""One paragraph the matrix counted, by program."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ParagraphRef(BaseModel):
    """A program and one of its paragraphs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    paragraph: str
