"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jackal.model import DD, DatasetOrg, DispNormal, DispStatus


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path
    org: DatasetOrg = DatasetOrg.PS
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


class DatasetCatalog:
    """Imperative shell: owns the job workdir and the DSN->file mapping."""

    def __init__(self, workdir: Path, data_dir: Path):
        self._workdir = workdir
        self._data_dir = data_dir
        self._datasets: dict[str, Dataset] = {}

    def seed(self, dsn: str, path: Path) -> None:
        self._datasets[dsn] = Dataset(dsn=dsn, path=path)

    def resolve(self, dsn: str) -> Dataset:
        return self._datasets[dsn]

    def allocate(self, dd: DD) -> Dataset:
        if dd.disp.status in (DispStatus.OLD, DispStatus.SHR):
            if dd.dsn in self._datasets:
                return self._datasets[dd.dsn]
            candidate = self._data_dir / dd.dsn
            if candidate.exists():
                ds = Dataset(dsn=dd.dsn, path=candidate)
                self._datasets[dd.dsn] = ds
                return ds
            raise KeyError(dd.dsn)
        if dd.disp.status is DispStatus.MOD:
            # MOD: extend if exists, create if not
            if dd.dsn in self._datasets:
                return self._datasets[dd.dsn]
            candidate = self._data_dir / dd.dsn
            if candidate.exists():
                ds = Dataset(dsn=dd.dsn, path=candidate)
                self._datasets[dd.dsn] = ds
                return ds
            path = self._workdir / dd.dsn.replace(".", "_")
            path.write_bytes(b"")
            ds = Dataset(dsn=dd.dsn, path=path)
            self._datasets[dd.dsn] = ds
            return ds
        path = self._workdir / dd.dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(dsn=dd.dsn, path=path)
        self._datasets[dd.dsn] = ds
        return ds

    def allocate_ksds(
        self, dsn: str, key_offset: int, key_length: int, record_size: int
    ) -> Dataset:
        path = self._workdir / dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(
            dsn=dsn,
            path=path,
            org=DatasetOrg.KSDS,
            key_offset=key_offset,
            key_length=key_length,
            record_size=record_size,
        )
        self._datasets[dsn] = ds
        return ds

    def delete_dsn(self, dsn: str) -> bool:
        """Remove a dataset from the catalog and delete its backing file.

        Returns True if the dataset existed and was deleted, False if not found.
        """
        if dsn not in self._datasets:
            return False
        ds = self._datasets.pop(dsn)
        ds.path.unlink(missing_ok=True)
        return True

    def dispose(self, dd: DD) -> None:
        if dd.disp.normal is DispNormal.DELETE:
            self._datasets[dd.dsn].path.unlink()
            del self._datasets[dd.dsn]

    @property
    def workdir(self) -> Path:
        return self._workdir
