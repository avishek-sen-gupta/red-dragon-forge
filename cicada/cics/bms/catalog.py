"""Every BMS map a region can send, parsed once from its mapset sources."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bms_copybook_gen.models import BmsMap, BmsMapSet
from bms_copybook_gen.parser import RawInvocation, parse_mapsets
from cics.bms.generate import DEFAULT_MACRO_DIR


class MapNotFound(LookupError):
    pass


@dataclass(frozen=True)
class MapCatalog:
    maps: Mapping[tuple[str, str], BmsMap]

    def lookup(self, mapset: str, map_name: str) -> BmsMap:
        """A SEND MAP that omits MAPSET resolves only when the map name is unique."""
        name = map_name.strip()
        return self._in(mapset.strip(), name) if mapset.strip() else self._unique(name)

    def _in(self, mapset: str, name: str) -> BmsMap:
        if (mapset, name) not in self.maps:
            raise MapNotFound(f"no BMS map {name!r} in mapset {mapset!r}")
        return self.maps[(mapset, name)]

    def _unique(self, name: str) -> BmsMap:
        matches = tuple(m for (_, label), m in self.maps.items() if label == name)
        if len(matches) != 1:
            raise MapNotFound(
                f"{len(matches)} BMS maps are named {name!r}; name the MAPSET"
            )
        return matches[0]


def catalog_from_mapsets(mapsets: Sequence[BmsMapSet]) -> MapCatalog:
    return MapCatalog(maps={(s.label, m.label): m for s in mapsets for m in s.maps})


def _invocations(
    bms_file: Path, hlasm_export_bin: str, syslib_dirs: Sequence[Path]
) -> Sequence[RawInvocation]:
    syslib = tuple(arg for d in syslib_dirs for arg in ("--syslib", str(d)))
    export = subprocess.run(
        [hlasm_export_bin, str(bms_file), *syslib], capture_output=True, check=True
    )
    return json.loads(export.stdout).get("macro_invocations", [])


def load_catalog(
    bms_dir: Path,
    hlasm_export_bin: str,
    syslib_dirs: Sequence[Path] = (DEFAULT_MACRO_DIR,),
) -> MapCatalog:
    return catalog_from_mapsets(
        tuple(
            mapset
            for bms_file in sorted(bms_dir.glob("*.bms"))
            for mapset in parse_mapsets(
                _invocations(bms_file, hlasm_export_bin, syslib_dirs)
            )
        )
    )
