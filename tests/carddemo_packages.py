"""CardDemo's checked-in build.toml and env.toml pairs, copied into a test directory with their outputs redirected there."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from red_dragon_forge.build_command import run as forge_build

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _REPO_ROOT / "config" / "carddemo"
_SYSTEM = '"/tmp/carddemo-system"'


@dataclass(frozen=True)
class CardDemoRegion:
    build: str
    env: str
    out_dir: str
    port: int


ONLINE = CardDemoRegion("build.toml", "env.toml", "/tmp/carddemo-build", 3270)
DB2 = CardDemoRegion("build-db2.toml", "env-db2.toml", "/tmp/carddemo-db2-build", 3271)


def _local(name: str, root: Path, rewrites: Mapping[str, str]) -> Path:
    local = root / name
    local.write_text(
        reduce(
            lambda text, rewrite: text.replace(*rewrite),
            rewrites.items(),
            (_CONFIG / name).read_text(),
        )
    )
    return local


def built_package(root: Path, region: CardDemoRegion) -> Path:
    build = _local(
        region.build,
        root,
        {'"../../': f'"{_REPO_ROOT}/', f'"{region.out_dir}"': f'"{root / "out"}"'},
    )
    assert forge_build([str(build)], os.environ) == 0
    return next((root / "out").glob("*.zip"))


def local_env(
    region: CardDemoRegion, root: Path, package: Path, system: Path, port: int
) -> Path:
    return _local(
        region.env,
        root,
        {
            f'"{region.out_dir}/': f'"{package.parent}/',
            _SYSTEM: f'"{system}"',
            f"port = {region.port}": f"port = {port}",
        },
    )
