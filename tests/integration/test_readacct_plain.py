"""CardDemo's READACCT step in plain mode: CBACT01C calls the assembler COBDATFT, and its three outputs carry the dates COBDATFT reformats."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from catnip.dataset import Dataset
from catnip.declaration import load_declaration
from catnip.install import install
from catnip.labels import DatasetLabel, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from interpreter.cobol.cee3abd_abend import LE_STUBS

from red_dragon_forge.build_command import run as forge_build

_FORGE_ROOT = Path(__file__).parents[2]
_DECLARATION = _FORGE_ROOT / "config" / "carddemo" / "data.toml"
_FIXTURES = Path(__file__).parent / "fixtures" / "readacct"
_PSCOMP = "AWS.M2.CARDDEMO.ACCTDATA.PSCOMP"
_ARRYPS = "AWS.M2.CARDDEMO.ACCTDATA.ARRYPS"
_VBPS = "AWS.M2.CARDDEMO.ACCTDATA.VBPS"
_REISSUE_DATE = slice(68, 76)
_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)


def _build_toml(tmp_path: Path, carddemo_home: Path) -> Path:
    path = tmp_path / "build.toml"
    path.write_text(
        "[cobol]\n"
        f'source_dirs = ["{carddemo_home / "cbl"}", "{LE_STUBS}"]\n'
        'source_exts = [".cbl", ".CBL"]\n'
        f'copybook_dirs = ["{carddemo_home / "cpy"}"]\n'
        'programs = ["CBACT01C", "CEE3ABD"]\n'
        "[hlasm]\n"
        f'source_dirs = ["{carddemo_home / "asm"}"]\n'
        f'maclib_dirs = ["{carddemo_home / "maclib"}"]\n'
        'programs = ["COBDATFT"]\n'
        "[build]\n"
        'name = "readacct"\n'
        'link = ["CBACT01C", "COBDATFT", "CEE3ABD"]\n'
        'out_dir = "out"\n'
    )
    return path


def _env_toml(tmp_path: Path, package: Path) -> Path:
    path = tmp_path / "env.toml"
    path.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        '[plain]\nprogram = "CBACT01C"\n'
        "[plain.files]\n"
        'ACCTFILE = "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"\n'
        f'OUTFILE = "{_PSCOMP}"\n'
        f'ARRYFILE = "{_ARRYPS}"\n'
        f'VBRCFILE = "{_VBPS}"\n'
    )
    return path


def _dataset(system: SystemCatalog, dsn: str) -> tuple[DatasetLabel, bytes]:
    match system.lookup(dsn):
        case Dataset(label=label, path=path):
            return label, path.read_bytes()
        case NotCataloged():
            raise AssertionError(f"{dsn} is not cataloged")


def _fixed(data: bytes, lrecl: int) -> list[bytes]:
    return [data[at : at + lrecl] for at in range(0, len(data), lrecl)]


def _variable(data: bytes) -> list[bytes]:
    if not data:
        return []
    length = int.from_bytes(data[:2], "big")
    return [data[:length], *_variable(data[length:])]


def _shown(records: Sequence[bytes]) -> list[str]:
    return [ascii(record.decode("cp037")) for record in records]


def _expected(name: str) -> list[str]:
    return (_FIXTURES / name).read_text().splitlines()


def test_readacct_formats_dates_through_cobdatft(
    tmp_path: Path, carddemo_home: Path
) -> None:
    install(load_declaration(_DECLARATION), SystemCatalog(tmp_path / "system"))
    assert forge_build([str(_build_toml(tmp_path, carddemo_home))], os.environ) == 0
    env = _env_toml(tmp_path, tmp_path / "out" / "readacct.zip")

    ran = subprocess.run(
        [sys.executable, "-c", _RUN, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )
    system = SystemCatalog(tmp_path / "system")
    pscomp_label, pscomp = _dataset(system, _PSCOMP)
    arryps_label, arryps = _dataset(system, _ARRYPS)
    vbps_label, vbps = _dataset(system, _VBPS)
    *displayed, report = ran.stdout.splitlines()

    assert (
        ran.returncode,
        [ascii(line) for line in displayed],
        report,
        ran.stderr,
    ) == (
        0,
        _expected("stdout.txt"),
        "RC 0",
        "",
    )
    assert (pscomp_label, arryps_label, vbps_label) == (
        SequentialLabel(RecordFormat.FB, 107),
        SequentialLabel(RecordFormat.FB, 110),
        SequentialLabel(RecordFormat.VB, 84),
    )
    assert (
        _shown(_fixed(pscomp, 107)),
        _shown(_fixed(arryps, 110)),
        _shown(_variable(vbps)),
    ) == (_expected("pscomp.txt"), _expected("arryps.txt"), _expected("vbps.txt"))
    assert [record[_REISSUE_DATE] for record in _fixed(pscomp, 107)[:2]] == [
        "20250520".encode("cp037"),
        "20240811".encode("cp037"),
    ]
