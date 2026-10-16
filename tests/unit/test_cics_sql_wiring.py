"""A [cics] run with [sql]: the Db2 connection is the current one, its backend commits at SYNCPOINT, and its rollback is the region's on_abend."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from catnip.system_catalog import SystemCatalog
from cics.tn3270.region import assemble_region
from interpreter.func_name import FuncName
from interpreter.project.cobol_compile import link_units
from interpreter.vm.builtins import Builtins
from interpreter.vm.vm_types import VMState
from litter.manifest import Manifest
from litter.package import Package
from squall.backend import SqlBackend, SqlResult

from red_dragon_forge.db2_connection import Db2Connection


class _RecordingBackend(SqlBackend):
    def __init__(self) -> None:
        self.calls: tuple[str, ...] = ()

    def execute(self, sql: str, params: Sequence[str]) -> SqlResult:
        raise AssertionError(f"no SQL runs here: {sql}")

    def open_cursor(self, name: str, sql: str, params: Sequence[str]) -> int:
        raise AssertionError(f"no cursor opens here: {name}")

    def fetch(self, name: str) -> SqlResult:
        raise AssertionError(f"no cursor fetches here: {name}")

    def close(self, name: str) -> None:
        raise AssertionError(f"no cursor closes here: {name}")

    def commit(self) -> None:
        self.calls = (*self.calls, "commit")

    def rollback(self) -> None:
        self.calls = (*self.calls, "rollback")


@pytest.fixture(autouse=True)
def _restore_builtins_table() -> Iterator[None]:
    before = dict(Builtins.TABLE)
    yield
    Builtins.TABLE.clear()
    Builtins.TABLE.update(before)


def _empty(tmp_path: Path) -> Package:
    return Package(
        Manifest(programs=(), coprocessors=(), transactions=(), files=(), mapsets=()),
        link_units((), tmp_path),
        {},
    )


def test_the_backend_commits_at_syncpoint_and_rolls_back_on_abend(
    tmp_path: Path,
) -> None:
    backend = _RecordingBackend()
    assemble_region(
        _empty(tmp_path),
        SystemCatalog(tmp_path / "system"),
        on_abend=Db2Connection("CARDDEMO", backend).install(tolerant=False),
    )

    Builtins.TABLE[FuncName("__cics_syncpoint_hook")]([], VMState())
    Builtins.TABLE[FuncName("__cics_abend")]([], VMState())

    assert backend.calls == ("commit", "rollback")
