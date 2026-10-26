"""forge-run's [plain] runs one program on the package image and reports its return code, abend or exhausted budget."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from catnip.dataset import Dataset
from catnip.labels import DatasetLabel, LabelPending, RecordFormat, SequentialLabel
from catnip.system_catalog import NotCataloged, SystemCatalog
from interpreter.cobol.cee3abd_abend import LE_STUBS

from red_dragon_forge.build_command import run as forge_build
from red_dragon_forge.run_command import run as forge_run

_FB80 = SequentialLabel(RecordFormat.FB, 80)
_TOLERANT = "[tolerant]\npermit_unresolved_call_targets = true\n"
_LOADED_PACKAGES = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "rc = run(sys.argv[1:], os.environ)\n"
    "print(*sorted({name.split('.')[0] for name in sys.modules}), sep='\\n')\n"
    "raise SystemExit(rc)\n"
)

_RCFOUR = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. RCFOUR.
       PROCEDURE DIVISION.
           MOVE 4 TO RETURN-CODE.
           GOBACK.
"""

_ABENDS = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ABENDS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ABCODE PIC S9(9) BINARY VALUE 1234.
       01 TIMING PIC S9(9) BINARY VALUE 0.
       PROCEDURE DIVISION.
           CALL 'CEE3ABD' USING ABCODE, TIMING.
           GOBACK.
"""

_LOSTCALL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOSTCALL.
       PROCEDURE DIVISION.
           CALL 'NOSUCHPG'.
           GOBACK.
"""

_LOSTABND = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LOSTABND.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 ABCODE PIC S9(9) BINARY VALUE 7.
       01 TIMING PIC S9(9) BINARY VALUE 0.
       PROCEDURE DIVISION.
           CALL 'NOSUCHPG'.
           CALL 'CEE3ABD' USING ABCODE, TIMING.
           GOBACK.
"""

_SPINNER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SPINNER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DONE PIC X VALUE 'N'.
       01 WS-N    PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
           PERFORM UNTIL WS-DONE = 'Y'
               ADD 1 TO WS-N
           END-PERFORM.
           GOBACK.
"""

_MARKER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MARKER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE   ASSIGN TO INFILE
                  ORGANIZATION IS SEQUENTIAL.
           SELECT MARK-FILE ASSIGN TO MARKDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE RECORDING MODE IS F.
       01  IN-REC   PIC X(80).
       FD  MARK-FILE RECORDING MODE IS F.
       01  MARK-REC PIC X(80).
       PROCEDURE DIVISION.
           OPEN OUTPUT MARK-FILE.
           MOVE 'RAN' TO MARK-REC.
           WRITE MARK-REC.
           CLOSE MARK-FILE.
           GOBACK.
"""

_WRITER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WRITER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO OUTDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE RECORDING MODE IS F.
       01  OUT-REC  PIC X(60).
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-FILE.
           MOVE 'FIRST WRITTEN' TO OUT-REC.
           WRITE OUT-REC.
           MOVE 'SECOND WRITTEN' TO OUT-REC.
           WRITE OUT-REC.
           CLOSE OUT-FILE.
           GOBACK.
"""

_READER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. READER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO INDD
                  ORGANIZATION IS SEQUENTIAL.
           SELECT CPY-FILE ASSIGN TO COPYDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE RECORDING MODE IS F.
       01  IN-REC   PIC X(60).
       FD  CPY-FILE RECORDING MODE IS F.
       01  CPY-REC  PIC X(80).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           OPEN OUTPUT CPY-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE IN-REC TO CPY-REC
                       WRITE CPY-REC
               END-READ
           END-PERFORM.
           CLOSE IN-FILE.
           CLOSE CPY-FILE.
           GOBACK.
"""


def _writer(program: str, ddname: str, length: int, then: str) -> str:
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. {program}.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCTFILE ASSIGN TO {ddname}
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  ACCTFILE RECORDING MODE IS F.
       01  ACCT-REC  PIC X({length}).
       PROCEDURE DIVISION.
           OPEN OUTPUT ACCTFILE.
           {then}
           MOVE 'WRITTEN BY {program}' TO ACCT-REC.
           WRITE ACCT-REC.
           CLOSE ACCTFILE.
           GOBACK.
"""


def _package(tmp_path: Path, programs: Mapping[str, str]) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    for name, text in programs.items():
        (src / f"{name}.cbl").write_text(text)
    names = ", ".join(f'"{name}"' for name in (*programs, "CEE3ABD"))
    toml = tmp_path / "build.toml"
    toml.write_text(
        f'[paths]\nsource_dirs = ["src", "{LE_STUBS}"]\n'
        f'[build]\nname = "app"\nout_dir = "out"\n'
        f"programs = [{names}]\nlink = [{names}]\n"
    )
    assert forge_build([str(toml)], os.environ) == 0
    return tmp_path / "out" / "app.zip"


def _ran(
    tmp_path: Path,
    package: Path,
    name: str,
    sections: str,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    capsys.readouterr()
    env = tmp_path / name
    env.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        f"{sections}"
    )
    rc = forge_run([str(env)], os.environ)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _catalogued(tmp_path: Path, dsn: str, label: DatasetLabel) -> None:
    SystemCatalog(tmp_path / "system").create(dsn, label)


def _dataset(tmp_path: Path, dsn: str) -> tuple[DatasetLabel, bytes]:
    match SystemCatalog(tmp_path / "system").lookup(dsn):
        case Dataset(label=label, path=path):
            return label, path.read_bytes()
        case NotCataloged():
            raise AssertionError(f"{dsn} is not cataloged")


