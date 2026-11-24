"""One column of a decoded CodeQL result set."""

from pydantic import BaseModel, ConfigDict


class Column(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    name: str = ""
