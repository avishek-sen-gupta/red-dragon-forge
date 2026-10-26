"""catnip install: a data declaration validated whole, stopping at its first fault, then loaded into a system catalog."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from itertools import chain, islice
from pathlib import Path

from catnip.alternate_index import AlternateIndex
from catnip.catalog_path import CatalogPath
from catnip.declaration import (
    AixEntry,
    Declaration,
    GdgEntry,
    KsdsEntry,
    SequentialEntry,
    Unseeded,
)
from catnip.declaration_error import DeclarationError
from catnip.gdg import GdgBase
from catnip.labels import KsdsLabel, SequentialLabel
from catnip.system_catalog import SystemCatalog

logger = logging.getLogger(__name__)

_Unit = tuple[str, Callable[[], Iterable[str]]]


def _nothing() -> Iterable[str]:
    return ()


def _seed_problems(dsn: str, data_dir: Path, seed: Path, lrecl: int) -> Iterator[str]:
    declared = seed.relative_to(data_dir)
    if not seed.exists():
        yield f"{dsn}: from: {declared} does not exist"
        return
    size = seed.stat().st_size
    if size % lrecl:
        yield (
            f"{dsn}: from: {declared} holds {size} bytes, "
            f"not a whole number of {lrecl}-byte records"
        )


def _declared_seed_problems(
    dsn: str, data_dir: Path, seed: Path | Unseeded, lrecl: int
) -> Iterable[str]:
    match seed:
        case Unseeded():
            return ()
        case Path():
            return _seed_problems(dsn, data_dir, seed, lrecl)


def _sequential_problems(data_dir: Path, entry: SequentialEntry) -> Iterable[str]:
    return _declared_seed_problems(entry.dsn, data_dir, entry.seed, entry.lrecl)


def _overrun(dsn: str, key_offset: int, key_length: int, lrecl: int) -> Iterable[str]:
    if key_offset + key_length <= lrecl:
        return ()
    return (
        f"{dsn}: key_offset: key {key_offset}+{key_length} overruns the {lrecl}-byte record",
    )


def _seed_bytes(entry: KsdsEntry) -> bytes:
    match entry.seed:
        case Unseeded():
            return b""
        case Path():
            return entry.seed.read_bytes()


def _records(entry: KsdsEntry) -> tuple[bytes, ...]:
    data = _seed_bytes(entry)
    return tuple(data[at : at + entry.lrecl] for at in range(0, len(data), entry.lrecl))


def _keys(
    records: tuple[bytes, ...], key_offset: int, key_length: int
) -> tuple[bytes, ...]:
    return tuple(record[key_offset : key_offset + key_length] for record in records)


def _repeats(what: str, keys: tuple[bytes, ...]) -> Iterator[str]:
    counts = Counter(keys)
    return (f"{what} {key!r} repeats" for key in keys if counts[key] > 1)


def _ksds_problems(data_dir: Path, entry: KsdsEntry) -> Iterator[str]:
    yield from _declared_seed_problems(entry.dsn, data_dir, entry.seed, entry.lrecl)
    yield from _overrun(entry.dsn, entry.key_offset, entry.key_length, entry.lrecl)
    yield from _repeats(
        f"{entry.dsn}: from: primary key",
        _keys(_records(entry), entry.key_offset, entry.key_length),
    )


def _aix_problems(base: KsdsEntry, aix: AixEntry) -> Iterator[str]:
    yield from _overrun(aix.dsn, aix.key_offset, aix.key_length, base.lrecl)
    if aix.unique:
        yield from _repeats(
            f"{aix.dsn}: unique: alternate key",
            _keys(_records(base), aix.key_offset, aix.key_length),
        )


def _aix_units(base: KsdsEntry, aix: AixEntry) -> tuple[_Unit, ...]:
    return ((aix.dsn, partial(_aix_problems, base, aix)), (aix.path, _nothing))


def _ksds_units(data_dir: Path, entry: KsdsEntry) -> tuple[_Unit, ...]:
    return (
        (entry.dsn, partial(_ksds_problems, data_dir, entry)),
        *chain.from_iterable(_aix_units(entry, aix) for aix in entry.aix),
    )


def _units(declaration: Declaration) -> tuple[_Unit, ...]:
    data_dir = declaration.data_dir
    return (
        *(
            (entry.dsn, partial(_sequential_problems, data_dir, entry))
            for entry in declaration.sequential
        ),
        *chain.from_iterable(_ksds_units(data_dir, k) for k in declaration.ksds),
        *((gdg.name, _nothing) for gdg in declaration.gdg),
    )


def _unit_problems(earlier: tuple[str, ...], unit: _Unit) -> Iterable[str]:
    name, check = unit
    if name in earlier:
        return (f"{name}: dsn: declared twice",)
    return check()


def _problems(declaration: Declaration) -> Iterator[str]:
    units = _units(declaration)
    names = tuple(name for name, _ in units)
    return chain.from_iterable(
        _unit_problems(names[:at], unit) for at, unit in enumerate(units)
    )


def _logged(dsn: str) -> str:
    logger.info("installed %s", dsn)
    return dsn


def _add_sequential(system: SystemCatalog, entry: SequentialEntry) -> str:
    label = SequentialLabel(entry.recfm, entry.lrecl)
    match entry.seed:
        case Unseeded():
            system.create(entry.dsn, label)
        case Path():
            system.add(entry.dsn, entry.seed, label)
    return _logged(entry.dsn)


def _sorted(entry: KsdsEntry) -> bytes:
    end = entry.key_offset + entry.key_length

    def primary_key(record: bytes) -> bytes:
        return record[entry.key_offset : end]

    return b"".join(sorted(_records(entry), key=primary_key))


def _add_aix(system: SystemCatalog, base: str, aix: AixEntry) -> tuple[str, ...]:
    system.define_aix(
        AlternateIndex(aix.dsn, base, aix.key_offset, aix.key_length, aix.unique)
    )
    system.define_path(CatalogPath(aix.path, aix.dsn))
    return (_logged(aix.dsn), _logged(aix.path))


def _add_ksds(system: SystemCatalog, entry: KsdsEntry) -> tuple[str, ...]:
    label = KsdsLabel(entry.lrecl, entry.key_offset, entry.key_length)
    system.create(entry.dsn, label).path.write_bytes(_sorted(entry))
    return (
        _logged(entry.dsn),
        *chain.from_iterable(_add_aix(system, entry.dsn, aix) for aix in entry.aix),
    )


def _add_gdg(system: SystemCatalog, entry: GdgEntry) -> str:
    system.catalog_gdg(
        GdgBase(entry.name, entry.limit, entry.empty, entry.scratch, entry.order, ())
    )
    return _logged(entry.name)


def install(declaration: Declaration, system: SystemCatalog) -> tuple[str, ...]:
    first = tuple(islice(_problems(declaration), 1))
    if first:
        raise DeclarationError(first[0])
    return (
        *(_add_sequential(system, entry) for entry in declaration.sequential),
        *chain.from_iterable(_add_ksds(system, k) for k in declaration.ksds),
        *(_add_gdg(system, gdg) for gdg in declaration.gdg),
    )
