"""One edges.jsonl row: a name-level dependency one statement of a program states."""

from pydantic import BaseModel, ConfigDict


class EdgeLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    src: str
    dst: str
    program: str
    seq: int
    verb: str
