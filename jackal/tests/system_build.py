"""Test helpers: a system catalog under a test's directory, a job's catalog over it, and labelled uploads."""

from __future__ import annotations

from pathlib import Path

from catnip.dataset import Dataset
from catnip.gdg import GdgBase
from catnip.labels import Label, RecordFormat, SequentialLabel
from catnip.system_catalog import SystemCatalog
from jackal.catalog import DatasetCatalog

FB80 = SequentialLabel(RecordFormat.FB, 80)


def system(root: Path) -> SystemCatalog:
    return SystemCatalog(root / "system")


def scratch(root: Path) -> Path:
    path = root / "scratch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_catalog(root: Path) -> DatasetCatalog:
    return DatasetCatalog(scratch(root), system(root))


def upload(root: Path, dsn: str, data: bytes, label: Label = FB80) -> Dataset:
    source = root / f"{dsn}.upload"
    source.write_bytes(data)
    added = system(root).add(dsn, source, label)
    source.unlink()
    return added


def gdg(root: Path, base: GdgBase, label: Label = FB80) -> GdgBase:
    for number in base.generations:
        upload(root, f"{base.name}.G{number:04d}V00", b"", label)
    return system(root).catalog_gdg(base)
