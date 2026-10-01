"""corpus_config.py — TOML-driven corpus configuration for build_graph.py and
generate_sym.py, so cobble can extract a knowledge graph / generate BMS
copybooks from any COBOL/CICS/JCL corpus without editing Python source.

TOML rather than YAML because every other config this pipeline reads is TOML --
the parse, depgraph and srccfg stages all are -- and one corpus described in two
markup languages is a corpus described twice. tomllib is stdlib, so the switch
also drops a dependency.

The TOML is validated on arrival into typed tables (corpus_table, bms_table) and
mapped onto the dataclasses here; nothing indexes the parsed dict. Every
required key is required by its table -- a missing one fails validation naming
it rather than silently guessing a path. List-shaped fields are never None; a
list left out of the file is an empty tuple, except for the two that describe how files
are NAMED rather than where they live (`copybook_extensions`, `bms_globs`):
those fall back to the conventions cobble shipped with. Keys a table does not
declare are ignored, so a config still naming a key cobble no longer reads
loads. Paths expand ~ and environment variables and are otherwise left
relative to the caller's working directory.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from cobble.bms_file import BmsFile
from cobble.bms_table import BmsTable
from cobble.cics.synth_csd import TransidRule
from cobble.corpus_file import CorpusFile
from cobble.corpus_table import CorpusTable
from cobble.path_utils import config_path


# The extensions the ProLeap bridge has always searched (see
# proleap-bridge/src/main/java/org/reddragon/bridge/Main.java). Kept as the
# default so a config written before `copybook_extensions` existed resolves
# copybooks exactly as it did before.
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
    # The directory cobble-parse-corpus wrote: one JSON ASG per member. An INPUT to
    # this stage, like cobol_dir -- cobble-build reads ASGs and never makes them,
    # because a parse is 4-7 seconds of JVM per member and has been paid already.
    asg_dir: Path
    # How this corpus's member names encode the transaction each one serves, for
    # `python -m cobble.generate_csd` to reconstruct a CSD the site never
    # exported. Empty for a corpus that ships a real one; see cics/synth_csd.py.
    transid_rules: tuple[TransidRule, ...] = ()


@dataclass(frozen=True)
class BmsConfig:
    bms_dir: Path
    bms_globs: tuple[str, ...]
    macros_dir: Path
    sym_dir: Path


def _corpus_config(table: CorpusTable) -> CorpusConfig:
    return CorpusConfig(
        cobol_dir=config_path(table.cobol_dir),
        cobol_globs=table.cobol_globs,
        jcl_dir=config_path(table.jcl_dir),
        jcl_globs=table.jcl_globs,
        proclib_dirs=tuple(map(config_path, table.proclib_dirs)),
        csd_files=tuple(map(config_path, table.csd_files)),
        copybook_dirs=tuple(map(config_path, table.copybook_dirs)),
        copybook_extensions=table.copybook_extensions,
        asg_dir=config_path(table.asg_dir),
        transid_rules=table.transid_rules,
    )


def _bms_config(table: BmsTable) -> BmsConfig:
    return BmsConfig(
        bms_dir=config_path(table.bms_dir),
        bms_globs=table.bms_globs,
        macros_dir=config_path(table.macros_dir),
        sym_dir=config_path(table.sym_dir),
    )


def load_corpus_config(path: Path) -> CorpusConfig:
    return _corpus_config(
        CorpusFile.model_validate(
            tomllib.loads(path.read_text(encoding="utf-8"))
        ).corpus
    )


def load_bms_config(path: Path) -> BmsConfig:
    return _bms_config(
        BmsFile.model_validate(tomllib.loads(path.read_text(encoding="utf-8"))).bms
    )
