"""Plain mode supplies each [plain.files] entry to HLASM as a DD: a copy reads and writes them and labels its new output; an unbound DD fails the OPEN with R15 8."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from catnip.dataset import Dataset
from catnip.labels import DatasetLabel, LabelPending, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog

from red_dragon_forge.build_command import run as forge_build

_FIXTURES = Path(__file__).parent / "fixtures" / "hlasm_dd"
_RUN = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "raise SystemExit(run(sys.argv[1:], os.environ))\n"
)
_FIXED = b"".join(
    text.ljust(80).encode("cp037")
    for text in ("FIRST RECORD", "SECOND RECORD", "THIRD RECORD")
)
_VARIABLE = b"".join(
    (len(text) + 4).to_bytes(2, "big") + bytes(2) + text.encode("cp037")
    for text in ("AB", "HELLO, WORLD", "Z" * 100)
)


def _forge_run(
    tmp_path: Path, entry: str, cobol: tuple[str, ...], files: Mapping[str, str]
) -> tuple[int, list[str], str]:
    quoted = lambda names: "[" + ", ".join(f'"{n}"' for n in names) + "]"
    build = tmp_path / "build.toml"
    build.write_text(
        f'[cobol]\nsource_dirs = ["{_FIXTURES}"]\nprograms = {quoted(cobol)}\n'
        f'[hlasm]\nsource_dirs = ["{_FIXTURES}"]\nprograms = ["DDCOPY"]\n'
        f'[build]\nname = "ddcopy"\nlink = {quoted((*cobol, "DDCOPY"))}\n'
        'out_dir = "out"\n'
    )
    assert forge_build([str(build)], os.environ) == 0
    env = tmp_path / "env.toml"
    bound = "".join(f'{dd} = "{dsn}"\n' for dd, dsn in files.items())
    env.write_text(
        f'package = "{tmp_path / "out" / "ddcopy.zip"}"\n'
        f'[paths]\nsystem = "{tmp_path / "system"}"\n'
        f'[plain]\nprogram = "{entry}"\n[plain.files]\n{bound}'
    )
    ran = subprocess.run(
        [sys.executable, "-c", _RUN, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )
    return ran.returncode, ran.stdout.splitlines(), ran.stderr


def _catalogued(tmp_path: Path, dsn: str, label: DatasetLabel, data: bytes) -> None:
    SystemCatalog(tmp_path / "system").create(dsn, label).path.write_bytes(data)


def _dataset(tmp_path: Path, dsn: str) -> tuple[DatasetLabel, bytes]:
    match SystemCatalog(tmp_path / "system").lookup(dsn):
        case Dataset(label=label, path=path):
            return label, path.read_bytes()
        case NotCataloged():
            raise AssertionError(f"{dsn} is not cataloged")


def _copied(
    tmp_path: Path, label: SequentialLabel, data: bytes
) -> tuple[tuple[int, list[str], str], tuple[DatasetLabel, bytes]]:
    _catalogued(tmp_path, "APP.IN", label, data)
    _catalogued(tmp_path, "APP.OUT", LabelPending(), b"")
    ran = _forge_run(tmp_path, "DDCOPY", (), {"INDD": "APP.IN", "OUTDD": "APP.OUT"})
    return ran, _dataset(tmp_path, "APP.OUT")


def test_an_hlasm_copy_of_fixed_records_writes_and_labels_its_new_output(
    tmp_path: Path,
) -> None:
    assert _copied(tmp_path, SequentialLabel(RecordFormat.FB, 80), _FIXED) == (
        (0, ["RC 0"], ""),
        (SequentialLabel(RecordFormat.F, 80), _FIXED),
    )


def test_an_hlasm_copy_of_variable_records_keeps_each_rdw_and_labels_v(
    tmp_path: Path,
) -> None:
    assert _copied(tmp_path, SequentialLabel(RecordFormat.VB, 104), _VARIABLE) == (
        (0, ["RC 0"], ""),
        (SequentialLabel(RecordFormat.V, 104), _VARIABLE),
    )


def test_a_cobol_driver_and_its_hlasm_callee_each_reach_their_own_files(
    tmp_path: Path,
) -> None:
    _catalogued(tmp_path, "APP.IN", SequentialLabel(RecordFormat.FB, 80), _FIXED)
    _catalogued(tmp_path, "APP.OUT", LabelPending(), b"")
    _catalogued(tmp_path, "APP.DRIVER", LabelPending(), b"")

    ran = _forge_run(
        tmp_path,
        "DDDRIVER",
        ("DDDRIVER",),
        {"DRVOUT": "APP.DRIVER", "INDD": "APP.IN", "OUTDD": "APP.OUT"},
    )

    assert (ran, _dataset(tmp_path, "APP.OUT"), _dataset(tmp_path, "APP.DRIVER")) == (
        (0, ["RC 0"], ""),
        (SequentialLabel(RecordFormat.F, 80), _FIXED),
        (
            SequentialLabel(RecordFormat.F, 80),
            "WRITTEN BY DDDRIVER".ljust(80).encode("cp037"),
        ),
    )


def _opened_input(
    tmp_path: Path, files: Mapping[str, str]
) -> tuple[int, list[str], str]:
    tmp_path.mkdir()
    _catalogued(tmp_path, "APP.OUT", LabelPending(), b"")
    _catalogued(tmp_path, "APP.NEW", LabelPending(), b"")
    return _forge_run(tmp_path, "DDCOPY", (), files)


def test_an_unbound_input_fails_the_open_and_a_pending_one_has_no_lrecl(
    tmp_path: Path,
) -> None:
    assert (
        _opened_input(tmp_path / "unbound", {"OUTDD": "APP.OUT"}),
        _opened_input(tmp_path / "pending", {"INDD": "APP.NEW", "OUTDD": "APP.OUT"}),
    ) == ((0, ["RC 8"], ""), (1, ["S013"], ""))
