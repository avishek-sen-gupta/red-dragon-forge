"""The TOML that describes a region to serve over TN3270."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

TomlValue = str | int | list[str] | Mapping[str, str | int]


class ConfigError(ValueError):
    pass


def _path(raw: str) -> Path:
    expanded = os.path.expandvars(raw)
    if "$" in expanded:
        raise ConfigError(f"unset environment variable in path {raw!r}")
    return Path(expanded).expanduser()


@dataclass(frozen=True)
class RegionConfig:
    source_dirs: tuple[Path, ...]
    copybook_dirs: tuple[Path, ...]
    bms_dirs: tuple[Path, ...]
    hlasm_export: Path
    initial_transid: str
    transactions: Mapping[str, str]
    programs: frozenset[str]
    system: Path
    csd_files: tuple[Path, ...]
    copybook_exts: tuple[str, ...] = ()


def load_config(path: Path) -> RegionConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    paths, region = raw["paths"], raw["region"]
    transactions = MappingProxyType(dict(raw["transactions"]))
    return RegionConfig(
        source_dirs=tuple(_path(p) for p in paths["source_dirs"]),
        copybook_dirs=tuple(_path(p) for p in paths["copybook_dirs"]),
        bms_dirs=tuple(_path(p) for p in paths["bms_dirs"]),
        hlasm_export=_path(paths["hlasm_export"]),
        initial_transid=region.get("initial_transid", ""),
        transactions=transactions,
        programs=frozenset((*transactions.values(), *region.get("programs", ()))),
        system=_path(paths["system"]),
        csd_files=tuple(_path(p) for p in paths["csd_files"]),
        copybook_exts=tuple(paths.get("copybook_exts", ())),
    )


def resolve_program_source(config: RegionConfig, program_name: str) -> Path:
    """First-hit-wins resolution of ``program_name``'s ``.cbl`` source across
    ``config.source_dirs``, in order.

    Raises :class:`ConfigError` naming every directory searched when the
    program is in none of them -- a region spanning two source trees (e.g.
    the CICS and Db2 CardDemo trees) needs a clear diagnostic rather than a
    bare FileNotFoundError against whichever directory happened to be first.
    """
    candidates = [directory / f"{program_name}.cbl" for directory in config.source_dirs]
    hits = [candidate for candidate in candidates if candidate.is_file()]
    match hits:
        case [found, *_]:
            return found
        case _:
            searched = ", ".join(str(d) for d in config.source_dirs)
            raise ConfigError(
                f"program {program_name!r} not found in any of the configured "
                f"source_dirs: [{searched}]"
            )
