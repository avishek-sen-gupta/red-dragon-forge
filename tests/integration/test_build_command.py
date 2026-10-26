"""forge-build turns a build.toml into a package whose manifest names the linked programs, coprocessors and CSD tables; COBOL and HLASM programs link into one image."""

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
from red_dragon_forge.run_command import run as forge_run

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


def _build_toml(
    tmp_path: Path, programs: str, build: str, cics: str, cobol: str = ""
) -> Path:
    path = tmp_path / "build.toml"
    path.write_text(
        "[cobol]\n"
        f'source_dirs = ["src", "{_APP / "cbl"}", "{_DB2_STUBS}"]\n'
        f'copybook_dirs = ["{_APP / "cpy"}"]\n'
        f"programs = {programs}\n"
        f"{cobol}"
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
        '["COSGN00C", "CBACT01C"]',
        'name = "carddemo"\n'
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
    ("cobol", "rc", "err"),
    [
        ('source_exts = [".cbl", ".CBL"]\n', 0, []),
        ("", 1, ["forge-build: program UPPER is in no [cobol] source_dirs as .cbl"]),
    ],
)
def test_a_source_is_found_only_by_a_listed_extension(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    cobol: str,
    rc: int,
    err: list[str],
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "UPPER.CBL").write_text(_UPPER)
    path = _build_toml(
        tmp_path, '["UPPER"]', 'name = "app"\nlink = ["UPPER"]\n', "", cobol
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
        '["FIRST", "SECOND"]',
        'name = "app"\nlink = ["FIRST", "SECOND"]\n',
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
        '["CBACT01C", "DSNTIAC"]',
        'name = "app"\n' 'link = ["CBACT01C"]\n' 'coprocessors = ["sql"]\n',
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
        '["CBACT01C"]',
        'name = "app"\nlink = ["CBACT01C"]\n',
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


_CALLER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC X(2) VALUE SPACES.
       PROCEDURE DIVISION.
           CALL 'ASMSUB' USING WS-X.
           DISPLAY WS-X.
           GOBACK.
"""
_ASMSUB = """\
ASMSUB   CSECT
         COPY  ASMEQU
         LR    12,15
         USING ASMSUB,12
         L     2,0(,1)
         MVC   0(2,2),=C'OK'
         LA    15,RCZERO
         BR    14
         LTORG
         END
"""
_ASMEQU = "RCZERO   EQU   0\n"


def _mixed_build_toml(tmp_path: Path, macros: dict[str, str]) -> Path:
    for directory, files in (
        ("src", {"CALLER.cbl": _CALLER}),
        ("asm", {"ASMSUB.asm": _ASMSUB}),
        ("mac", macros),
    ):
        (tmp_path / directory).mkdir()
        _ = [(tmp_path / directory / n).write_text(t) for n, t in files.items()]
    path = tmp_path / "build.toml"
    path.write_text(
        '[cobol]\nsource_dirs = ["src"]\nprograms = ["CALLER"]\n'
        '[hlasm]\nsource_dirs = ["asm"]\nmaclib_dirs = ["mac"]\n'
        'programs = ["ASMSUB"]\n'
        '[build]\nname = "app"\nlink = ["CALLER", "ASMSUB"]\nout_dir = "out"\n'
    )
    return path


def test_an_hlasm_program_builds_into_the_image(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _mixed_build_toml(tmp_path, {"ASMEQU.mac": _ASMEQU})

    built = run([str(path)], os.environ)
    package = tmp_path / "out" / "app.zip"
    programs = open_package(package).manifest.programs
    capsys.readouterr()
    env = tmp_path / "env.toml"
    env.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        '[plain]\nprogram = "CALLER"\n'
    )
    ran = forge_run([str(env)], os.environ)
    captured = capsys.readouterr()

    assert (built, programs, (ran, captured.out, captured.err)) == (
        0,
        ("CALLER", "ASMSUB"),
        (0, "OK\nRC 0\n", ""),
    )


def test_a_missing_macro_member_stops_the_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _mixed_build_toml(tmp_path, {})

    rc = run([str(path)], os.environ)
    err = capsys.readouterr().err

    assert (rc, [line for line in err.split("\n") if not line.startswith("\r")]) == (
        1,
        [
            "forge-build: E058 line 2: Copy member not found;"
            " E010 line 7: Unknown ordinary symbol: RCZERO",
            "",
        ],
    )


def test_an_hlasm_program_with_no_source_stops_the_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _mixed_build_toml(tmp_path, {"ASMEQU.mac": _ASMEQU})
    (tmp_path / "asm" / "ASMSUB.asm").rename(tmp_path / "asm" / "ASMSUB.s")

    rc = run([str(path)], os.environ)

    assert (rc, capsys.readouterr().err) == (
        1,
        "forge-build: program ASMSUB is in no [hlasm] source_dirs as .asm\n",
    )


def test_an_unfound_hlasm_bridge_stops_the_build(tmp_path: Path) -> None:
    path = _mixed_build_toml(tmp_path, {"ASMEQU.mac": _ASMEQU})
    absent = tmp_path / "absent-bridge"

    done = subprocess.run(
        [sys.executable, "-m", "red_dragon_forge.build_command", str(path)],
        env={**os.environ, "HLASM_AST_BRIDGE": str(absent)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert (
        done.returncode,
        done.stderr,
        (tmp_path / "out" / "app.zip").exists(),
    ) == (1, f"forge-build: hlasm_ast_bridge not found: {absent}\n", False)


def test_a_cobol_only_build_needs_no_hlasm_bridge(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "UPPER.cbl").write_text(_UPPER)
    path = _build_toml(tmp_path, '["UPPER"]', 'name = "app"\nlink = ["UPPER"]\n', "")

    done = subprocess.run(
        [sys.executable, "-m", "red_dragon_forge.build_command", str(path)],
        env={**os.environ, "HLASM_AST_BRIDGE": str(tmp_path / "absent-bridge")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert (
        done.returncode,
        done.stdout,
        open_package(tmp_path / "out" / "app.zip").manifest.programs,
    ) == (
        0,
        f"{tmp_path / 'out' / 'app.zip'}\n",
        ("UPPER",),
    )
