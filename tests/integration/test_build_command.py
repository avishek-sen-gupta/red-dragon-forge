"""forge-build turns a build.toml into a package whose manifest names the linked programs, coprocessors and CSD tables."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cics.bms.catalog import mapset_json
from cics.bms.generate import generate_symbolic_copybooks
from litter.cics_file import CicsFile
from litter.manifest import Manifest
from litter.open import open_package
from litter.transaction import Transaction

from red_dragon_forge.build_command import run

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP = _REPO_ROOT / "vendor" / "carddemo" / "app"
_DB2_STUBS = _REPO_ROOT / "squall" / "squall" / "stubs"

_TRANSACTIONS = tuple(
    Transaction(transid, program)
    for transid, program in (
        ("CA00", "COADM01C"),
        ("CAUP", "COACTUPC"),
        ("CAVW", "COACTVWC"),
        ("CB00", "COBIL00C"),
        ("CC00", "COSGN00C"),
        ("CCDL", "COCRDSLC"),
        ("CCLI", "COCRDLIC"),
        ("CCUP", "COCRDUPC"),
        ("CDV1", "COCRDSEC"),
        ("CM00", "COMEN01C"),
        ("CR00", "CORPT00C"),
        ("CT00", "COTRN00C"),
        ("CT01", "COTRN01C"),
        ("CT02", "COTRN02C"),
        ("CU00", "COUSR00C"),
        ("CU01", "COUSR01C"),
        ("CU02", "COUSR02C"),
        ("CU03", "COUSR03C"),
    )
)
_FILES = tuple(
    CicsFile(name, dsname)
    for name, dsname in (
        ("ACCTDAT", "AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS"),
        ("CARDAIX", "AWS.M2.CARDDEMO.CARDDATA.VSAM.AIX.PATH"),
        ("CARDDAT", "AWS.M2.CARDDEMO.CARDDATA.VSAM.KSDS"),
        ("CCXREF", "AWS.M2.CARDDEMO.CARDXREF.VSAM.KSDS"),
        ("CUSTDAT", "AWS.M2.CARDDEMO.CUSTDATA.VSAM.KSDS"),
        ("CXACAIX", "AWS.M2.CARDDEMO.CARDXREF.VSAM.AIX.PATH"),
        ("TRANSACT", "AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS"),
        ("USRSEC", "AWS.M2.CARDDEMO.USRSEC.VSAM.KSDS"),
    )
)


def _build_toml(tmp_path: Path, build: str, cics: str, paths: str = "") -> Path:
    path = tmp_path / "build.toml"
    path.write_text(
        "[paths]\n"
        f'source_dirs = ["src", "{_APP / "cbl"}", "{_DB2_STUBS}"]\n'
        f'copybook_dirs = ["{_APP / "cpy"}"]\n'
        f"{paths}"
        f"[build]\n{build}"
        'out_dir = "out"\n'
        f"{cics}"
    )
    return path


def _sign_on_bms(tmp_path: Path) -> Path:
    bms = tmp_path / "bms"
    bms.mkdir()
    shutil.copy(_APP / "bms" / "COSGN00.bms", bms / "COSGN00.bms")
    return bms


def _shadowing_bms(tmp_path: Path) -> Path:
    bms = tmp_path / "later-bms"
    bms.mkdir()
    (bms / "COSGN00.bms").write_text(
        (_APP / "bms" / "COSGN00.bms")
        .read_text()
        .replace("INITIAL='Tran :'", "INITIAL='TRAN?:'")
    )
    return bms


def test_builds_a_cics_and_a_batch_program(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sign_on = _sign_on_bms(tmp_path)
    path = _build_toml(
        tmp_path,
        'name = "carddemo"\n'
        'programs = ["COSGN00C", "CBACT01C"]\n'
        'link = ["CBACT01C", "COSGN00C"]\n'
        'coprocessors = ["cics"]\n',
        "[cics]\n"
        f'bms_dirs = ["{sign_on}", "{_shadowing_bms(tmp_path)}"]\n'
        f'csd_files = ["{_APP / "csd" / "CARDDEMO.CSD"}"]\n',
    )
    stale = tmp_path / "out" / "work" / "sym" / "COSGN00.cpy"
    stale.parent.mkdir(parents=True)
    stale.write_text("      * A STALE SYMBOLIC MAP FROM AN EARLIER BUILD\n")
    fresh = tmp_path / "fresh"
    generate_symbolic_copybooks(
        bms_dir=sign_on, out_dir=fresh, hlasm_export_bin=os.environ["HLASM_EXPORT"]
    )

    rc = run([str(path)], os.environ)
    package = tmp_path / "out" / "carddemo.zip"
    opened = open_package(package)

    assert (
        rc,
        capsys.readouterr().out,
        opened.manifest,
        sorted(opened.image.programs),
        opened.mapsets["COSGN00"],
        stale.read_text(),
    ) == (
        0,
        f"{package}\n",
        Manifest(
            programs=("CBACT01C", "COSGN00C"),
            coprocessors=("cics",),
            transactions=_TRANSACTIONS,
            files=_FILES,
            mapsets=("COSGN00",),
        ),
        ["CBACT01C", "COSGN00C"],
        mapset_json(sign_on / "COSGN00.bms", os.environ["HLASM_EXPORT"]),
        (fresh / "COSGN00.cpy").read_text(),
    )


_UPPER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UPPER.
       PROCEDURE DIVISION.
           GOBACK.
"""


