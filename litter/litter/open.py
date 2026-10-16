"""Opens a package: the typed manifest, the image read by LinkedCodec, and each mapset's JSON text."""

import logging
import tempfile
import zipfile
from pathlib import Path

from interpreter.project.ir_codec import IrCodec
from interpreter.project.linked_codec import LinkedCodec
from interpreter.project.types import LinkedProgram
from interpreter.project.unit_format_error import UnitFormatError
from litter.entries import IMAGE_ENTRY, MANIFEST_ENTRY, mapset_entry
from litter.manifest import Manifest
from litter.package import Package
from litter.package_error import PackageError
from litter.validation_message import validation_message
from pydantic import ValidationError

logger = logging.getLogger(__name__)
_EXTRACTED = "image.linked.json"


def open_package(path: Path) -> Package:
    with (
        zipfile.ZipFile(path) as archive,
        tempfile.TemporaryDirectory() as extracted,
    ):
        manifest = _manifest(path, archive)
        image = _image(path, archive, Path(extracted))
        mapsets = {
            mapset: _entry(path, archive, mapset_entry(mapset)).decode("utf-8")
            for mapset in manifest.mapsets
        }
    return Package(manifest, image, mapsets)


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


def _image(path: Path, archive: zipfile.ZipFile, extracted: Path) -> LinkedProgram:
    linked = extracted / _EXTRACTED
    linked.write_bytes(_entry(path, archive, IMAGE_ENTRY))
    try:
        return LinkedCodec(IrCodec()).read(linked)
    except UnitFormatError as exc:
        raise PackageError(
            f"{path}: {IMAGE_ENTRY}: {str(exc).removeprefix(f'{linked}: ')}"
        ) from exc