def test_a_plain_program_ends_with_its_return_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"RCFOUR": _RCFOUR})

    assert _ran(
        tmp_path, package, "env.toml", '[plain]\nprogram = "RCFOUR"\n', capsys
    ) == (0, "RC 4\n", "")


def test_a_plain_program_that_calls_cee3abd_reports_the_user_abend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"ABENDS": _ABENDS})

    assert _ran(
        tmp_path, package, "env.toml", '[plain]\nprogram = "ABENDS"\n', capsys
    ) == (1, "U1234\n", "")


def test_an_abend_after_a_tolerated_call_wins_over_the_return_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"LOSTABND": _LOSTABND})

    assert _ran(
        tmp_path,
        package,
        "env.toml",
        _TOLERANT + '[plain]\nprogram = "LOSTABND"\n',
        capsys,
    ) == (1, "U0007\n", "")


def test_a_symbolic_return_code_reports_rc_0_with_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"LOSTCALL": _LOSTCALL})

    assert _ran(
        tmp_path,
        package,
        "env.toml",
        _TOLERANT + '[plain]\nprogram = "LOSTCALL"\n',
        capsys,
    ) == (
        0,
        "RC 0\n",
        "forge-run: warning: LOSTCALL's RETURN-CODE is unknown; reported as 0\n",
    )


def test_a_plain_program_that_runs_out_of_budget_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"SPINNER": _SPINNER})

    assert _ran(
        tmp_path,
        package,
        "env.toml",
        '[plain]\nprogram = "SPINNER"\nmax_steps = 50\n',
        capsys,
    ) == (1, "budget exhausted after 50 steps\n", "")


def test_a_plain_file_not_in_the_catalog_is_refused_before_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"MARKER": _MARKER})
    _catalogued(tmp_path, "APP.MARK", _FB80)

    ran = _ran(
        tmp_path,
        package,
        "env.toml",
        '[plain]\nprogram = "MARKER"\n'
        '[plain.files]\nMARKDD = "APP.MARK"\nINFILE = "APP.MISSING"\n',
        capsys,
    )

    assert (ran, _dataset(tmp_path, "APP.MARK")) == (
        (1, "", "forge-run: [plain.files] INFILE: APP.MISSING is not cataloged\n"),
        (_FB80, b""),
    )


def test_a_plain_output_dataset_is_labelled_on_first_open_and_read_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"WRITER": _WRITER, "READER": _READER})
    _catalogued(tmp_path, "APP.NEW", LabelPending())
    _catalogued(tmp_path, "APP.COPY", _FB80)

    wrote = _ran(
        tmp_path,
        package,
        "writer.toml",
        '[plain]\nprogram = "WRITER"\n[plain.files]\nOUTDD = "APP.NEW"\n',
        capsys,
    )
    labelled = _dataset(tmp_path, "APP.NEW")
    read = _ran(
        tmp_path,
        package,
        "reader.toml",
        '[plain]\nprogram = "READER"\n'
        '[plain.files]\nINDD = "APP.NEW"\nCOPYDD = "APP.COPY"\n',
        capsys,
    )

    written = "FIRST WRITTEN".ljust(60).encode("cp037") + "SECOND WRITTEN".ljust(
        60
    ).encode("cp037")
    copied = "FIRST WRITTEN".ljust(80).encode("cp037") + "SECOND WRITTEN".ljust(
        80
    ).encode("cp037")
    assert (wrote, labelled, read, _dataset(tmp_path, "APP.COPY")) == (
        (0, "RC 0\n", ""),
        (SequentialLabel(RecordFormat.F, 60), written),
        (0, "RC 0\n", ""),
        (_FB80, copied),
    )


def test_two_plain_programs_select_the_same_name_apart(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(
        tmp_path,
        {
            "ACCTA": _writer("ACCTA", "ADDA", 80, "CALL 'ACCTB'."),
            "ACCTB": _writer("ACCTB", "BDDB", 120, "CONTINUE."),
        },
    )
    _catalogued(tmp_path, "J.A", LabelPending())
    _catalogued(tmp_path, "J.B", LabelPending())

    ran = _ran(
        tmp_path,
        package,
        "env.toml",
        '[plain]\nprogram = "ACCTA"\n[plain.files]\nADDA = "J.A"\nBDDB = "J.B"\n',
        capsys,
    )

    assert (ran, _dataset(tmp_path, "J.A"), _dataset(tmp_path, "J.B")) == (
        (0, "RC 0\n", ""),
        (
            SequentialLabel(RecordFormat.F, 80),
            "WRITTEN BY ACCTA".ljust(80).encode("cp037"),
        ),
        (
            SequentialLabel(RecordFormat.F, 120),
            "WRITTEN BY ACCTB".ljust(120).encode("cp037"),
        ),
    )


def test_an_unresolved_call_stops_the_run_unless_tolerated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _package(tmp_path, {"LOSTCALL": _LOSTCALL})

    assert _ran(
        tmp_path, package, "env.toml", '[plain]\nprogram = "LOSTCALL"\n', capsys
    ) == (
        1,
        "",
        "forge-run: CALL to __entry_NOSUCHPG, but nothing in this run unit is"
        " registered under it\n",
    )


def test_a_plain_run_loads_neither_jackal_nor_cics(tmp_path: Path) -> None:
    package = _package(tmp_path, {"RCFOUR": _RCFOUR})
    env = tmp_path / "env.toml"
    env.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        '[plain]\nprogram = "RCFOUR"\n'
    )

    ran = subprocess.run(
        [sys.executable, "-c", _LOADED_PACKAGES, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )
    report, *loaded = ran.stdout.splitlines()

    assert (ran.returncode, report, {"jackal", "cics"} & set(loaded)) == (
        0,
        "RC 4",
        set(),
    )
