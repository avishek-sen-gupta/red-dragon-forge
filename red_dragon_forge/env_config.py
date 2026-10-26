"""env.toml, the place a package runs: the settings every mode shares, the one mode section present, and the shared checks against the package's manifest."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from litter.manifest import Manifest
from pydantic import BaseModel, ConfigDict, Field

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_paths import EnvPaths
from red_dragon_forge.run_mode import RunMode
from red_dragon_forge.sql_section import SqlSection
from red_dragon_forge.tolerant_section import TolerantSection
from red_dragon_forge.toml_config import toml_config, toml_sections

_SQL = "sql"


class EnvConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    package: Path
    tolerant: TolerantSection = Field(default_factory=TolerantSection)
    paths: EnvPaths
    sql: SqlSection = Field(default_factory=SqlSection)

    def has_sql(self) -> bool:
        return _SQL in self.model_fields_set

    def check_loaded(self, path: Path) -> None:
        return None

    def check_against(self, path: Path, manifest: Manifest) -> None:
        if _SQL in manifest.coprocessors and not self.has_sql():
            raise ConfigError(
                f"{path.name}: [sql] is required: {self.package} was built with sql"
            )


E = TypeVar("E", bound=EnvConfig)


def run_mode(path: Path) -> RunMode:
    present = toml_sections(path)
    found = tuple(mode for mode in RunMode if mode in present)
    if len(found) != 1:
        named = ", ".join(f"[{m}]" for m in found) or "none"
        raise ConfigError(
            f"{path.name}: exactly one of [plain], [jcl], [cics] is required;"
            f" found {named}"
        )
    return found[0]


def load_env_config(path: Path, model: type[E]) -> E:
    config = toml_config(model, path)
    config.check_loaded(path)
    return config
