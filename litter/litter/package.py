"""An opened package: its manifest, the one linked image, and each mapset's hlasm_export JSON text."""

from collections.abc import Mapping
from dataclasses import dataclass

from interpreter.project.types import LinkedProgram
from litter.manifest import Manifest


@dataclass(frozen=True)
class Package:
    manifest: Manifest
    image: LinkedProgram
    mapsets: Mapping[str, str]
