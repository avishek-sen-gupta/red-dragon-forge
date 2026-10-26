"""forge-run runs a package as env.toml says: one program, a JCL job, or a CICS region served over TN3270."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import ibm_db
import pytest
from catnip.dataset import Dataset
from catnip.labels import RecordFormat, SequentialLabel
from catnip.system_catalog import SystemCatalog
from interpreter.func_name import FuncName
from interpreter.vm.vm_types import VMState
from jackal.cli import run as jackal_run

from red_dragon_forge.build_command import run as forge_build
from red_dragon_forge.cics_command import cics_region
from red_dragon_forge.run_command import run as forge_run

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP = _REPO_ROOT / "vendor" / "carddemo" / "app"
_DB2_STUBS = _REPO_ROOT / "squall" / "squall" / "stubs"
_SQUALL_COPYBOOKS = _REPO_ROOT / "squall" / "squall" / "copybooks"
_FB80 = SequentialLabel(RecordFormat.FB, 80)
_TOP_PACKAGES = (
    "print(*sorted({name.split('.')[0] for name in sys.modules}), sep='\\n')\n"
)
_RUN_LOADED = (
    "import os, sys\n"
    "from red_dragon_forge.run_command import run\n"
    "rc = run(sys.argv[1:], os.environ)\n" + _TOP_PACKAGES + "raise SystemExit(rc)\n"
)
_REGION_LOADED = (
    "import os, sys\n"
    "from pathlib import Path\n"
    "import red_dragon_forge.run_command\n"
    "from red_dragon_forge.cics_command import cics_region\n"
    "cics_region(Path(sys.argv[1]), os.environ)\n" + _TOP_PACKAGES
)

_COPIER = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COPIER.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO INFILE
                  ORGANIZATION IS SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO OUTFILE
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE RECORDING MODE IS F.
       01  IN-REC   PIC X(80).
       FD  OUT-FILE RECORDING MODE IS F.
       01  OUT-REC  PIC X(80).
       WORKING-STORAGE SECTION.
       01  EOF-FLAG PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           OPEN OUTPUT OUT-FILE.
           PERFORM UNTIL EOF-FLAG = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO EOF-FLAG
                   NOT AT END
                       MOVE FUNCTION UPPER-CASE(IN-REC) TO OUT-REC
                       WRITE OUT-REC
               END-READ
           END-PERFORM.
           CLOSE IN-FILE.
           CLOSE OUT-FILE.
           MOVE 4 TO RETURN-CODE.
           GOBACK.
"""

_SETRC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SETRC.
       PROCEDURE DIVISION.
           MOVE 8 TO RETURN-CODE.
           GOBACK.
"""

_SELECTOR = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SELECTOR.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO RPTDD
                  ORGANIZATION IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE RECORDING MODE IS F.
       01  RPT-REC  PIC X(80).
       WORKING-STORAGE SECTION.
       01 WS-ID  PIC S9(9) COMP VALUE 11.
       01 WS-BAL PIC S9(9) COMP.
       01 WS-OUT PIC 9(9).
           EXEC SQL INCLUDE SQLCA END-EXEC.
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT ACCT_BAL
               INTO :WS-BAL
               FROM FORGERUN.ACCOUNT
               WHERE ACCT_ID = :WS-ID
           END-EXEC.
           MOVE WS-BAL TO WS-OUT.
           OPEN OUTPUT RPT-FILE.
           MOVE WS-OUT TO RPT-REC.
           WRITE RPT-REC.
           CLOSE RPT-FILE.
           GOBACK.
"""


def _sources(tmp_path: Path, programs: dict[str, str]) -> Path:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    for name, text in programs.items():
        (src / f"{name}.cbl").write_text(text)
    return src


def _built(tmp_path: Path, build: str, paths: str = "") -> Path:
    toml = tmp_path / "build.toml"
    toml.write_text(
        "[paths]\n"
        f'source_dirs = ["src", "{_APP / "cbl"}", "{_DB2_STUBS}"]\n'
        f"{paths}"
        f'[build]\nname = "app"\nout_dir = "out"\n{build}'
    )
    package = tmp_path / "out" / "app.zip"
    assert forge_build([str(toml)], os.environ) == 0
    return package


