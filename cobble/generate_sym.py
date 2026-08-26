#!/usr/bin/env python3
"""Stage-0: GENERATE the BMS symbolic copybooks from a corpus's BMS map
sources.

A port of cics.bms.generate.generate_symbolic_copybooks. For each map source
in <bms_dir> matching <bms_globs> (both come from the --config YAML's `bms:`
section; bms_globs defaults to ["*.bms"]), runs

    hlasm_export <map>.bms --syslib <macros_dir>/ | python -m cobble.bms_copybook_gen

and writes <sym_dir>/<stem>.cpy. This produces the symbolic copybooks the CICS
COBOL programs `COPY`, from source -- nothing pre-generated is shipped.
hlasm_export is built from the che-che4z-lsp-for-hlasm submodule; the
DFHMSD/DFHMDI/DFHMDF prototype macros are the assembler SYSLIB.

Invoke as: uv run python -m cobble.generate_sym --config <path>
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from cobble.corpus_config import BmsConfig, load_bms_config
from cobble.matching_files import matching_files

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HLASM = (
    _REPO_ROOT / "vendor" / "che-che4z-lsp-for-hlasm" / "build" / "bin" / "hlasm_export"
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
        help="Path to a corpus YAML config (see cobble/corpus_config.py / config/carddemo.yaml)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_bms_config(args.config)

    if not _HLASM.is_file():
        sys.exit(
            f"hlasm_export not built: {_HLASM} (run `make jars` / the HLASM build first)"
        )
    syslib_args = ["--syslib", str(config.macros_dir)]
    config.sym_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
    }  # so `python -m cobble.bms_copybook_gen` resolves

    written = 0
    for bms in _bms_sources(config):
        export = subprocess.run(
            [str(_HLASM), str(bms), *syslib_args], capture_output=True, check=True
        )
        gen = subprocess.run(
            [sys.executable, "-m", "cobble.bms_copybook_gen"],
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
        (config.sym_dir / (bms.stem + ".cpy")).write_bytes(gen.stdout)
        written += 1
        print(f"  BMS: {bms.stem}.cpy")
    print(f"generated {written} symbolic copybooks -> {config.sym_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
