"""env.toml's [paths]: catnip's system directory, where the run's datasets are cataloged."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class EnvPaths(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    system: Path
