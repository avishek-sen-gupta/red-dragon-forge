"""env.toml's [sql]: present when the package was built with sql; the DSN comes from SQUALL_DB2_DSN."""

from pydantic import BaseModel, ConfigDict


class SqlSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
