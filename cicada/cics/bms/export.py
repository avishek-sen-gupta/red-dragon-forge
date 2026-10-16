"""A build's BMS outputs: each mapset's hlasm_export JSON, and the symbolic copybooks, regenerated fresh every build."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Sequence
from pathlib import Path

from cics.bms.catalog import mapset_json
from cics.bms.generate import generate_symbolic_copybooks

logger = logging.getLogger(__name__)


def _first_hit(bms_files: Sequence[Path]) -> dict[str, Path]:
    return {bms.stem: bms for bms in reversed(bms_files)}


def _exported(bms: Path, hlasm_export: str, target: Path) -> Path:
    target.write_text(mapset_json(bms, hlasm_export), encoding="utf-8")
    logger.info("exported mapset %s to %s", bms.name, target)
    return target


def exported_mapsets(
    bms_dirs: Sequence[Path], hlasm_export: str, maps_dir: Path
) -> dict[str, Path]:
    maps_dir.mkdir(parents=True, exist_ok=True)
    found = _first_hit(tuple(bms for d in bms_dirs for bms in sorted(d.glob("*.bms"))))
    return {
        name: _exported(bms, hlasm_export, maps_dir / f"{name}.json")
        for name, bms in sorted(found.items())
    }


def fresh_symbolic_copybooks(
    bms_dirs: Sequence[Path], hlasm_export: str, sym_dir: Path
) -> None:
    shutil.rmtree(sym_dir, ignore_errors=True)
    for bms_dir in bms_dirs:
        generate_symbolic_copybooks(
            bms_dir=bms_dir, out_dir=sym_dir, hlasm_export_bin=hlasm_export
        )
