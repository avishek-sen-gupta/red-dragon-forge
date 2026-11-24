"""A decoded CodeQL result file: the query's selected rows under `#select`."""

from cobble.experimental.codeql.demo.select import Select
from pydantic import BaseModel, ConfigDict, Field


class ResultSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    select: Select = Field(alias="#select")
