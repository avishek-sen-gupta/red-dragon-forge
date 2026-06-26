"""VSAM dataset seeding from EBCDIC flat files.

Seeding writes the backing ``.dat`` files the file-resident drivers open. Base
KSDS clusters (``key_offset == 0``) are written key-sorted so the IndexedDriver
binary search applies; alternate-key datasets (``key_offset > 0``) are written
in source order (linear scan, no sort needed).
"""

from __future__ import annotations

from pathlib import Path

from cics.vsam.fct import DatasetConfig, FctConfig
from cics.vsam.format import read_flat_file, write_flat_file


def _ordered(cfg: DatasetConfig, records: list[bytes]) -> list[bytes]:
    """Key-sort base-KSDS records; leave alternate-key records in source order."""
    if cfg.key_offset == 0:
        return sorted(records, key=lambda r: r[: cfg.key_length])
    return records


def seed_records(
    vsam_dir: Path, fct: FctConfig, records_by_name: dict[str, list[bytes]]
) -> None:
    """Write each dataset's backing ``<NAME>.dat`` into ``vsam_dir``.

    Base KSDS records are key-sorted; alternate-key records keep source order.
    """
    vsam_dir.mkdir(parents=True, exist_ok=True)
    for name, records in records_by_name.items():
        canonical = name.upper()
        cfg = fct.datasets[canonical]
        write_flat_file(
            vsam_dir / f"{canonical}.dat",
            _ordered(cfg, records),
            cfg.record_length,
        )


def seed_vsam(fct_path: Path, data_dir: Path, vsam_dir: Path) -> None:
    """Read EBCDIC flat files and write key-sorted ``.dat`` files into vsam_dir."""
    fct = FctConfig.from_yaml(fct_path)
    records = {
        name: read_flat_file(data_dir / cfg.file, cfg.record_length)
        for name, cfg in fct.datasets.items()
    }
    seed_records(vsam_dir, fct, records)
