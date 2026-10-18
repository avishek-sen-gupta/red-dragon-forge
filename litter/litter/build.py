"""Lowers each program once, links the link list into one image, and writes it, the manifest and the mapsets into one zip."""

import logging
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from cobol_asg.cobol_parser import ProLeapCobolParser
from interpreter.project.cobol_compile import link_units
from interpreter.project.coprocessor_compile import CoprocessorSpec, lower_program
from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from interpreter.project.types import LinkedProgram
from litter.cics_file import CicsFile
from litter.entries import IMAGE_ENTRY, MANIFEST_ENTRY, mapset_entry
from litter.manifest import Manifest
from litter.package_error import PackageError
from litter.package_name import PackageName
from litter.transaction import Transaction
from litter.validation_message import validation_message
from pydantic import TypeAdapter, ValidationError

logger = logging.getLogger(__name__)
_STAGED_IMAGE = "image.linked.json"
_PACKAGE_NAME: TypeAdapter[str] = TypeAdapter(PackageName)


def build(
    *,
    name: str,
    programs: Sequence[str],
    link: Sequence[str],
    sources: Mapping[str, Path],
    parser: ProLeapCobolParser,
    specs: Sequence[CoprocessorSpec],
    copybook_dirs: Sequence[Path],
    work_dir: Path,
    out_dir: Path,
    transactions: Sequence[Transaction],
    files: Sequence[CicsFile],
    mapsets: Mapping[str, Path],
    tolerant: bool,
) -> Path:
    package = out_dir / f"{_package_name(out_dir, name)}.zip"
    coprocessors = tuple(spec.make_strategy().name for spec in specs)
    _manifest(
        package,
        programs=tuple(programs),
        coprocessors=coprocessors,
        transactions=tuple(transactions),
        files=tuple(files),
        mapsets=tuple(mapsets),
    )
    _refuse_unlowered(package, programs, link)
    _refuse_repeated(package, link)
    image = _image(
        programs, link, sources, parser, specs, copybook_dirs, work_dir, tolerant
    )
    manifest = _manifest(
        package,
        programs=tuple(image.programs),
        coprocessors=coprocessors,
        transactions=tuple(transactions),
        files=tuple(files),
        mapsets=tuple(mapsets),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    _publish(package, manifest, image, mapsets)
    return package


def _image(
    programs: Sequence[str],
    link: Sequence[str],
    sources: Mapping[str, Path],
    parser: ProLeapCobolParser,
    specs: Sequence[CoprocessorSpec],
    copybook_dirs: Sequence[Path],
    work_dir: Path,
    tolerant: bool,
) -> LinkedProgram:
    work_dir.mkdir(parents=True, exist_ok=True)
    units = {
        program: _lowered(
            program,
            sources[program].read_bytes(),
            parser,
            specs,
            copybook_dirs,
            work_dir,
            tolerant,
        )
        for program in programs
    }
    image = link_units([unit for program in link for unit in units[program]], work_dir)
    logger.info("linked %s into one image", ", ".join(link))
    return image


def _package_name(out_dir: Path, name: str) -> str:
    try:
        return _PACKAGE_NAME.validate_python(name)
    except ValidationError as exc:
        raise PackageError(
            f"{out_dir}: package name {name!r}:"
            f"{validation_message(exc).removeprefix(':')}"
        ) from exc


def _refuse_unlowered(
    package: Path, programs: Sequence[str], link: Sequence[str]
) -> None:
    unlowered = tuple(program for program in link if program not in programs)
    if unlowered:
        raise PackageError(
            f"{package}: link names {', '.join(unlowered)}, which programs does not list"
        )


def _refuse_repeated(package: Path, link: Sequence[str]) -> None:
    repeated = tuple(dict.fromkeys(p for p in link if link.count(p) > 1))
    if repeated:
        raise PackageError(
            f"{package}: link lists {', '.join(repeated)} more than once"
        )


def _publish(
    package: Path,
    manifest: Manifest,
    image: LinkedProgram,
    mapsets: Mapping[str, Path],
) -> None:
    part = package.with_name(f"{package.name}.part")
    try:
        _write(part, manifest, image, mapsets)
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


def _lowered(
    program: str,
    source: bytes,
    parser: ProLeapCobolParser,
    specs: Sequence[CoprocessorSpec],
    copybook_dirs: Sequence[Path],
    work_dir: Path,
    tolerant: bool,
) -> tuple[Path, ...]:
    units = lower_program(
        source,
        parser=parser,
        specs=specs,
        copybook_dirs=copybook_dirs,
        work_dir=work_dir,
        tolerant=tolerant,
    )
    logger.info("lowered %s to %s", program, ", ".join(unit.name for unit in units))
    return units


def _write(
    package: Path,
    manifest: Manifest,
    image: LinkedProgram,
    mapsets: Mapping[str, Path],
) -> None:
    with (
        tempfile.TemporaryDirectory() as staging,
        zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        archive.writestr(MANIFEST_ENTRY, manifest.model_dump_json(indent=2))
        written = Path(staging) / _STAGED_IMAGE
        LinkedCodec(IrCodec()).write(image, written)
        archive.write(written, IMAGE_ENTRY)
        logger.info("wrote %s into %s", IMAGE_ENTRY, package)
        for mapset, exported in mapsets.items():
            archive.write(exported, mapset_entry(mapset))
            logger.info("wrote %s into %s", mapset_entry(mapset), package)
