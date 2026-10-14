"""Alternate indexes and paths in the system catalog."""

from __future__ import annotations

from pathlib import Path

import pytest
from catnip.alternate_index import AlternateIndex
from catnip.catalog_error import CatalogError
from catnip.catalog_path import CatalogPath
from catnip.dataset import Dataset
from catnip.labels import KsdsLabel, PathView, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from catnip.system_catalog_removal import remove_cataloged
from cobol_asg.file_enums import OpenMode
from interpreter.cobol.access_result import AccessCondition, AccessResult
from tests.covers import NotLanguageFeature, covers

_KSDS = KsdsLabel(8, 0, 3)
_AIX = AlternateIndex("T.AIX", "T.KSDS", 3, 3, False)
_PATH = CatalogPath("T.PATH", "T.AIX")


def _system(tmp_path: Path) -> SystemCatalog:
    system = SystemCatalog(tmp_path / "system")
    system.create("T.KSDS", _KSDS).path.write_bytes(b"001BBBxx002AAAyy003AAAzz")
    system.define_aix(_AIX)
    system.define_path(_PATH)
    return system


def _read_three(found: Dataset | NotCataloged) -> tuple[AccessResult, ...]:
    match found:
        case Dataset():
            drv = found.opened(OpenMode.INPUT)
            seen = tuple(drv.read_seq() for _ in range(3))
            drv.close()
            return seen
        case NotCataloged():
            return ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_path_survives_reopening_and_opens_the_base_in_alternate_key_order(
    tmp_path: Path,
) -> None:
    _system(tmp_path)
    reopened = SystemCatalog(tmp_path / "system")
    path = reopened.lookup("T.PATH")
    seen = _read_three(path)

    assert path == Dataset(
        "T.PATH",
        tmp_path / "system" / "datasets" / "T.KSDS",
        PathView(_KSDS, 3, 3, False),
    )
    assert seen == (
        AccessResult(AccessCondition.DUPLICATES_FOLLOW, b"002AAAyy"),
        AccessResult(AccessCondition.OK, b"003AAAzz"),
        AccessResult(AccessCondition.OK, b"001BBBxx"),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_removing_a_cluster_removes_its_alternate_indexes_and_paths(
    tmp_path: Path,
) -> None:
    system = _system(tmp_path)
    remove_cataloged(system, "T.KSDS")
    reopened = SystemCatalog(tmp_path / "system")

    assert (reopened.lookup("T.KSDS"), reopened.lookup("T.PATH")) == (
        NotCataloged(),
        NotCataloged(),
    )
    assert (tmp_path / "system" / "datasets" / "T.KSDS").exists() is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_an_alternate_index_needs_a_cataloged_cluster_and_a_path_needs_its_index(
    tmp_path: Path,
) -> None:
    system = SystemCatalog(tmp_path / "system")
    system.create("T.SEQ", SequentialLabel(RecordFormat.FB, 8))

    with pytest.raises(CatalogError) as over_sequential:
        system.define_aix(AlternateIndex("T.AIX", "T.SEQ", 3, 3, False))
    with pytest.raises(CatalogError) as without_index:
        system.define_path(CatalogPath("T.PATH", "T.MISSING"))

    assert (
        str(over_sequential.value)
        == "T.AIX: base cluster T.SEQ is not a cataloged KSDS"
    )
    assert (
        str(without_index.value) == "T.PATH: alternate index T.MISSING is not cataloged"
    )
