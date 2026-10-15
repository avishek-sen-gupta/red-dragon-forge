"""Test helpers: litter packages of fixture programs, built or opened; the empty package, and a packaged program as a step runs it."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.subprocess_runner import RealSubprocessRunner
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
    {},
    {},
)


def built(
    directory: Path,
    programs: Sequence[str],
    cbl_dir: Path = FIXTURE_CBL,
    copybook_dirs: Sequence[Path] = (),
) -> Path:
    return build(
        name="fixture",
        programs=programs,
        sources={name: cbl_dir / f"{name}.cbl" for name in programs},
        parser=ProLeapCobolParser(
            runner=RealSubprocessRunner(),
            bridge_jar=os.environ["PROLEAP_BRIDGE_JAR"],
            copybook_dirs=list(copybook_dirs),
        ),
        specs=(),
        search_dirs=(cbl_dir, LE_STUBS),
        work_dir=directory / "work",
        out_dir=directory / "out",
        transactions=(),
        files=(),
        mapsets={},
        tolerant=False,
    )


def package(
    directory: Path,
    programs: Sequence[str],
    cbl_dir: Path = FIXTURE_CBL,
    copybook_dirs: Sequence[Path] = (),
) -> Package:
    return open_package(built(directory, programs, cbl_dir, copybook_dirs))


def compiled(packaged: Package, name: str) -> CompiledProgram:
    linked = packaged.programs[name]
    return CompiledProgram(linked, program_files_of(linked))
