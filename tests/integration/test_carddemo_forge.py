"""CardDemo's checked-in build.toml and env.toml files build its online packages and serve them to a 3270 emulator."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

import pytest
from litter.open import open_package
from litter.transaction import Transaction

from red_dragon_forge.build_command import run as forge_build

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPO_ROOT / "config" / "carddemo"
_SCREEN_ROWS = 24
_BEFORE_THE_TIME = 70

_ONLINE_PROGRAMS = (
    "COSGN00C",
    "COMEN01C",
    "COADM01C",
    "COACTVWC",
    "COACTUPC",
    "COCRDLIC",
    "COCRDSLC",
    "COCRDUPC",
    "COTRN00C",
    "COTRN01C",
    "COTRN02C",
    "COBIL00C",
    "CORPT00C",
    "COUSR00C",
    "COUSR01C",
    "COUSR02C",
    "COUSR03C",
)
_CARDDEMO_TRANSACTIONS = tuple(
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
_DB2_TRANSACTIONS = (
    Transaction("CTLI", "COTRTLIC"),
    Transaction("CTTU", "COTRTUPC"),
)


@dataclass(frozen=True)
class _Region:
    build: str
    env: str
    out_dir: str
    port: int


_ONLINE = _Region("build.toml", "env.toml", "/tmp/carddemo-build", 3270)
_DB2 = _Region("build-db2.toml", "env-db2.toml", "/tmp/carddemo-db2-build", 3271)


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


def _built(root: Path, region: _Region) -> Path:
    build = _local(
        region.build,
        root,
        {'"../../': f'"{_REPO_ROOT}/', f'"{region.out_dir}"': f'"{root / "out"}"'},
    )
    assert forge_build([str(build)], os.environ) == 0
    return next((root / "out").glob("*.zip"))


@pytest.fixture(scope="module")
def online_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _built(tmp_path_factory.mktemp("online"), _ONLINE)


@pytest.fixture(scope="module")
def db2_package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _built(tmp_path_factory.mktemp("db2"), _DB2)


def _env(region: _Region, root: Path, package: Path, system: Path, port: int) -> Path:
    return _local(
        region.env,
        root,
        {
            f'"{region.out_dir}/': f'"{package.parent}/',
            '"/tmp/carddemo-system"': f'"{system}"',
            f"port = {region.port}": f"port = {port}",
        },
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


def _screens(port: int, keystrokes: Sequence[str]) -> list[list[str]]:
    script = "".join(
        f"{keys}\nEnter\nWait(30,InputField)\nAscii()\n" for keys in keystrokes
    )
    emulator = subprocess.run(
        ["s3270", "-model", "2"],
        input=f"Connect(127.0.0.1:{port})\nWait(30,InputField)\n{script}Quit()\n",
        capture_output=True,
        text=True,
        check=True,
    )
    rows = [
        line[len("data: ") :]
        for line in emulator.stdout.splitlines()
        if line.startswith("data: ")
    ]
    return [rows[at : at + _SCREEN_ROWS] for at in range(0, len(rows), _SCREEN_ROWS)]


def _rows(screen: Sequence[str]) -> list[str]:
    return [row.rstrip() for row in screen]


def test_each_build_toml_packages_its_programs_and_csd_transactions(
    online_package: Path, db2_package: Path
) -> None:
    online, db2 = open_package(online_package), open_package(db2_package)

    assert (
        (online.manifest.programs, online.manifest.coprocessors),
        online.manifest.transactions,
        (db2.manifest.programs, db2.manifest.coprocessors),
        db2.manifest.transactions,
    ) == (
        ((*_ONLINE_PROGRAMS, "CSUTLDTC", "CEEDAYS"), ("cics",)),
        _CARDDEMO_TRANSACTIONS,
        (
            (
                *_ONLINE_PROGRAMS,
                "COTRTLIC",
                "COTRTUPC",
                "CSUTLDTC",
                "CEEDAYS",
                "DSNTIAC",
            ),
            ("cics", "sql"),
        ),
        _CARDDEMO_TRANSACTIONS + _DB2_TRANSACTIONS,
    )


def test_a_user_signs_on_and_views_an_account(
    tmp_path: Path, online_package: Path, carddemo_system: Path
) -> None:
    assert shutil.which("s3270"), "s3270 is not installed (brew install x3270)"
    port = _free_port()
    env = _env(_ONLINE, tmp_path, online_package, carddemo_system, port)

    with _serving(env, port):
        screens = _screens(
            port,
            (
                'String("USER0001")\nString("PASSWORD")',
                'String("01")',
                'String("00000000050")',
            ),
        )

    menu, _, account = (_rows(screen) for screen in screens)
    assert (
        menu[0][:_BEFORE_THE_TIME],
        menu[3:16],
        account[0][:_BEFORE_THE_TIME],
        account[3:19],
    ) == (
        " Tran: CM00                AWS Mainframe Modernization           Date:",
        [
            "                                   Main Menu",
            "",
            "                    01. Account View",
            "                    02. Account Update",
            "                    03. Credit Card List",
            "                    04. Credit Card View",
            "                    05. Credit Card Update",
            "                    06. Transaction List",
            "                    07. Transaction View",
            "                    08. Transaction Add",
            "                    09. Transaction Reports",
            "                    10. Bill Payment",
            "                    11. Pending Authorization View",
        ],
        " Tran: CAVW                AWS Mainframe Modernization           Date:",
        [
            "                                 View Account",
            "                   Account Number :   00000000050        Active Y/N:  Y",
            "        Opened:  2011-04-22            Credit Limit        : +      6,169.00",
            "        Expiry:  2023-03-09            Cash credit Limit   : +      4,587.00",
            "        Reissue: 2023-03-09            Current Balance     : +        492.00",
            "                                       Current Cycle Credit: +           .00",
            "        Account Group:                 Current Cycle Debit : +           .00",
            "                                Customer Details",
            "        Customer id  : 000000050                 SSN: 931-24-8469",
            "        Date of birth: 1960-12-01                FICO Score: 623",
            " First Name                 Middle Name:               Last Name :",
            " Aniya                      Alba                       Von",
            " Address: 1588 Nienow Cape                                     State     OR",
            "          Suite 187                                            Zip       04257",
            " City     New Aricchester                                      Country   USA",
            " Phone 1: (325)301-0827 Government Issued Id Ref    :     00000000000030387824",
        ],
    )


@pytest.mark.usefixtures("db2_dsn", "carddemo_db2_schema")
def test_an_admin_reaches_the_db2_transaction_type_list(
    tmp_path: Path, db2_package: Path, carddemo_system: Path
) -> None:
    assert shutil.which("s3270"), "s3270 is not installed (brew install x3270)"
    port = _free_port()
    env = _env(_DB2, tmp_path, db2_package, carddemo_system, port)

    with _serving(env, port):
        screens = _screens(
            port, ('String("ADMIN001")\nString("PASSWORD")', 'String("05")')
        )

    listed = _rows(screens[1])
    assert (listed[0][:_BEFORE_THE_TIME], listed[3:24]) == (
        " Tran: CTLI                AWS Mainframe Modernization           Date:",
        [
            "                            Maintain Transaction Type                 Page  1",
            "",
            "                              Type Filter:",
            "",
            "    Description Filter:",
            "",
            "    Select      Type                      Description",
            "    ------     -----     --------------------------------------------------",
            "                 01      PURCHASE",
            "                 02      PAYMENT",
            "                 03      CREDIT",
            "                 04      AUTHORIZATION",
            "                 05      REFUND",
            "                 06      REVERAL",
            "                 07      ADJUSTMENT",
            "",
            "",
            "                     Type U to update, D to delete any record",
            "",
            "",
            " F2=Add   F3=Exit  F7=Page Up   F8=Page Dn  F10=Save",
        ],
    )