def _env(tmp_path: Path, name: str, package: Path, system: Path, sections: str) -> Path:
    env = tmp_path / name
    env.write_text(f'package = "{package}"\n[paths]\nsystem = "{system}"\n{sections}')
    return env


def _catalogued(system: Path, records: bytes) -> None:
    SystemCatalog(system).add("APP.IN", _upload(system.parent / "in", records), _FB80)
    SystemCatalog(system).add("APP.OUT", _upload(system.parent / "out.dat", b""), _FB80)


def _dataset_bytes(system: Path, dsn: str) -> bytes:
    match SystemCatalog(system).lookup(dsn):
        case Dataset(path=path):
            return path.read_bytes()
        case _:
            raise AssertionError(f"{dsn} is not cataloged")


def _upload(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_plain_matches_a_one_step_job(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sources(tmp_path, {"COPIER": _COPIER})
    package = _built(tmp_path, 'programs = ["COPIER"]\nlink = ["COPIER"]\n')
    capsys.readouterr()
    records = "first record".ljust(80).encode("cp037") + "second".ljust(80).encode(
        "cp037"
    )
    plain_system, jcl_system = (
        tmp_path / "plain" / "system",
        tmp_path / "jcl" / "system",
    )
    plain_system.parent.mkdir()
    jcl_system.parent.mkdir()
    _catalogued(plain_system, records)
    _catalogued(jcl_system, records)
    job = tmp_path / "copy.jcl"
    job.write_text(
        "//J JOB 1\n//PLAIN EXEC PGM=COPIER\n"
        "//INFILE DD DSN=APP.IN,DISP=SHR\n//OUTFILE DD DSN=APP.OUT,DISP=SHR\n"
    )
    plain = _env(
        tmp_path,
        "plain.toml",
        package,
        plain_system,
        '[plain]\nprogram = "COPIER"\n'
        '[plain.files]\nINFILE = "APP.IN"\nOUTFILE = "APP.OUT"\n',
    )
    jcl = _env(tmp_path, "jcl.toml", package, jcl_system, f'[jcl]\njob = "{job}"\n')

    plain_rc = forge_run([str(plain)], os.environ)
    plain_out = capsys.readouterr().out
    jcl_rc = forge_run([str(jcl)], os.environ)
    jcl_out = capsys.readouterr().out
    expected = "FIRST RECORD".ljust(80).encode("cp037") + "SECOND".ljust(80).encode(
        "cp037"
    )

    assert (
        (
            plain_rc,
            plain_out,
            _dataset_bytes(plain_system, "APP.OUT"),
        ),
        (
            jcl_rc,
            jcl_out,
            _dataset_bytes(jcl_system, "APP.OUT"),
        ),
    ) == ((0, "RC 4\n", expected), (1, "PLAIN: RC=4\n", expected))


def test_jcl_runs_a_multi_step_job_from_a_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sources(tmp_path, {"SETRC": _SETRC})
    package = _built(tmp_path, 'programs = ["SETRC"]\nlink = ["SETRC"]\n')
    capsys.readouterr()
    job = tmp_path / "steps.jcl"
    job.write_text(
        "//J JOB 1\n//A EXEC PGM=SETRC\n//B EXEC PGM=NOSUCH\n"
        "//C EXEC PGM=IEFBR14\n//D DD DSN=J.X,DISP=(NEW,DELETE,DELETE)\n"
    )
    system = tmp_path / "system"
    env = _env(tmp_path, "env.toml", package, system, f'[jcl]\njob = "{job}"\n')

    forge = (forge_run([str(env)], os.environ), capsys.readouterr().out)
    jackal = (
        jackal_run(
            ["run", str(job), "--package", str(package), "--system", str(system)]
        ),
        capsys.readouterr().out,
    )

    assert (forge, jackal) == (
        (1, "A: RC=8\nB: RC=0\nC: RC=0\n"),
        (1, "A: RC=8\nB: RC=0\nC: RC=0\n"),
    )


def _loaded(script: str, env: Path) -> tuple[int, list[str]]:
    ran = subprocess.run(
        [sys.executable, "-c", script, str(env)],
        capture_output=True,
        text=True,
        check=False,
    )
    return ran.returncode, ran.stdout.splitlines()


def test_a_jcl_run_loads_no_cics(tmp_path: Path) -> None:
    _sources(tmp_path, {"SETRC": _SETRC})
    package = _built(tmp_path, 'programs = ["SETRC"]\nlink = ["SETRC"]\n')
    job = tmp_path / "one.jcl"
    job.write_text("//J JOB 1\n//A EXEC PGM=SETRC\n")
    env = _env(
        tmp_path, "env.toml", package, tmp_path / "system", f'[jcl]\njob = "{job}"\n'
    )

    rc, (report, *loaded) = _loaded(_RUN_LOADED, env)

    assert (rc, report, {"cics"} & set(loaded)) == (1, "A: RC=8", set())


def test_each_fault_in_a_run_stops_it_naming_the_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sources(tmp_path, {"SELECTOR": _SELECTOR})
    package = _built(
        tmp_path,
        'programs = ["SELECTOR", "DSNTIAC"]\nlink = ["SELECTOR", "DSNTIAC"]\n'
        'coprocessors = ["sql"]\n',
        f'copybook_dirs = ["{_SQUALL_COPYBOOKS}"]\n',
    )
    capsys.readouterr()
    plain = '[sql]\n[plain]\nprogram = "SELECTOR"\n'
    missing = _env(tmp_path, "a.toml", tmp_path / "absent.zip", tmp_path, plain)
    sql = _env(tmp_path, "b.toml", package, tmp_path / "system", plain)
    (tmp_path / "plain").mkdir()
    _sources(tmp_path / "plain", {"SETRC": _SETRC})
    batch = _built(tmp_path / "plain", 'programs = ["SETRC"]\nlink = ["SETRC"]\n')
    capsys.readouterr()
    no_job = _env(
        tmp_path, "c.toml", batch, tmp_path, f'[jcl]\njob = "{tmp_path}/none.jcl"\n'
    )
    without_dsn = {k: v for k, v in os.environ.items() if k != "SQUALL_DB2_DSN"}
    with_hostname_only = {**without_dsn, "SQUALL_DB2_DSN": "HOSTNAME=localhost;PORT=1"}

    def stopped(env: Path, environ: dict[str, str]) -> tuple[int, str]:
        rc = forge_run([str(env)], environ)
        return rc, capsys.readouterr().err

    assert (
        stopped(missing, without_dsn),
        stopped(sql, without_dsn),
        stopped(sql, with_hostname_only),
        stopped(no_job, with_hostname_only),
    ) == (
        (
            1,
            f"forge-run: a.toml: package {tmp_path / 'absent.zip'}: [Errno 2] No such"
            f" file or directory: '{tmp_path / 'absent.zip'}'\n",
        ),
        (1, "forge-run: SQUALL_DB2_DSN is not set\n"),
        (1, "forge-run: SQUALL_DB2_DSN names no DATABASE\n"),
        (1, f"forge-run: {tmp_path / 'none.jcl'}: No such file or directory\n"),
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def _serving(env: Path, port: int) -> Iterator[None]:
    server = subprocess.Popen(
        [sys.executable, "-m", "red_dragon_forge.run_command", str(env)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        while not _listening(port) and time.monotonic() < deadline:
            time.sleep(0.2)
        yield
    finally:
        server.terminate()
        server.wait()


def _sign_on_screen(port: int) -> list[str]:
    emulator = subprocess.run(
        ["s3270", "-model", "2"],
        input=f"Connect(127.0.0.1:{port})\nWait(30,InputField)\nAscii()\nQuit()\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line[len("data: ") :]
        for line in emulator.stdout.splitlines()
        if line.startswith("data: ")
    ]


def test_cics_serves_sign_on_from_a_package(
    tmp_path: Path, carddemo_system: Path
) -> None:
    assert shutil.which("s3270"), "s3270 is not installed (brew install x3270)"
    bms = tmp_path / "bms"
    bms.mkdir()
    shutil.copy(_APP / "bms" / "COSGN00.bms", bms / "COSGN00.bms")
    package = _built(
        tmp_path,
        'programs = ["COSGN00C"]\nlink = ["COSGN00C"]\ncoprocessors = ["cics"]\n'
        f'[cics]\nbms_dirs = ["{bms}"]\n'
        f'csd_files = ["{_APP / "csd" / "CARDDEMO.CSD"}"]\n',
        f'copybook_dirs = ["{_APP / "cpy"}"]\n',
    )
    port = _free_port()
    env = _env(
        tmp_path,
        "env.toml",
        package,
        carddemo_system,
        f'[cics]\ninitial_transid = "CC00"\nport = {port}\n',
    )

    with _serving(env, port):
        screen = _sign_on_screen(port)

    assert screen[16:20] == [
        "                Type your User ID and Password, then press ENTER:               ",
        "                                                                                ",
        "                             User ID     :          (8 Char)                    ",
        "                             Password    :          (8 Char)                    ",
    ]


def test_a_cics_region_reads_its_datform_from_env_toml(
    tmp_path: Path, carddemo_system: Path
) -> None:
    bms = tmp_path / "bms"
    bms.mkdir()
    shutil.copy(_APP / "bms" / "COSGN00.bms", bms / "COSGN00.bms")
    package = _built(
        tmp_path,
        'programs = ["COSGN00C"]\nlink = ["COSGN00C"]\ncoprocessors = ["cics"]\n'
        f'[cics]\nbms_dirs = ["{bms}"]\n'
        f'csd_files = ["{_APP / "csd" / "CARDDEMO.CSD"}"]\n',
        f'copybook_dirs = ["{_APP / "cpy"}"]\n',
    )
    env = _env(
        tmp_path,
        "env.toml",
        package,
        carddemo_system,
        '[cics]\ninitial_transid = "CC00"\ndatform = "YYMMDD"\n',
    )

    region = cics_region(env, os.environ)

    datform = region.builtins[FuncName("__cics_datform")]([], VMState())
    assert datform.value == "YYMMDD"


def test_a_cics_region_loads_no_jackal(tmp_path: Path, carddemo_system: Path) -> None:
    bms = tmp_path / "bms"
    bms.mkdir()
    shutil.copy(_APP / "bms" / "COSGN00.bms", bms / "COSGN00.bms")
    package = _built(
        tmp_path,
        'programs = ["COSGN00C"]\nlink = ["COSGN00C"]\ncoprocessors = ["cics"]\n'
        f'[cics]\nbms_dirs = ["{bms}"]\n'
        f'csd_files = ["{_APP / "csd" / "CARDDEMO.CSD"}"]\n',
        f'copybook_dirs = ["{_APP / "cpy"}"]\n',
    )
    env = _env(
        tmp_path,
        "env.toml",
        package,
        carddemo_system,
        '[cics]\ninitial_transid = "CC00"\n',
    )

    rc, loaded = _loaded(_REGION_LOADED, env)

    assert (rc, {"jackal"} & set(loaded)) == (0, set())


@pytest.mark.usefixtures("db2_dsn")
def test_plain_sql_from_a_package(
    tmp_path: Path,
    db2_admin_conn: ibm_db.IBM_DBConnection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for statement in (
        "CREATE TABLE FORGERUN.ACCOUNT (ACCT_ID INTEGER, ACCT_BAL INTEGER)",
        "INSERT INTO FORGERUN.ACCOUNT VALUES (11, 500)",
    ):
        ibm_db.exec_immediate(db2_admin_conn, statement)
    _sources(tmp_path, {"SELECTOR": _SELECTOR})
    package = _built(
        tmp_path,
        'programs = ["SELECTOR", "DSNTIAC"]\nlink = ["SELECTOR", "DSNTIAC"]\n'
        'coprocessors = ["sql"]\n',
        f'copybook_dirs = ["{_SQUALL_COPYBOOKS}"]\n',
    )
    capsys.readouterr()
    system = tmp_path / "system"
    SystemCatalog(system).add("APP.RPT", _upload(tmp_path / "rpt", b""), _FB80)
    env = _env(
        tmp_path,
        "env.toml",
        package,
        system,
        '[sql]\n[plain]\nprogram = "SELECTOR"\n[plain.files]\nRPTDD = "APP.RPT"\n',
    )

    try:
        rc = forge_run([str(env)], os.environ)
    finally:
        ibm_db.exec_immediate(db2_admin_conn, "DROP TABLE FORGERUN.ACCOUNT")

    assert (
        rc,
        capsys.readouterr().out,
        _dataset_bytes(system, "APP.RPT"),
    ) == (0, "RC 0\n", "000000500".ljust(80).encode("cp037"))
