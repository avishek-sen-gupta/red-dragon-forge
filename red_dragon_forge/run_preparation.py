"""What every forge-run mode starts from: the env.toml config and mode, the opened package, and its coprocessing."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from zipfile import BadZipFile

from cics.transaction_hooks import TransactionHooks
from litter.open import open_package
from litter.package import Package

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.db2_connection import connected
from red_dragon_forge.env_config import (
    EnvConfig,
    RunMode,
    check_against,
    load_env_config,
)

_DSN = "SQUALL_DB2_DSN"


def _noop() -> None:
    return None


_NO_COPROCESSING = Coprocessing(
    on_abend=_noop, hooks=TransactionHooks(), builtins=MappingProxyType({})
)


def _coprocessing(
    config: EnvConfig, package: Package, environ: Mapping[str, str]
) -> Coprocessing:
    if "sql" not in package.manifest.coprocessors:
        return _NO_COPROCESSING
    if not environ.get(_DSN, ""):
        raise ConfigError(f"{_DSN} is not set")
    return connected(environ[_DSN]).install(
        config.tolerant.permit_missing_host_variables
    )


def _package(path: Path, config: EnvConfig) -> Package:
    try:
        return open_package(path.parent / config.package)
    except (OSError, BadZipFile) as exc:
        raise ConfigError(f"{path.name}: package {config.package}: {exc}") from exc


def prepared(
    path: Path, environ: Mapping[str, str]
) -> tuple[EnvConfig, RunMode, Package, Coprocessing]:
    config, mode = load_env_config(path)
    package = _package(path, config)
    check_against(path, config, mode, package.manifest)
    return config, mode, package, _coprocessing(config, package, environ)
