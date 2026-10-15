"""Opens a package: the typed manifest, each linked program read by LinkedCodec, and each mapset's JSON text."""

import logging
import tempfile
import zipfile
from pathlib import Path

from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from interpreter.project.types import LinkedProgram
from interpreter.project.unit_format_error import UnitFormatError
from litter.entries import MANIFEST_ENTRY, mapset_entry, program_entry
from litter.manifest import Manifest
from litter.package import Package
from litter.package_error import PackageError
from litter.validation_message import validation_message
from pydantic import ValidationError

logger = logging.getLogger(__name__)
_EXTRACTED = "program.linked.json"


def open_package(path: Path) -> Package:
    with (
        zipfile.ZipFile(path) as archive,
        tempfile.TemporaryDirectory() as extracted,
    ):
        manifest = _manifest(path, archive)
        programs = {
            program: _program(path, archive, Path(extracted), program)
            for program in manifest.programs
        }
        mapsets = {
            mapset: _entry(path, archive, mapset_entry(mapset)).decode("utf-8")
            for mapset in manifest.mapsets
        }
    return Package(manifest, programs, mapsets)


def _entry(path: Path, archive: zipfile.ZipFile, entry: str) -> bytes:
    if entry not in archive.namelist():
        raise PackageError(f"{path}: {entry}: missing")
    logger.info("reading %s from %s", entry, path)
    return archive.read(entry)


def _manifest(path: Path, archive: zipfile.ZipFile) -> Manifest:
    try:
        return Manifest.model_validate_json(_entry(path, archive, MANIFEST_ENTRY))
    except ValidationError as exc:
        raise PackageError(
            f"{path}: {MANIFEST_ENTRY}: {validation_message(exc)}"
        ) from exc


def _program(
    path: Path, archive: zipfile.ZipFile, extracted: Path, program: str
) -> LinkedProgram:
    entry = program_entry(program)
    linked = extracted / _EXTRACTED
    linked.write_bytes(_entry(path, archive, entry))
    try:
        return LinkedCodec(IrCodec()).read(linked)
    except UnitFormatError as exc:
        raise PackageError(
            f"{path}: {entry}: {str(exc).removeprefix(f'{linked}: ')}"
        ) from exc
