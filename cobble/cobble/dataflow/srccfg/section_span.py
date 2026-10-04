"""SectionSpan — a section and the first and last paragraphs declared in it."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import NO_SPAN, SourceSpan


@dataclass(frozen=True)
class SectionSpan:
    section: str
    first: str
    last: str
    span: SourceSpan = NO_SPAN
