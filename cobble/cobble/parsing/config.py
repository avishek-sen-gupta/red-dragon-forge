"""config.py — which programs to parse, how to resolve their copybooks, where the
ASGs go.

Own config rather than a section of any consumer's, because the parse is its own
stage and runs on its own clock: once per corpus change, where the graph stages
run once per question asked of the corpus. A consumer needs the ASG directory and
nothing else from here -- it never needs the bridge JAR, because it never parses.

Shape -- see config/parse.example.toml:

    [parse]
    cobol_dir = "/path/to/corpus"
    cobol_globs = ["cobol/*.cbl"]
    copybook_dirs = ["sym", "layouts/"]
    copybook_extensions = ["cpy", "txt"]
    bridge_jar = ".../proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar"
    asg_dir = "out-parsed"

Every key is required. A default here would be a run that matches no programs, or
resolves no copybooks, and reports success either way.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

TABLE = "parse"


@dataclass(frozen=True)
class ParseConfig:
    cobol_dir: Path
    cobol_globs: tuple[str, ...]
    copybook_dirs: tuple[Path, ...]
    copybook_extensions: tuple[str, ...]
    bridge_jar: Path
    asg_dir: Path


def _require(table: Mapping[str, object], key: str, source: Path) -> object:
    if key not in table:
        raise KeyError(f"{source}: [{TABLE}] is missing {key}")
    return table[key]


def _path(table: Mapping[str, object], key: str, source: Path) -> Path:
    return Path(str(_require(table, key, source))).expanduser()


def _strings(table: Mapping[str, object], key: str, source: Path) -> tuple[str, ...]:
    value = _require(table, key, source)
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise KeyError(f"{source}: [{TABLE}] {key} must be a list")
    return tuple(str(item) for item in value)


def _table(document: Mapping[str, object], source: Path) -> Mapping[str, object]:
    table = document.get(TABLE)
    if not isinstance(table, Mapping):
        raise KeyError(f"{source}: no [{TABLE}] table")
    return table


def parse_config_from_dict(
    document: Mapping[str, object], source: Path = Path()
) -> ParseConfig:
    """The pure half: parsed TOML -> ParseConfig, no I/O."""
    table = _table(document, source)
    return ParseConfig(
        cobol_dir=_path(table, "cobol_dir", source),
        cobol_globs=_strings(table, "cobol_globs", source),
        copybook_dirs=tuple(
            Path(d).expanduser() for d in _strings(table, "copybook_dirs", source)
        ),
        copybook_extensions=_strings(table, "copybook_extensions", source),
        bridge_jar=_path(table, "bridge_jar", source),
        asg_dir=_path(table, "asg_dir", source),
    )


def load_parse_config(path: Path) -> ParseConfig:
    return parse_config_from_dict(
        tomllib.loads(path.read_text(encoding="utf-8")), source=path
    )
