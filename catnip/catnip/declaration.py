"""A data declaration: the TOML a system is installed from, parsed into typed entries as it is read."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from catnip.declaration_error import DeclarationError
from catnip.gdg import Empty, GdgOrder, Scratch
from catnip.labels import RecordFormat
from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class Unseeded:
    pass


@dataclass(frozen=True)
class SequentialEntry:
    dsn: str
    seed: Path
    recfm: RecordFormat
    lrecl: int


@dataclass(frozen=True)
class AixEntry:
    dsn: str
    path: str
    key_offset: int
    key_length: int
    unique: bool


@dataclass(frozen=True)
class KsdsEntry:
    dsn: str
    seed: Path | Unseeded
    lrecl: int
    key_offset: int
    key_length: int
    aix: tuple[AixEntry, ...]


@dataclass(frozen=True)
class GdgEntry:
    name: str
    limit: int
    empty: Empty
    scratch: Scratch
    order: GdgOrder


@dataclass(frozen=True)
class Declaration:
    data_dir: Path
    sequential: tuple[SequentialEntry, ...]
    ksds: tuple[KsdsEntry, ...]
    gdg: tuple[GdgEntry, ...]


class _Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _SequentialWire(_Wire):
    dsn: str
    seed: str = Field(alias="from")
    recfm: RecordFormat
    lrecl: int

    def model(self, data_dir: Path) -> SequentialEntry:
        return SequentialEntry(self.dsn, data_dir / self.seed, self.recfm, self.lrecl)


class _AixWire(_Wire):
    dsn: str
    path: str
    key_offset: int
    key_length: int
    unique: bool

    def model(self) -> AixEntry:
        return AixEntry(
            self.dsn, self.path, self.key_offset, self.key_length, self.unique
        )


class _ClusterWire(_Wire):
    dsn: str
    lrecl: int
    key_offset: int
    key_length: int
    aix: tuple[_AixWire, ...] = ()

    def entry(self, seed: Path | Unseeded) -> KsdsEntry:
        return KsdsEntry(
            self.dsn,
            seed,
            self.lrecl,
            self.key_offset,
            self.key_length,
            tuple(aix.model() for aix in self.aix),
        )


class _SeededKsdsWire(_ClusterWire):
    seed: str = Field(alias="from")

    def model(self, data_dir: Path) -> KsdsEntry:
        return self.entry(data_dir / self.seed)


class _EmptyKsdsWire(_ClusterWire):
    def model(self, data_dir: Path) -> KsdsEntry:
        return self.entry(Unseeded())


class _GdgWire(_Wire):
    name: str
    limit: int
    empty: Empty
    scratch: Scratch
    order: GdgOrder

    def model(self) -> GdgEntry:
        return GdgEntry(self.name, self.limit, self.empty, self.scratch, self.order)


def _expanded(raw: str) -> Path:
    expanded = os.path.expandvars(raw)
    if "$" in expanded:
        raise DeclarationError(f"data_dir: unset environment variable in {raw!r}")
    return Path(expanded)


class _DeclarationWire(_Wire):
    data_dir: str
    sequential: tuple[_SequentialWire, ...] = ()
    ksds: tuple[_SeededKsdsWire | _EmptyKsdsWire, ...] = ()
    gdg: tuple[_GdgWire, ...] = ()

    def model(self) -> Declaration:
        data_dir = _expanded(self.data_dir)
        return Declaration(
            data_dir,
            tuple(entry.model(data_dir) for entry in self.sequential),
            tuple(entry.model(data_dir) for entry in self.ksds),
            tuple(entry.model() for entry in self.gdg),
        )


def load_declaration(path: Path) -> Declaration:
    return _DeclarationWire.model_validate(
        tomllib.loads(path.read_text("utf-8"))
    ).model()
