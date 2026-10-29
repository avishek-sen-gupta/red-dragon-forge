"""One row of the accesses table: a field read at a CFG node."""

from typing import Literal

from cobble.dataflow.fields.access_extent_line import AccessExtentLine
from pydantic import BaseModel, ConfigDict


class AccessLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["access"]
    program: str
    site: str
    node: str
    paragraph: str
    extent: AccessExtentLine