@pytest.mark.parametrize(
    ("paths", "rc", "err"),
    [
        ('source_exts = [".cbl", ".CBL"]\n', 0, []),
        ("", 1, ["forge-build: program UPPER is in no [paths] source_dirs as .cbl"]),
    ],
)
def test_a_source_is_found_only_by_a_listed_extension(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    paths: str,
    rc: int,
    err: list[str],
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "UPPER.CBL").write_text(_UPPER)
    path = _build_toml(
        tmp_path, 'name = "app"\nprograms = ["UPPER"]\nlink = ["UPPER"]\n', "", paths
    )

    built = run([str(path)], os.environ)

    stopped = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("forge-build:")
    ]

    assert (built, stopped) == (rc, err)


def test_two_members_with_one_program_id_stop_the_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "FIRST.cbl").write_text(_UPPER)
    (tmp_path / "src" / "SECOND.cbl").write_text(_UPPER)
    path = _build_toml(
        tmp_path,
        'name = "app"\nprograms = ["FIRST", "SECOND"]\nlink = ["FIRST", "SECOND"]\n',
        "",
    )

    rc = run([str(path)], os.environ)

    assert (
        rc,
        [
            line.split(" twice:")[0]
            for line in capsys.readouterr().err.splitlines()
            if line.startswith("forge-build:")
        ],
        (tmp_path / "out" / "app.zip").exists(),
    ) == (1, ["forge-build: program UPPER is in the image"], False)


def test_a_build_with_sql_that_does_not_link_dsntiac_stops_before_linking(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _build_toml(
        tmp_path,
        'name = "app"\n'
        'programs = ["CBACT01C", "DSNTIAC"]\n'
        'link = ["CBACT01C"]\n'
        'coprocessors = ["sql"]\n',
        "",
    )

    rc = run([str(path)], os.environ)

    assert (rc, capsys.readouterr().err, (tmp_path / "out").exists()) == (
        1,
        "forge-build: coprocessor sql requires DSNTIAC in [build] link\n",
        False,
    )


def test_an_unset_tool_variable_stops_the_build(tmp_path: Path) -> None:
    path = _build_toml(
        tmp_path,
        'name = "app"\nprograms = ["CBACT01C"]\nlink = ["CBACT01C"]\n',
        "",
    )

    def stopped(unset: str) -> tuple[int, str]:
        env = {k: v for k, v in os.environ.items() if k != unset}
        done = subprocess.run(
            [sys.executable, "-m", "red_dragon_forge.build_command", str(path)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done.returncode, done.stderr

    assert (stopped("HLASM_EXPORT"), stopped("PROLEAP_BRIDGE_JAR")) == (
        (1, "forge-build: HLASM_EXPORT is not set\n"),
        (1, "forge-build: PROLEAP_BRIDGE_JAR is not set\n"),
    )
