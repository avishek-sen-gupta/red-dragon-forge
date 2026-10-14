"""A region's CICS files, each resolved to its cataloged cluster or path."""

from __future__ import annotations

from collections.abc import Mapping

from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, PathView
from catnip.system_catalog import NotCataloged, SystemCatalog


class FileTableError(ValueError):
    pass


def _resolved(system: SystemCatalog, name: str, dsn: str) -> Dataset:
    match system.lookup(dsn):
        case Dataset(label=KsdsLabel() | PathView()) as dataset:
            return dataset
        case Dataset():
            raise FileTableError(f"CICS file {name}: {dsn} is not a KSDS or path")
        case NotCataloged():
            raise FileTableError(f"CICS file {name}: {dsn} is not cataloged")


def cics_files(system: SystemCatalog, dsnames: Mapping[str, str]) -> dict[str, Dataset]:
    return {
        name.upper(): _resolved(system, name.upper(), dsn)
        for name, dsn in dsnames.items()
    }
