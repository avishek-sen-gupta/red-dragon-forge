#!/usr/bin/env python3
"""Stage-0: GENERATE the BMS symbolic copybooks from the CardDemo .bms map sources.

A port of cics.bms.generate.generate_symbolic_copybooks. For each
vendor/carddemo/app/bms/*.bms, runs

    hlasm_export <map>.bms --syslib bms-macros/ | python -m cobble.bms_copybook_gen

and writes sym/<stem>.cpy. This produces the symbolic copybooks the CICS COBOL
programs `COPY`, from source — nothing pre-generated is shipped. hlasm_export is
built from the che-che4z-lsp-for-hlasm submodule; the DFHMSD/DFHMDI/DFHMDF
prototype macros in bms-macros/ are the assembler SYSLIB.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_HLASM = _HERE / "third-party" / "che-che4z-lsp-for-hlasm" / "build" / "bin" / "hlasm_export"
_BMS_DIR = _HERE / "vendor" / "carddemo" / "app" / "bms"
_MACROS = _HERE / "bms-macros"
_OUT = _HERE / "sym"


def main() -> int:
    if not _HLASM.is_file():
        sys.exit(f"hlasm_export not built: {_HLASM} (run `make jars` / the HLASM build first)")
    syslib_args = ["--syslib", str(_MACROS)]
    _OUT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(_HERE)}  # so `python -m cobble.bms_copybook_gen` resolves

    written = 0
    for bms in sorted(_BMS_DIR.glob("*.bms")):
        export = subprocess.run(
            [str(_HLASM), str(bms), *syslib_args], capture_output=True, check=True
        )
        gen = subprocess.run(
            [sys.executable, "-m", "cobble.bms_copybook_gen"],
            input=export.stdout, capture_output=True, check=True, env=env,
        )
        if not gen.stdout.strip():
            raise RuntimeError(
                f"bms_copybook_gen produced an empty copybook for {bms.name} "
                f"(a BMS macro keyword is likely undeclared in {_MACROS})"
            )
        (_OUT / (bms.stem + ".cpy")).write_bytes(gen.stdout)
        written += 1
        print(f"  BMS: {bms.stem}.cpy")
    print(f"generated {written} symbolic copybooks -> {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
