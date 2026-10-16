"""A [cics] run with [sql]: the Db2 connection is the current one, its backend commits at SYNCPOINT, its rollback is the region's on_abend, and __exec_sql is in the region's table."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from catnip.system_catalog import SystemCatalog
from cics.tn3270.region import assemble_region
from interpreter.func_name import FuncName
from interpreter.project.cobol_compile import link_units
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
    coprocessing = Db2Connection("CARDDEMO", backend).install(tolerant=False)
    served = assemble_region(
        _empty(tmp_path),
        SystemCatalog(tmp_path / "system"),
        on_abend=coprocessing.on_abend,
        hooks=coprocessing.hooks,
        other_builtins=coprocessing.builtins,
    )

    served.builtins[FuncName("__cics_syncpoint_hook")]([], VMState())
    served.builtins[FuncName("__cics_abend")]([], VMState())

    assert backend.calls == ("commit", "rollback")
    exec_sql = FuncName("__exec_sql")
    assert served.builtins[exec_sql] is coprocessing.builtins[exec_sql]
