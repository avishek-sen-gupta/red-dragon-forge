"""One extents.jsonl row: a declared field's extents and, per extent, its declared cell."""

from pydantic import BaseModel, ConfigDict


class ExtentLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    program: str
    extents: tuple[str, ...]
    names: tuple[str, ...]
    records: tuple[str, ...]
    paths: tuple[tuple[str, ...], ...]
    levels: tuple[int, ...]
    pics: tuple[str, ...]
    usages: tuple[str, ...]
    occurs: tuple[int, ...]
    origins: tuple[str, ...]
    values: tuple[str, ...]
    redefines: tuple[str, ...]
