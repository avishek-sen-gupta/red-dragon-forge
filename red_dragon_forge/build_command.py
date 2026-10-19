"""forge-build: turns a build.toml into a litter package of one linked image."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cics.bms.export import exported_mapsets, fresh_symbolic_copybooks
from cics.csd_parse import parse_csd, parse_csd_files
from cics.tn3270.region import CICS_COPYBOOKS
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.copybook_search import CopybookSearch
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.project.duplicate_program_in_image import DuplicateProgramInImage
from litter.build import build
from litter.cics_file import CicsFile
from litter.package_error import PackageError
from litter.transaction import Transaction

from red_dragon_forge.build_config import BuildConfig, load_build_config
from red_dragon_forge.config_error import ConfigError
from red_dragon_forge.coprocessors import COPROCESSORS, require_linked
from red_dragon_forge.missing_required_program import MissingRequiredProgram

logger = logging.getLogger(__name__)

_TOOLS = ("PROLEAP_BRIDGE_JAR", "HLASM_EXPORT")
_LINK = "[build] link"
_DEFAULT_SOURCE_EXTS = (".cbl",)


class _Unbuildable(Exception):
    pass


def _tools(environ: Mapping[str, str]) -> tuple[str, str]:
    unset = tuple(name for name in _TOOLS if not environ.get(name, ""))
    if unset:
        raise _Unbuildable(f"{unset[0]} is not set")
    return environ["PROLEAP_BRIDGE_JAR"], environ["HLASM_EXPORT"]


def _named(directory: Path, names: Sequence[str]) -> tuple[Path, ...]:
    present = (
        frozenset(p.name for p in directory.iterdir())
        if directory.is_dir()
        else frozenset()
    )
    return tuple(directory / name for name in names if name in present)


def _source(base: Path, config: BuildConfig, program: str) -> Path:
    exts = config.paths.source_exts or _DEFAULT_SOURCE_EXTS
    found = tuple(
        source
        for d in config.paths.source_dirs
        for source in _named(base / d, tuple(f"{program}{ext}" for ext in exts))
    )
    if not found:
        raise _Unbuildable(
            f"program {program} is in no [paths] source_dirs as {', '.join(exts)}"
        )
    return found[0]


def _transactions(base: Path, config: BuildConfig) -> tuple[Transaction, ...]:
    return tuple(
        Transaction(transid, program)
        for csd in config.cics.csd_files
        for transid, program in sorted(parse_csd(base / csd).items())
    )


def _files(base: Path, config: BuildConfig) -> tuple[CicsFile, ...]:
    return tuple(
        CicsFile(name, dsname)
        for csd in config.cics.csd_files
        for name, dsname in parse_csd_files(base / csd).items()
    )


def _copybook_dirs(base: Path, config: BuildConfig, sym: Path) -> tuple[Path, ...]:
    own = tuple(base / d for d in config.paths.copybook_dirs)
    return (sym, *own, CICS_COPYBOOKS) if config.uses_cics() else own


def _built(path: Path, environ: Mapping[str, str]) -> Path:
    bridge_jar, hlasm_export = _tools(environ)
    config = load_build_config(path)
    require_linked(config.build.coprocessors, config.build.link, _LINK)
    base = path.parent
    out_dir = base / config.build.out_dir
    work = out_dir / "work"
    cics = config.uses_cics()
    if cics:
        fresh_symbolic_copybooks(
            tuple(base / d for d in config.cics.bms_dirs), hlasm_export, work / "sym"
        )
    copybook_dirs = _copybook_dirs(base, config, work / "sym")
    return build(
        name=config.build.name,
        programs=config.build.programs,
        link=config.build.link,
        sources={p: _source(base, config, p) for p in config.build.programs},
        parser=ProLeapCobolParser(
            RealSubprocessRunner(),
            bridge_jar,
            copybooks=CopybookSearch(
                dirs=tuple(copybook_dirs), exts=tuple(config.paths.copybook_exts)
            ),
        ),
        specs=tuple(COPROCESSORS[c].spec() for c in config.build.coprocessors),
        copybook_dirs=copybook_dirs,
        work_dir=work / "units",
        out_dir=out_dir,
        transactions=_transactions(base, config) if cics else (),
        files=_files(base, config) if cics else (),
        mapsets=(
            exported_mapsets(
                tuple(base / d for d in config.cics.bms_dirs),
                hlasm_export,
                work / "maps",
            )
            if cics
            else {}
        ),
        tolerant=config.build.tolerant,
    )


def run(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    try:
        package = _built(Path(argv[0]), environ)
    except (
        _Unbuildable,
        ConfigError,
        DuplicateProgramInImage,
        MissingRequiredProgram,
        PackageError,
    ) as unbuildable:
        sys.stderr.write(f"forge-build: {unbuildable}\n")
        return 1
    sys.stdout.write(f"{package}\n")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    return run(sys.argv[1:], os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
