#!/usr/bin/env python3
"""Stage-0: GENERATE the BMS symbolic copybooks from a corpus's BMS map
sources.

A port of cics.bms.generate.generate_symbolic_copybooks. For each map source
in <bms_dir> matching <bms_globs> (both come from the --config TOML's `[bms]`
section; bms_globs defaults to ["*.bms"]), runs

    hlasm_export <map>.bms --syslib <macros_dir>/ | python -m bms_copybook_gen

and writes <sym_dir>/<stem>.cpy. This produces the symbolic copybooks the CICS
COBOL programs `COPY`, from source -- nothing pre-generated is shipped.
hlasm_export is built from the workspace's che-che4z-lsp-for-hlasm fork, which
cicada vendors; the DFHMSD/DFHMDI/DFHMDF prototype macros are the assembler
SYSLIB.

Invoke as: uv run python -m cobble.generate_sym --config <path>
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import BmsConfig, load_bms_config
from cobble.matching_files import matching_files
from cobble.path_utils import ensure_dir

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HLASM = (
    _REPO_ROOT.parent
    / "vendor"
    / "red-dragon"
    / "hlasm-bridge"
    / "che4z"
    / "build"
    / "bin"
    / "hlasm_export"
)


def _bms_sources(config: BmsConfig) -> list[Path]:
    """The BMS map sources in bms_dir, selected by the corpus's own globs.

    A glob rather than a fixed extension because a corpus's map directory may
    hold non-map members alongside the maps (one production corpus keeps its
    compile JCL in there, and every file is a .txt) -- feeding one of those to
    hlasm_export is a hard failure, so the selection has to be narrowable.
    """
    return matching_files(config.bms_dir, config.bms_globs)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus TOML config (see cobble/corpus_config.py / config/carddemo.toml)",
    )
    return parser.parse_args()


def _child_env() -> Mapping[str, str]:
    """The generator runs as `python -m bms_copybook_gen`, so the child needs
    the repo on its PYTHONPATH to import it."""
    return {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}


def _generate_one(bms: Path, config: BmsConfig, env: Mapping[str, str]) -> Path:
    """hlasm_export <map> | bms_copybook_gen -> <sym_dir>/<stem>.cpy.

    An empty copybook is raised rather than written: it would resolve at parse time
    and declare nothing, which reads downstream as a program with no working
    storage instead of as a build that failed here.
    """
    export = subprocess.run(
        [str(_HLASM), str(bms), "--syslib", str(config.macros_dir)],
        capture_output=True,
        check=True,
    )
    gen = subprocess.run(
        [sys.executable, "-m", "bms_copybook_gen"],
        input=export.stdout,
        capture_output=True,
        check=True,
        env=env,
    )
    if not gen.stdout.strip():
        raise RuntimeError(
            f"bms_copybook_gen produced an empty copybook for {bms.name} "
            f"(a BMS macro keyword is likely undeclared in {config.macros_dir})"
        )
    target = config.sym_dir / (bms.stem + ".cpy")
    target.write_bytes(gen.stdout)
    logger.info("  BMS: %s.cpy", bms.stem)
    return target


def main() -> int:
    configure_cli_logging()
    config = load_bms_config(_parse_args().config)

    if not _HLASM.is_file():
        sys.exit(
            f"hlasm_export not built: {_HLASM} (run `make setup` or `make hlasm` at the forge root)"
        )
    ensure_dir(config.sym_dir)
    env = _child_env()
    written = tuple(_generate_one(bms, config, env) for bms in _bms_sources(config))
    logger.info("generated %d symbolic copybooks -> %s", len(written), config.sym_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
