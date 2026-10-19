"""Test helpers: litter packages of fixture programs, built or opened; the empty package, and a packaged program as a step enters it."""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.project.cobol_compile import link_units
from interpreter.project.program_entry import ProgramEntry
from jackal.cobol_step import CompiledProgram
from jackal.file_definitions import program_files_of
from jackal.le_abend import LE_STUBS
from litter.build import build
from litter.manifest import Manifest
from litter.open import open_package
from litter.package import Package

FIXTURE_CBL = Path(__file__).parent / "integration" / "fixtures" / "cbl"


EMPTY = Package(
    Manifest(programs=(), coprocessors=(), transactions=(), files=(), mapsets=()),
    link_units((), Path(tempfile.mkdtemp(prefix="jackal-empty-image-"))),
    {},
)


def _source(name: str, cbl_dir: Path) -> Path:
    return next(
        found
        for found in (cbl_dir / f"{name}.cbl", LE_STUBS / f"{name}.cbl")
        if found.is_file()
    )


def built(
    directory: Path,
    bridge_jar: str,
    programs: Sequence[str],
    cbl_dir: Path = FIXTURE_CBL,
    copybook_dirs: Sequence[Path] = (),
) -> Path:
    return build(
        name="fixture",
        programs=programs,
        link=programs,
        sources={name: _source(name, cbl_dir) for name in programs},
        parser=ProLeapCobolParser(
            runner=RealSubprocessRunner(),
            bridge_jar=bridge_jar,
            copybooks=CopybookSearch(dirs=tuple(copybook_dirs)),
        ),
        specs=(),
        copybook_dirs=copybook_dirs,
        work_dir=directory / "work",
        out_dir=directory / "out",
        transactions=(),
        files=(),
        mapsets={},
        tolerant=False,
    )


def package(
    directory: Path,
    bridge_jar: str,
    programs: Sequence[str],
    cbl_dir: Path = FIXTURE_CBL,
    copybook_dirs: Sequence[Path] = (),
) -> Package:
    return open_package(built(directory, bridge_jar, programs, cbl_dir, copybook_dirs))


def compiled(packaged: Package, name: str) -> CompiledProgram:
    return CompiledProgram(
        packaged.image, ProgramEntry(name), program_files_of(packaged.image)
    )
