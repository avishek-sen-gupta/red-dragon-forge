"""Compiles each program once and writes the linked programs, the manifest and the mapsets into one zip."""

import logging
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from interpreter.project.coprocessor_compile import CoprocessorSpec, compile_program
from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from interpreter.project.types import LinkedProgram
from litter.cics_file import CicsFile
from litter.entries import MANIFEST_ENTRY, mapset_entry, program_entry
from litter.manifest import Manifest
from litter.package_error import PackageError
from litter.transaction import Transaction
from litter.validation_message import validation_message
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def build(
    *,
    name: str,
    programs: Sequence[str],
    sources: Mapping[str, Path],
    parser: ProLeapCobolParser,
    specs: Sequence[CoprocessorSpec],
    search_dirs: Sequence[Path],
    work_dir: Path,
    out_dir: Path,
    transactions: Sequence[Transaction],
    files: Sequence[CicsFile],
    mapsets: Mapping[str, Path],
    tolerant: bool,
) -> Path:
    package = out_dir / f"{name}.zip"
    manifest = _manifest(
        package,
        programs=tuple(programs),
        coprocessors=tuple(spec.make_strategy().name for spec in specs),
        transactions=tuple(transactions),
        files=tuple(files),
        mapsets=tuple(mapsets),
    )
    linked = {
        program: _compiled(
            sources[program].read_bytes(),
            parser,
            specs,
            search_dirs,
            work_dir / program,
            tolerant,
        )
        for program in programs
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _publish(package, manifest, linked, mapsets)
    return package


def _publish(
    package: Path,
    manifest: Manifest,
    linked: Mapping[str, LinkedProgram],
    mapsets: Mapping[str, Path],
) -> None:
    part = package.with_name(f"{package.name}.part")
    try:
        _write(part, manifest, linked, mapsets)
        part.replace(package)
    finally:
        part.unlink(missing_ok=True)


def _manifest(
    package: Path,
    *,
    programs: tuple[str, ...],
    coprocessors: tuple[str, ...],
    transactions: tuple[Transaction, ...],
    files: tuple[CicsFile, ...],
    mapsets: tuple[str, ...],
) -> Manifest:
    try:
        return Manifest(
            programs=programs,
            coprocessors=coprocessors,
            transactions=transactions,
            files=files,
            mapsets=mapsets,
        )
    except ValidationError as exc:
        raise PackageError(
            f"{package}: {MANIFEST_ENTRY}: {validation_message(exc)}"
        ) from exc


def _compiled(
    source: bytes,
    parser: ProLeapCobolParser,
    specs: Sequence[CoprocessorSpec],
    search_dirs: Sequence[Path],
    work_dir: Path,
    tolerant: bool,
) -> LinkedProgram:
    linked = compile_program(
        source,
        parser,
        specs,
        source_search_dirs=search_dirs,
        tolerant=tolerant,
        work_dir=work_dir,
    )
    logger.info("compiled %s", work_dir.name)
    return linked


def _write(
    package: Path,
    manifest: Manifest,
    linked: Mapping[str, LinkedProgram],
    mapsets: Mapping[str, Path],
) -> None:
    with (
        tempfile.TemporaryDirectory() as staging,
        zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        archive.writestr(MANIFEST_ENTRY, manifest.model_dump_json(indent=2))
        for program, compiled in linked.items():
            written = Path(staging) / f"{program}.linked.json"
            LinkedCodec(IrCodec()).write(compiled, written)
            archive.write(written, program_entry(program))
            logger.info("wrote %s into %s", program_entry(program), package)
        for mapset, exported in mapsets.items():
            archive.write(exported, mapset_entry(mapset))
            logger.info("wrote %s into %s", mapset_entry(mapset), package)
