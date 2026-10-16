"""build.toml's [cics]: the BMS mapsets and the CSD files a CICS build reads."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class BuildCics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bms_dirs: tuple[Path, ...]
    csd_files: tuple[Path, ...]
