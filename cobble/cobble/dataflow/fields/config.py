"""Where the ASG cache is and where the field graph goes.

Both values are required. A silent default here buys nothing: the failure it hides
is a run that finds no members and reports success.

Deliberately fails in the same words as ``srccfg/config.py`` -- two configs in one
package that reject the same mistake differently is the drift worth avoiding.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TABLE = "fields"


@dataclass(frozen=True)
class FieldsConfig:
    asg_dir: Path
    out_dir: Path


def _require(value: str, key: str, source: Path) -> str:
    if value:
        return value
    raise KeyError(f"{source}: [{TABLE}] is missing a non-empty {key}")


def load_fields_config(path: Path) -> FieldsConfig:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    table = document.get(TABLE, {})
    if not isinstance(table, Mapping):
        raise KeyError(f"{path}: [{TABLE}] must be a table")
    if not table:
        raise KeyError(f"{path}: no [{TABLE}] table")
    return FieldsConfig(
        asg_dir=_path_of(_require(str(table.get("asg_dir", "")), "asg_dir", path)),
        out_dir=_path_of(_require(str(table.get("out_dir", "")), "out_dir", path)),
    )


def _path_of(text: str) -> Path:
    return Path(text).expanduser()
