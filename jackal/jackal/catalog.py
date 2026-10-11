"""Job-scoped dataset catalog: DSN -> backing file, with DISP lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cobol_asg.file_enums import FileOrganization, OpenMode
from interpreter.cobol.file_drivers import FileOrganizationDriver, open_driver
from jackal.catalog_stores import Table
from jackal.model import (
    DD,
    DSN,
    DatasetOrg,
    DirectDSN,
    DispNormal,
    DispStatus,
    StepReference,
    TempRef,
)
from jackal.results import AllocationError


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


@dataclass(frozen=True)
class Unallocated:
    dd: DD[StepReference]
    error: AllocationError


_ORG_MAP: dict[DatasetOrg, FileOrganization] = {
    DatasetOrg.PS: FileOrganization.SEQUENTIAL,
    DatasetOrg.KSDS: FileOrganization.INDEXED,
}


def _require_positive(value: int, what: str, dsn: str) -> None:
    if value == 0:
        raise ValueError(f"KSDS {what} must be > 0: {dsn}")


def _check_spec(spec: DatasetSpec) -> None:
    if spec.org is not DatasetOrg.KSDS:
        return
    _require_positive(spec.record_size, "record_size", spec.dsn)
    _require_positive(spec.key_length, "key_length", spec.dsn)


class DatasetCatalog:
    """Imperative shell: owns the job workdir and the DSN->file mapping."""

    def __init__(self, workdir: Path, data_dir: Path):
        self._workdir = workdir
        self._data_dir = data_dir
        self._datasets: Table[str, Dataset] = Table()
        self._temps: Table[str, Dataset] = Table()

    def seed(self, dsn: str, path: Path) -> None:
        self._datasets.put(dsn, Dataset(dsn=dsn, path=path))

    def resolve(self, dsn: str) -> Dataset:
        return self._datasets.get(dsn)

    def allocate(self, dd: DD[StepReference]) -> Dataset | Unallocated:
        match dd.dsn:
            case TempRef(name=name):
                return self._allocate_temp(dd, name)
            case _:
                return self._allocate_direct(dd, dd.dsn.dataset_name())

    def created_empty(self, dd: DD[StepReference]) -> Dataset:
        match dd.dsn:
            case TempRef(name=name):
                return self._temps.put(name, self._created(name, self._workdir / name))
            case _:
                return self._created_direct(dd.dsn.dataset_name())

    def _created_direct(self, name: str) -> Dataset:
        return self._created(name, self._work_path(name))

    def _work_path(self, name: str) -> Path:
        return self._workdir / name.replace(".", "_")

    def _created(self, dsn: str, path: Path) -> Dataset:
        path.write_bytes(b"")
        return self._datasets.put(dsn, Dataset(dsn=dsn, path=path))

    def _allocate_temp(self, dd: DD[StepReference], name: str) -> Dataset | Unallocated:
        if dd.disposition().status is DispStatus.NEW:
            return self._new_temp(dd, name)
        if not self._temps.has(name):
            return Unallocated(dd, AllocationError.TEMP_NOT_CREATED)
        return self._datasets.get(self._temps.get(name).dsn)

    def _new_temp(self, dd: DD[StepReference], name: str) -> Dataset | Unallocated:
        if self._temps.has(name):
            return Unallocated(dd, AllocationError.DUPLICATE_NAME)
        return self.created_empty(dd)

    def _allocate_direct(
        self, dd: DD[StepReference], name: str
    ) -> Dataset | Unallocated:
        if dd.disposition().status is DispStatus.NEW:
            return self._new_direct(dd, name)
        return self._existing(dd, name)

    def _new_direct(self, dd: DD[StepReference], name: str) -> Dataset | Unallocated:
        if self._datasets.has(name):
            return Unallocated(dd, AllocationError.DUPLICATE_NAME)
        return self.created_empty(dd)

    def _existing(self, dd: DD[StepReference], name: str) -> Dataset | Unallocated:
        if self._datasets.has(name):
            return self._datasets.get(name)
        candidate = self._data_dir / name
        if candidate.exists():
            return self._datasets.put(name, Dataset(dsn=name, path=candidate))
        return self._missing(dd)

    def _missing(self, dd: DD[StepReference]) -> Dataset | Unallocated:
        if dd.disposition().status is DispStatus.MOD:
            return self.created_empty(dd)
        return Unallocated(dd, AllocationError.DATASET_NOT_FOUND)

    def delete_if_new(self, dd: DD[StepReference]) -> None:
        if dd.disposition().status is DispStatus.NEW:
            self._delete(dd.dsn)

    def allocate_new(self, spec: DatasetSpec) -> Dataset:
        if self._datasets.has(spec.dsn):
            raise ValueError(f"DSN already allocated: {spec.dsn}")
        _check_spec(spec)
        path = self._work_path(spec.dsn)
        path.write_bytes(b"")
        return self._datasets.put(
            spec.dsn,
            Dataset(
                dsn=spec.dsn,
                path=path,
                org=spec.org,
                key_offset=spec.key_offset,
                key_length=spec.key_length,
                record_size=spec.record_size,
            ),
        )

    def open_dataset(self, dsn: str, mode: OpenMode) -> FileOrganizationDriver:
        return self.open_dataset_with_record_size(
            dsn, mode, self._datasets.get(dsn).record_size
        )

    def open_dataset_with_record_size(
        self, dsn: str, mode: OpenMode, record_size: int
    ) -> FileOrganizationDriver:
        ds = self._datasets.get(dsn)
        return open_driver(
            _ORG_MAP[ds.org], ds.path, mode, record_size, ds.key_offset, ds.key_length
        )

    def delete_dsn(self, dsn: str) -> bool:
        if not self._datasets.has(dsn):
            return False
        self._datasets.take(dsn).path.unlink(missing_ok=True)
        return True

    def dispose(self, dd: DD[StepReference]) -> None:
        if dd.disposition().normal is DispNormal.DELETE:
            self._delete(dd.dsn)

    def _delete(self, dsn: DSN[StepReference]) -> None:
        match dsn:
            case TempRef(name=name):
                self._delete_temp(name)
            case _:
                self._delete_direct(dsn)

    def _delete_direct(self, dsn: DSN[StepReference]) -> None:
        match dsn:
            case DirectDSN():
                self.delete_dsn(dsn.dataset_name())
            case _:
                return

    def _delete_temp(self, name: str) -> None:
        if self._temps.has(name):
            self.delete_dsn(self._temps.take(name).dsn)

    def cleanup_temps(self) -> None:
        for ds in self._temps.drain():
            self.delete_dsn(ds.dsn)

    @property
    def workdir(self) -> Path:
        return self._workdir
