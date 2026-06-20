"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jackal.model import DD, DispNormal, DispStatus


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path


class DatasetCatalog:
    """Imperative shell: owns the job workdir and the DSN->file mapping."""

    def __init__(self, workdir: Path):
        self._workdir = workdir
        self._datasets: dict[str, Dataset] = {}

    def seed(self, dsn: str, path: Path) -> None:
        self._datasets[dsn] = Dataset(dsn=dsn, path=path)

    def resolve(self, dsn: str) -> Dataset:
        return self._datasets[dsn]

    def allocate(self, dd: DD) -> Dataset:
        if dd.disp.status in (DispStatus.OLD, DispStatus.SHR, DispStatus.MOD):
            return self._datasets[dd.dsn]
        path = self._workdir / dd.dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(dsn=dd.dsn, path=path)
        self._datasets[dd.dsn] = ds
        return ds

    def dispose(self, dd: DD) -> None:
        if dd.disp.normal is DispNormal.DELETE:
            self._datasets[dd.dsn].path.unlink()
            del self._datasets[dd.dsn]

    @property
    def workdir(self) -> Path:
        return self._workdir
