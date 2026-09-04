"""Where the ASG cache is and where the CFGs go.

Both values are required. A silent default here buys nothing: the failure it hides
is a run that finds no members and reports success.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TABLE = "srccfg"


@dataclass(frozen=True)
class SrcCfgConfig:
    asg_dir: Path
    out_dir: Path


def _require(table: Mapping[str, object], key: str, source: Path) -> str:
    value = str(table.get(key, ""))
    if value:
        return value
    raise KeyError(f"{source}: [{TABLE}] is missing a non-empty {key}")


def load_srccfg_config(path: Path) -> SrcCfgConfig:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    table = document.get(TABLE, {})
    if not isinstance(table, Mapping):
        raise KeyError(f"{path}: [{TABLE}] must be a table")
    if not table:
        raise KeyError(f"{path}: no [{TABLE}] table")
    return SrcCfgConfig(
        asg_dir=_path_of(_require(table, "asg_dir", path)),
        out_dir=_path_of(_require(table, "out_dir", path)),
    )


def _path_of(text: str) -> Path:
    return Path(text).expanduser()
