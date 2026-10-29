"""One sinks.jsonl row: bytes leaving a program at one statement, and their definers."""

from __future__ import annotations

from cobble.dataflow.fields.sink import Sink
from pydantic import BaseModel, ConfigDict


class SinkRow(BaseModel):
    """A sink row as the fixpoint writes it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    program: str
    node: str
    sink: Sink
    source_extent: str
    definers: tuple[str, ...]
