"""build.toml's [paths]: where the application's sources and copybooks are, and the extensions a source may have."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class BuildPaths(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_dirs: tuple[Path, ...]
    source_exts: tuple[str, ...] = ()
    copybook_dirs: tuple[Path, ...] = ()
    copybook_exts: tuple[str, ...] = ()
