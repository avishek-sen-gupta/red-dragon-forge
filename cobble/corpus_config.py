"""corpus_config.py — YAML-driven corpus configuration for build_graph.py and
generate_sym.py, so cobble can extract a knowledge graph / generate BMS
copybooks from any COBOL/CICS/JCL corpus without editing Python source.

Split into a pure core (dict -> dataclass, no I/O) and an imperative shell
(reads the YAML file off disk). Every required field is read without a
fallback default -- a missing key raises rather than silently guessing a
path. List-shaped fields are never None; an absent/empty key means an empty
tuple, except for the two that describe how files are NAMED rather than where
they live (`copybook_extensions`, `bms_globs`): those fall back to the
conventions cobble shipped with, so a corpus only spells them out when its
members don't follow those conventions. Relative paths are NOT resolved here -- they stay relative to
whatever the caller's current working directory is (matching today's
implicit behavior of running scripts from the repo root).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

# The extensions the ProLeap bridge has always searched (see
# proleap-bridge/src/main/java/org/reddragon/bridge/Main.java). Kept as the
# default so a config written before `copybook_extensions` existed resolves
# copybooks exactly as it did before.
DEFAULT_COPYBOOK_EXTENSIONS: tuple[str, ...] = (
    "",
    "cpy",
    "CPY",
    "cob",
    "cbl",
    "copy",
    "COPY",
)

DEFAULT_BMS_GLOBS: tuple[str, ...] = ("*.bms",)


@dataclass(frozen=True)
class CorpusConfig:
    cobol_dir: Path
    cobol_globs: tuple[str, ...]
    jcl_dir: Path
    jcl_globs: tuple[str, ...]
    proclib_dirs: tuple[Path, ...]
    csd_files: tuple[Path, ...]
    copybook_dirs: tuple[Path, ...]
    copybook_extensions: tuple[str, ...]
    out_dir: Path


@dataclass(frozen=True)
class BmsConfig:
    bms_dir: Path
    bms_globs: tuple[str, ...]
    macros_dir: Path
    sym_dir: Path


def _require(data: Mapping, key: str) -> object:
    if key not in data:
        raise KeyError(f"config missing required key: {key!r}")
    return data[key]


def _corpus_config_from_dict(data: Mapping) -> CorpusConfig:
    return CorpusConfig(
        cobol_dir=Path(_require(data, "cobol_dir")),
        cobol_globs=tuple(_require(data, "cobol_globs")),
        jcl_dir=Path(_require(data, "jcl_dir")),
        jcl_globs=tuple(_require(data, "jcl_globs")),
        proclib_dirs=tuple(Path(p) for p in data.get("proclib_dirs", ())),
        csd_files=tuple(Path(p) for p in data.get("csd_files", ())),
        copybook_dirs=tuple(Path(p) for p in _require(data, "copybook_dirs")),
        copybook_extensions=tuple(
            data.get("copybook_extensions", DEFAULT_COPYBOOK_EXTENSIONS)
        ),
        out_dir=Path(_require(data, "out_dir")),
    )


def _bms_config_from_dict(data: Mapping) -> BmsConfig:
    return BmsConfig(
        bms_dir=Path(_require(data, "bms_dir")),
        bms_globs=tuple(data.get("bms_globs", DEFAULT_BMS_GLOBS)),
        macros_dir=Path(_require(data, "macros_dir")),
        sym_dir=Path(_require(data, "sym_dir")),
    )


def load_corpus_config(path: Path) -> CorpusConfig:
    data = yaml.safe_load(path.read_text())
    return _corpus_config_from_dict(_require(data, "corpus"))


def load_bms_config(path: Path) -> BmsConfig:
    data = yaml.safe_load(path.read_text())
    return _bms_config_from_dict(_require(data, "bms"))
