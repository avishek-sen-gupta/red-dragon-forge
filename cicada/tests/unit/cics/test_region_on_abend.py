"""Pins assemble_region's on_abend seam: the caller's callable reaches the CICS runtime's abend builtins, and a CICS-only region's default is a genuine no-op."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path

import pytest

import cics.tn3270.region as region_mod
from catnip.system_catalog import SystemCatalog
from interpreter.func_name import FuncName
from interpreter.project.cobol_compile import link_units
from interpreter.vm.vm_types import BuiltinResult, VMState
from litter.manifest import Manifest
from litter.package import Package


def _fire_installed_abend(served: region_mod.ServedRegion) -> BuiltinResult:
    return served.builtins[FuncName("__cics_abend")]([], VMState())


def _empty(tmp_path: Path) -> Package:
    return Package(
        Manifest(programs=(), coprocessors=(), transactions=(), files=(), mapsets=()),
        link_units((), tmp_path),
        {},
    )


def _assembled(tmp_path: Path, on_abend: Callable[[], None]) -> region_mod.ServedRegion:
    return region_mod.assemble_region(
        _empty(tmp_path), SystemCatalog(tmp_path / "system"), on_abend=on_abend
    )


def test_assemble_region_forwards_on_abend_to_install_cics_runtime(
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    served = _assembled(tmp_path, on_abend=lambda: calls.append(1))
    _fire_installed_abend(served)

    assert calls == [1]


def test_assemble_region_default_on_abend_is_the_module_noop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    served = region_mod.assemble_region(
        _empty(tmp_path), SystemCatalog(tmp_path / "system")
    )

    result = _fire_installed_abend(served)

    assert (
        inspect.signature(region_mod.assemble_region).parameters["on_abend"].default
        is region_mod._region_noop
    )
    assert region_mod._region_noop() is None
    assert caplog.records == []
    assert result == BuiltinResult(value=None)
