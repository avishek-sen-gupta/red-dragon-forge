"""A data declaration: the TOML a system is installed from, parsed into typed entries as it is read."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from catnip.declaration_error import DeclarationError
from catnip.gdg import Empty, GdgOrder, Scratch
from catnip.labels import RecordFormat
from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
    lrecl: int = Field(gt=0)

    def model(self, data_dir: Path) -> SequentialEntry:
        return SequentialEntry(self.dsn, data_dir / self.seed, self.recfm, self.lrecl)


class _AixWire(_Wire):
    dsn: str
    path: str
    key_offset: int = Field(ge=0)
    key_length: int = Field(gt=0)
    unique: bool

    def model(self) -> AixEntry:
        return AixEntry(
            self.dsn, self.path, self.key_offset, self.key_length, self.unique
        )


class _KsdsWire(_Wire):
    dsn: str
    seed: str = Field(alias="from", default="")
    lrecl: int = Field(gt=0)
    key_offset: int = Field(ge=0)
    key_length: int = Field(gt=0)
    aix: tuple[_AixWire, ...] = ()

    def model(self, data_dir: Path) -> KsdsEntry:
        return KsdsEntry(
            self.dsn,
            self._seed(data_dir),
            self.lrecl,
            self.key_offset,
            self.key_length,
            tuple(aix.model() for aix in self.aix),
        )

    def _seed(self, data_dir: Path) -> Path | Unseeded:
        if "seed" in self.model_fields_set:
            return data_dir / self.seed
        return Unseeded()


class _GdgWire(_Wire):
    name: str
    limit: int = Field(gt=0)
    empty: Empty
    scratch: Scratch
    order: GdgOrder

    def model(self) -> GdgEntry:
        return GdgEntry(self.name, self.limit, self.empty, self.scratch, self.order)


class _DeclarationWire(_Wire):
    data_dir: str
    sequential: tuple[_SequentialWire, ...] = ()
    ksds: tuple[_KsdsWire, ...] = ()
    gdg: tuple[_GdgWire, ...] = ()

    def model(self, base: Path) -> Declaration:
        data_dir = base / self.data_dir
        return Declaration(
            data_dir,
            tuple(entry.model(data_dir) for entry in self.sequential),
            tuple(entry.model(data_dir) for entry in self.ksds),
            tuple(entry.model() for entry in self.gdg),
        )


class _Lenient(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Unnamed(_Lenient):
    """An entry whose name did not parse: it is named by its position."""

    def label(self, index: int) -> str:
        return f"entry {index + 1}"


class _Named(_Unnamed):
    dsn: str

    def label(self, index: int) -> str:
        return self.dsn


class _NamedGdg(_Unnamed):
    name: str

    def label(self, index: int) -> str:
        return self.name


class _NamedCluster(_Named):
    aix: tuple[_Named | _Unnamed, ...] = ()


def _label(entries: Sequence[_Unnamed], index: int) -> str:
    if index < len(entries):
        return entries[index].label(index)
    return _Unnamed().label(index)


class _Names(_Lenient):
    """The declaration's entry names alone, read to say where a validation error lies."""

    sequential: tuple[_Named | _Unnamed, ...] = ()
    ksds: tuple[_NamedCluster | _Unnamed, ...] = ()
    gdg: tuple[_NamedGdg | _Unnamed, ...] = ()

    def label(self, section: str, index: int) -> str:
        sections: dict[str, Sequence[_Unnamed]] = {
            "sequential": self.sequential,
            "ksds": self.ksds,
            "gdg": self.gdg,
        }
        return _label(sections[section], index)

    def aix_label(self, cluster: int, index: int) -> str:
        clusters = self.ksds[cluster : cluster + 1]
        match clusters:
            case (_NamedCluster(aix=aix),):
                return _label(aix, index)
            case _:
                return _Unnamed().label(index)


def _names(text: str) -> _Names:
    try:
        return _Names.model_validate(tomllib.loads(text))
    except ValidationError:
        return _Names()


def _where(names: _Names, loc: tuple[int | str, ...]) -> tuple[str, ...]:
    match loc:
        case ("ksds", int(cluster), "aix", int(index), *field):
            return (f"[[ksds.aix]] {names.aix_label(cluster, index)}", *map(str, field))
        case (str(section), int(entry), *rest):
            return (f"[[{section}]] {names.label(section, entry)}", *map(str, rest))
        case _:
            return tuple(map(str, loc))


def _invalid(text: str, error: ValidationError) -> DeclarationError:
    first = error.errors()[0]
    return DeclarationError(
        ": ".join((*_where(_names(text), first["loc"]), first["msg"]))
    )


def _wire(path: Path, text: str) -> _DeclarationWire:
    try:
        return _DeclarationWire.model_validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as error:
        raise DeclarationError(f"{path}: {error}") from error
    except ValidationError as invalid:
        raise _invalid(text, invalid) from invalid


def load_declaration(path: Path) -> Declaration:
    return _wire(path, path.read_text("utf-8")).model(path.parent)
