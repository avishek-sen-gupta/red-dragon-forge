"""build.toml, the application's build descriptor, parsed into typed sections on arrival."""

from __future__ import annotations

from pathlib import Path

from litter.member_name import MemberName
from pydantic import BaseModel, ConfigDict, Field

from red_dragon_forge.build_cics import BuildCics
from red_dragon_forge.build_cobol import BuildCobol
from red_dragon_forge.build_hlasm import BuildHlasm
from red_dragon_forge.build_section import BuildSection
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.toml_config import toml_config

_CICS = frozenset({"cics", "cics-conversational"})


class BuildConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cobol: BuildCobol = BuildCobol()
    hlasm: BuildHlasm = BuildHlasm()
    build: BuildSection
    cics: BuildCics = Field(
        default_factory=lambda: BuildCics(bms_dirs=(), csd_files=())
    )

    def uses_cics(self) -> bool:
        return bool(_CICS & set(self.build.coprocessors))

    def programs(self) -> tuple[MemberName, ...]:
        return (*self.cobol.programs, *self.hlasm.programs)


def _checked(path: Path, config: BuildConfig) -> BuildConfig:
    if config.uses_cics() and "cics" not in config.model_fields_set:
        raise ConfigError(
            f"{path.name}: [cics] is required when coprocessors include cics"
        )
    both = tuple(p for p in config.cobol.programs if p in config.hlasm.programs)
    if both:
        raise ConfigError(
            f"{path.name}: {both[0]} is listed in both [cobol] and [hlasm] programs"
        )
    return config


def load_build_config(path: Path) -> BuildConfig:
    return _checked(path, toml_config(BuildConfig, path))
