"""env.toml, the place a package runs, parsed on arrival and checked against the package's manifest before anything runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from litter.manifest import Manifest
from pydantic import BaseModel, ConfigDict, Field

from red_dragon_forge.cics_run import CicsRun
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.env_paths import EnvPaths
from red_dragon_forge.jcl_run import JclRun
from red_dragon_forge.plain_run import PlainRun
from red_dragon_forge.sql_section import SqlSection
from red_dragon_forge.tolerant_section import TolerantSection
from red_dragon_forge.toml_config import toml_config

_MODES = ("plain", "jcl", "cics")
_SQL = "sql"

RunMode = PlainRun | JclRun | CicsRun


class EnvConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    package: Path
    tolerant: TolerantSection = Field(default_factory=TolerantSection)
    paths: EnvPaths
    sql: SqlSection = Field(default_factory=SqlSection)
    plain: PlainRun = Field(default_factory=lambda: PlainRun(program=""))
    jcl: JclRun = Field(default_factory=lambda: JclRun(job=Path()))
    cics: CicsRun = Field(default_factory=CicsRun)

    def has_sql(self) -> bool:
        return _SQL in self.model_fields_set

    def modes(self) -> tuple[str, ...]:
        return tuple(mode for mode in _MODES if mode in self.model_fields_set)


def _plain(path: Path, config: EnvConfig) -> RunMode:
    return config.plain


def _jcl(path: Path, config: EnvConfig) -> RunMode:
    return config.jcl


def _cics(path: Path, config: EnvConfig) -> RunMode:
    if "initial_transid" not in config.cics.model_fields_set:
        raise ConfigError(f"{path.name}: [cics] initial_transid is required")
    return config.cics


_MODE_OF: Mapping[str, Callable[[Path, EnvConfig], RunMode]] = {
    "plain": _plain,
    "jcl": _jcl,
    "cics": _cics,
}


def _mode(path: Path, config: EnvConfig) -> RunMode:
    found = config.modes()
    if len(found) != 1:
        named = ", ".join(f"[{m}]" for m in found) or "none"
        raise ConfigError(
            f"{path.name}: exactly one of [plain], [jcl], [cics] is required;"
            f" found {named}"
        )
    return _MODE_OF[found[0]](path, config)


def load_env_config(path: Path) -> tuple[EnvConfig, RunMode]:
    config = toml_config(EnvConfig, path)
    return config, _mode(path, config)


def _require_sql(path: Path, config: EnvConfig, manifest: Manifest) -> None:
    if _SQL in manifest.coprocessors and not config.has_sql():
        raise ConfigError(
            f"{path.name}: [sql] is required: {config.package} was built with sql"
        )


def _require_entry(
    path: Path, config: EnvConfig, mode: RunMode, manifest: Manifest
) -> None:
    match mode:
        case PlainRun(program=program) if program not in manifest.programs:
            raise ConfigError(
                f"{path.name}: program {program} is not in {config.package}"
            )
        case CicsRun(initial_transid=transid):
            _require_transaction(path, config, transid, manifest)
        case _:
            return


def _require_transaction(
    path: Path, config: EnvConfig, transid: str, manifest: Manifest
) -> None:
    programs = {t.transid: t.program for t in manifest.transactions}
    if transid not in programs:
        raise ConfigError(
            f"{path.name}: transaction {transid} is not in {config.package}"
        )
    if programs[transid] not in manifest.programs:
        raise ConfigError(
            f"{path.name}: transaction {transid} runs {programs[transid]},"
            f" which is not in {config.package}"
        )


def check_against(
    path: Path, config: EnvConfig, mode: RunMode, manifest: Manifest
) -> None:
    _require_sql(path, config, manifest)
    _require_entry(path, config, mode, manifest)
