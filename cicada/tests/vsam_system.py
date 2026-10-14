"""Test helper: a catnip system holding test clusters and their paths, and the CICS file table over it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.labels import KsdsLabel
from catnip.system_catalog import SystemCatalog


@dataclass(frozen=True)
class SeedAix:
    file: str
    key_offset: int
    key_length: int
    unique: bool


@dataclass(frozen=True)
class SeedCluster:
    file: str
    lrecl: int
    key_length: int
    records: tuple[bytes, ...]
    aix: tuple[SeedAix, ...] = ()


def _cluster(system: SystemCatalog, cluster: SeedCluster) -> Mapping[str, str]:
    dsn = f"TEST.{cluster.file}"
    label = KsdsLabel(cluster.lrecl, 0, cluster.key_length)
    ordered = sorted(cluster.records, key=lambda r: r[: cluster.key_length])
    system.create(dsn, label).path.write_bytes(b"".join(ordered))
    paths = {aix.file: _path(system, dsn, aix) for aix in cluster.aix}
    return {cluster.file: dsn, **paths}


def _path(system: SystemCatalog, base: str, aix: SeedAix) -> str:
    system.define_aix(
        AlternateIndex(f"{base}.AIX", base, aix.key_offset, aix.key_length, aix.unique)
    )
    system.define_path(CatalogPath(f"{base}.PATH", f"{base}.AIX"))
    return f"{base}.PATH"


def build_test_system(
    root: Path, clusters: Sequence[SeedCluster]
) -> tuple[SystemCatalog, dict[str, str]]:
    system = SystemCatalog(root / "system")
    dsnames = {name: dsn for c in clusters for name, dsn in _cluster(system, c).items()}
    return system, dsnames
