"""The rows a CodeQL query selected, as `codeql bqrs decode --format=json` writes them."""

from cobble.experimental.codeql.demo.column import Column
from pydantic import BaseModel, ConfigDict


class Select(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    columns: tuple[Column, ...]
    tuples: tuple[tuple[str, ...], ...]
