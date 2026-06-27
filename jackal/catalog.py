"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from interpreter.cobol.file_enums import FileOrganization, OpenMode
from jackal.model import DD, DatasetOrg, DispNormal, DispStatus


@dataclass(frozen=True)
class DatasetSpec:
    dsn: str
    org: DatasetOrg
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


@dataclass(frozen=True)
class Dataset:
    dsn: str
    path: Path
    org: DatasetOrg = DatasetOrg.PS
    key_offset: int = 0
    key_length: int = 0
    record_size: int = 0


_ORG_MAP: dict[DatasetOrg, FileOrganization] = {
    DatasetOrg.PS: FileOrganization.SEQUENTIAL,
    DatasetOrg.KSDS: FileOrganization.INDEXED,
}


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

    def allocate_new(self, spec: DatasetSpec) -> Dataset:
        if spec.dsn in self._datasets:
            raise ValueError(f"DSN already allocated: {spec.dsn}")
        if spec.org is DatasetOrg.KSDS:
            if spec.record_size == 0:
                raise ValueError(f"KSDS record_size must be > 0: {spec.dsn}")
            if spec.key_length == 0:
                raise ValueError(f"KSDS key_length must be > 0: {spec.dsn}")
        path = self._workdir / spec.dsn.replace(".", "_")
        path.write_bytes(b"")
        ds = Dataset(
            dsn=spec.dsn,
            path=path,
            org=spec.org,
            key_offset=spec.key_offset,
            key_length=spec.key_length,
            record_size=spec.record_size,
        )
        self._datasets[spec.dsn] = ds
        return ds

    def open_dataset(
        self, dsn: str, mode: OpenMode, record_size: int | None = None
    ) -> FileOrganizationDriver:
        # record_size override exists solely as a jackal-ifq workaround: PS inputs
        # allocated via allocate(dd) carry record_size=0; callers that know the true
        # record size (e.g. REPRO borrowing the output KSDS value) pass it here.
        # Remove this parameter and all call sites that supply it when jackal-ifq is fixed.
        ds = self._datasets[dsn]
        rl = record_size if record_size is not None else ds.record_size
        return open_driver(
            _ORG_MAP[ds.org], ds.path, mode, rl, ds.key_offset, ds.key_length
        )

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
        # DELETE disposition removes the dataset; delegate to delete_dsn so a DD
        # that was never allocated (sysout, optional, or a step that failed before
        # allocation) is a safe no-op instead of a KeyError.
        if dd.disp.normal is DispNormal.DELETE:
            self.delete_dsn(dd.dsn)

    @property
    def workdir(self) -> Path:
        return self._workdir
