"""env.toml's [jcl]: a job jackal runs against the package, and the procedure libraries it expands from."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class JclRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job: Path
    proclib_dirs: tuple[Path, ...] = ()
