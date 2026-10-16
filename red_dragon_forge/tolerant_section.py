"""env.toml's [tolerant]: the run-time tolerances, each off unless named."""

from pydantic import BaseModel, ConfigDict


class TolerantSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    permit_unresolved_call_targets: bool = False
    permit_missing_host_variables: bool = False
