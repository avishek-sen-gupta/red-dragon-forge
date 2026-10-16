"""build.toml, the application's build descriptor, parsed into typed sections on arrival."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from red_dragon_forge.build_cics import BuildCics
from red_dragon_forge.build_paths import BuildPaths
from red_dragon_forge.build_section import BuildSection
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.toml_config import toml_config

_CICS = frozenset({"cics", "cics-conversational"})


class BuildConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    paths: BuildPaths
    build: BuildSection
    cics: BuildCics = Field(
        default_factory=lambda: BuildCics(bms_dirs=(), csd_files=())
    )

    def uses_cics(self) -> bool:
        return bool(_CICS & set(self.build.coprocessors))


def _checked(path: Path, config: BuildConfig) -> BuildConfig:
    if config.uses_cics() and "cics" not in config.model_fields_set:
        raise ConfigError(
            f"{path.name}: [cics] is required when coprocessors include cics"
        )
    return config


def load_build_config(path: Path) -> BuildConfig:
    return _checked(path, toml_config(BuildConfig, path))
