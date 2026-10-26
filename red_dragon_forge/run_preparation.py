"""What every forge-run mode starts from: its env.toml config, the opened package, and its coprocessing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar
from zipfile import BadZipFile

from interpreter.types.typed_value import TypedValue
from interpreter.vm.vm_types import BuiltinResult, VMState
from litter.open import open_package
from litter.package import Package
from squall.sql_runtime import SqlRuntime

from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessing import Coprocessing
from red_dragon_forge.db2_connection import connected
from red_dragon_forge.env_config import EnvConfig, load_env_config

_DSN = "SQUALL_DB2_DSN"

E = TypeVar("E", bound=EnvConfig)


def _noop() -> None:
    return None


def _no_hook(args: Sequence[TypedValue], vm: VMState) -> BuiltinResult:
    return BuiltinResult(value=None)


_NO_COPROCESSING = Coprocessing(
    on_abend=_noop,
    sql=SqlRuntime(
        entries=MappingProxyType({}),
        reset_session=_no_hook,
        syncpoint=_no_hook,
        rollback=_no_hook,
    ),
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
    path: Path, environ: Mapping[str, str], model: type[E]
) -> tuple[E, Package, Coprocessing]:
    config = load_env_config(path, model)
    package = _package(path, config)
    config.check_against(path, package.manifest)
    return config, package, _coprocessing(config, package, environ)
