"""Where the ASG cache is and where the CFGs go.

Both values are required. A silent default here buys nothing: the failure it hides
is a run that finds no members and reports success.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from cobble.path_utils import config_path

TABLE = "srccfg"


def _read_table(path: Path) -> Mapping:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    table = document.get(TABLE, {})
    if not isinstance(table, Mapping):
        raise KeyError(f"{path}: [{TABLE}] must be a table")
    if not table:
        raise KeyError(f"{path}: no [{TABLE}] table")
    return table


def _require(table: Mapping, key: str, source: Path) -> str:
    value = str(table.get(key, ""))
    if value:
        return value
    raise KeyError(f"{source}: [{TABLE}] is missing a non-empty {key}")


def _source_dir(table: Mapping) -> Path:
    return config_path(str(table["source_dir"])) if table.get("source_dir") else Path()


@dataclass(frozen=True)
class SrcCfgCorpusConfig:
    asg_dir: Path
    out_dir: Path
    source_dir: Path = Path()


def load_srccfg_corpus_config(path: Path) -> SrcCfgCorpusConfig:
    table = _read_table(path)
    return SrcCfgCorpusConfig(
        asg_dir=config_path(_require(table, "asg_dir", path)),
        out_dir=config_path(_require(table, "out_dir", path)),
        source_dir=_source_dir(table),
    )


@dataclass(frozen=True)
class SrcCfgBuildConfig:
    asg_dir: Path
    source_dir: Path = Path()


def load_srccfg_build_config(path: Path) -> SrcCfgBuildConfig:
    table = _read_table(path)
    return SrcCfgBuildConfig(
        asg_dir=config_path(_require(table, "asg_dir", path)),
        source_dir=_source_dir(table),
    )
