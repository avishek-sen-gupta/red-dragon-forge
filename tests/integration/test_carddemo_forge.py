"""CardDemo's checked-in build.toml and env.toml files build its online packages and serve them to a 3270 emulator."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from typing import NamedTuple
from contextlib import contextmanager
from pathlib import Path

import pytest
from litter.open import open_package
from litter.transaction import Transaction

from catnip.system_catalog import SystemCatalog
from cics.tn3270.region import assemble_region

from tests.carddemo_packages import DB2, ONLINE, local_env

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
    carddemo_online_package: Path, carddemo_db2_package: Path
) -> None:
    online, db2 = open_package(carddemo_online_package), open_package(
        carddemo_db2_package
    )

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
    tmp_path: Path, carddemo_online_package: Path, carddemo_system: Path
) -> None:
    assert shutil.which("s3270"), "s3270 is not installed (brew install x3270)"
    port = _free_port()
    env = local_env(ONLINE, tmp_path, carddemo_online_package, carddemo_system, port)

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
    tmp_path: Path, carddemo_db2_package: Path, carddemo_system: Path
) -> None:
    assert shutil.which("s3270"), "s3270 is not installed (brew install x3270)"
    port = _free_port()
    env = local_env(DB2, tmp_path, carddemo_db2_package, carddemo_system, port)

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


def test_the_db2_package_serves_both_trees_mapsets(
    carddemo_db2_package: Path, carddemo_system: Path
) -> None:
    region = assemble_region(
        open_package(carddemo_db2_package), SystemCatalog(carddemo_system)
    )

    assert sorted(region.catalog.maps) == [
        ("COACTUP", "CACTUPA"),
        ("COACTVW", "CACTVWA"),
        ("COADM01", "COADM1A"),
        ("COBIL00", "COBIL0A"),
        ("COCRDLI", "CCRDLIA"),
        ("COCRDSL", "CCRDSLA"),
        ("COCRDUP", "CCRDUPA"),
        ("COMEN01", "COMEN1A"),
        ("CORPT00", "CORPT0A"),
        ("COSGN00", "COSGN0A"),
        ("COTRN00", "COTRN0A"),
        ("COTRN01", "COTRN1A"),
        ("COTRN02", "COTRN2A"),
        ("COTRTLI", "CTRTLIA"),
        ("COTRTUP", "CTRTUPA"),
        ("COUSR00", "COUSR0A"),
        ("COUSR01", "COUSR1A"),
        ("COUSR02", "COUSR2A"),
        ("COUSR03", "COUSR3A"),
    ]


class Step(NamedTuple):
    """One turn of the tour: s3270 actions, then text the screen must show
    (``expect``) and text it must not (``absent``)."""

    name: str
    actions: str
    expect: str
    absent: str = ""


def _drive(port: int, steps: Sequence[Step]) -> list[list[str]]:
    """Run every step in one s3270 session; after each, wait for the keyboard
    to unlock and dump the screen. Returns one screen per step."""
    script = "".join(f"{step.actions}\nWait(30,Unlock)\nAscii()\n" for step in steps)
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


_ACCT = 'String("00000000001")'
_CARD = 'String("9680294154603697")'
_NEXT_TRAN_ID = "0000000996722788"  # one past the highest key in the shipped DALYTRAN

# The whole online tier through the shipped package, as a terminal user drives it:
# every menu option the plain package serves (01-08, 10; 09 needs JCL, 11 ships no
# source), paging on each list, one validation error per update screen, the
# two-turn ENTER-then-PF5 commit, a write read back by key, and admin user CRUD.
# Each step names the screen text that proves the turn did what a real CICS
# region does; the account update step is the one that proves CSUTLDTC and
# CEEDAYS, linked as callees, accept CardDemo's undashed YYYYMMDD dates.
_TOUR = (
    Step("sign on", 'String("USER0001")\nString("PASSWORD")\nEnter', "Main Menu"),
    Step("01 account view: prompt", 'String("01")\nEnter', "View Account"),
    Step("01 account view: account 1", f"{_ACCT}\nEnter", "Kessler"),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("02 account update: prompt", 'String("02")\nEnter', "Update Account"),
    Step(
        "02 account update: fetch",
        f"{_ACCT}\nEnter",
        "Update account details presented above",
    ),
    Step(
        "02 account update: an out-of-range FICO fails the edit",
        'MoveCursor(12,62)\nString("999")\nEnter',
        "FICO Score: should be between",
    ),
    Step(
        "02 account update: FICO, zip and phone 2 validate; open date 20141120 passes CEEDAYS",
        'MoveCursor(12,62)\nString("720")\nMoveCursor(16,73)\nString("27601")\n'
        'MoveCursor(19,10)\nString("2125550100")\nEnter',
        "Changes validated.Press F5 to save",
    ),
    Step("02 account update: PF5 commits", "PF(5)", "Changes committed to database"),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("03 card list: page 1", 'String("03")\nEnter', "List Credit Cards"),
    Step("03 card list: PF8 pages forward", "PF(8)", "1561409106491600"),
    Step("03 card list: PF7 pages back", "PF(7)", "0500024453765740"),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("04 card view: prompt", 'String("04")\nEnter', "View Credit Card Detail"),
    Step(
        "04 card view: account 1's card", f"{_ACCT}\n{_CARD}\nEnter", "Immanuel Kessler"
    ),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("05 card update: prompt", 'String("05")\nEnter', "Update Credit Card Details"),
    Step(
        "05 card update: fetch",
        f"{_ACCT}\n{_CARD}\nEnter",
        "Details of selected card shown above",
    ),
    Step(
        "05 card update: new name and expiry year validate",
        'DeleteField()\nString("IMMANUEL K KESSLER")\nTab()\nTab()\nTab()\nString("2027")\nEnter',
        "Changes validated.Press F5 to save",
    ),
    Step("05 card update: PF5 commits", "PF(5)", "Changes committed to database"),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step(
        "04 card view: prompt again", 'String("04")\nEnter', "View Credit Card Detail"
    ),
    Step(
        "04 card view: the committed name",
        f"{_ACCT}\n{_CARD}\nEnter",
        "IMMANUEL K KESSLER",
    ),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("06 transaction list: page 1", 'String("06")\nEnter', "0000000000683580"),
    Step("06 transaction list: PF8 pages forward", "PF(8)", "0000000025430891"),
    Step("06 transaction list: PF7 pages back", "PF(7)", "0000000000683580"),
    Step(
        "06 transaction list: S opens the first row",
        'Tab()\nString("S")\nEnter',
        "View Transaction",
    ),
    Step("PF3 from the view returns to the menu", "PF(3)", "Main Menu"),
    Step("08 add transaction: prompt", 'String("08")\nEnter', "Add Transaction"),
    Step(
        "08 add transaction: an unsigned amount fails the edit",
        f'{_ACCT}\nTab()\nString("01")\nString("0001")\nString("POS TERM")\nTab()\n'
        'String("Coffee at Blue Bottle")\nTab()\nString("12.50")\nTab()\n'
        'String("2026-11-05")\nString("2026-11-05")\nString("000000789")\n'
        'String("Blue Bottle Coffee")\nTab()\nString("Oakland")\nTab()\nString("94607")\nEnter',
        "Amount should be in format",
    ),
    Step(
        "08 add transaction: a signed amount asks for confirmation",
        'DeleteField()\nString("+00000012.50")\nEnter',
        "Confirm to add this transaction",
    ),
    Step(
        "08 add transaction: Y writes it",
        'String("Y")\nEnter',
        f"Your Tran ID is {_NEXT_TRAN_ID}",
    ),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("07 transaction view: prompt", 'String("07")\nEnter', "View Transaction"),
    Step(
        "07 transaction view: the record just written",
        f'String("{_NEXT_TRAN_ID}")\nEnter',
        "Blue Bottle",
    ),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("10 bill payment: prompt", 'String("10")\nEnter', "Bill Payment"),
    Step(
        "10 bill payment: the balance asks for confirmation",
        f"{_ACCT}\nEnter",
        "Confirm to make a bill payment",
    ),
    Step("10 bill payment: Y pays it", 'String("Y")\nEnter', "Payment successful"),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("01 account view: prompt again", 'String("01")\nEnter', "View Account"),
    Step(
        "01 account view: balance cleared, FICO committed",
        f"{_ACCT}\nEnter",
        "720",
        absent="194.00",
    ),
    Step("back to menu", "PF(3)", "Main Menu"),
    Step("PF3 at the menu signs off", "PF(3)", "Thank you for using CardDemo"),
    Step(
        "CLEAR then CC00 restarts sign-on",
        'Clear()\nString("CC00")\nEnter',
        "Type your User ID",
    ),
    Step(
        "admin sign on", 'String("ADMIN001")\nString("PASSWORD")\nEnter', "Admin Menu"
    ),
    Step("admin 01 list users", 'String("01")\nEnter', "List Users"),
    Step("back to admin menu", "PF(3)", "Admin Menu"),
    Step("admin 02 add user: prompt", 'String("02")\nEnter', "Add User"),
    Step(
        "admin 02 add user: USER0006",
        'String("CAROL")\nTab()\nString("DIAZ")\nTab()\nString("USER0006")\nString("PASSWORD")\nString("U")\nEnter',
        "User USER0006 has been added",
    ),
    Step("back to admin menu", "PF(3)", "Admin Menu"),
    Step("admin 01 list users: page 1", 'String("01")\nEnter', "List Users"),
    Step("admin 01 list users: PF8 shows the new user on page 2", "PF(8)", "USER0006"),
    Step("admin 01 list users: PF7 pages back", "PF(7)", "ADMIN001"),
    Step("back to admin menu", "PF(3)", "Admin Menu"),
    Step("admin 03 update user: prompt", 'String("03")\nEnter', "Update User"),
    Step(
        "admin 03 update user: fetch",
        'String("USER0006")\nEnter',
        "Press PF5 key to save your updates",
    ),
    Step(
        "admin 03 update user: PF5 saves",
        'Tab()\nDeleteField()\nString("CAROLINE")\nTab()\nDeleteField()\nString("DIAZ")\nTab()\nString("PASSWORD")\nString("U")\nPF(5)',
        "User USER0006 has been updated",
    ),
    Step("back to admin menu", "PF(3)", "Admin Menu"),
    Step("admin 04 delete user: prompt", 'String("04")\nEnter', "Delete User"),
    Step(
        "admin 04 delete user: fetch",
        'String("USER0006")\nEnter',
        "Press PF5 key to delete this user",
    ),
    Step(
        "admin 04 delete user: PF5 deletes", "PF(5)", "User USER0006 has been deleted"
    ),
    Step("back to admin menu", "PF(3)", "Admin Menu"),
    Step(
        "admin 01 list users from USER0001: she is gone",
        'String("01")\nEnter\nWait(30,Unlock)\nString("USER0001")\nEnter',
        "LAWRENCE",
        absent="USER0006",
    ),
)


def test_a_terminal_user_tours_every_online_screen(
    tmp_path: Path, carddemo_online_package: Path, carddemo_system: Path
) -> None:
    assert shutil.which("s3270"), "s3270 is not installed (brew install x3270)"
    port = _free_port()
    env = local_env(ONLINE, tmp_path, carddemo_online_package, carddemo_system, port)

    with _serving(env, port):
        screens = _drive(port, _TOUR)

    assert len(screens) == len(_TOUR), f"{len(screens)} screens for {len(_TOUR)} steps"
    for step, screen in zip(_TOUR, screens):
        text = "\n".join(screen)
        assert step.expect in text, f"{step.name}: no {step.expect!r} on\n{text}"
        assert (
            not step.absent or step.absent not in text
        ), f"{step.name}: {step.absent!r} still on\n{text}"
