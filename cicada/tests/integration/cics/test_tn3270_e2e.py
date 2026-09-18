from __future__ import annotations

import os
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pytest

from cics.tn3270.config import load_config
from tests.covers import NotLanguageFeature, covers
from tests.integration.cics.tn3270_helpers import (
    REPO_ROOT,
    S3270,
    records,
    served_session,
)
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

pytestmark = [pytest.mark.carddemo_e2e, pytest.mark.tn3270_e2e]

_CONFIG = Path(__file__).parents[3] / "config" / "carddemo-tn3270.toml"


def _records(name: str, length: int) -> list[bytes]:
    return records(Path(os.environ["CARDDEMO_HOME"]) / "data/EBCDIC", name, length)


@dataclass(frozen=True)
class _AccountView:
    """What COACTVWC must show for the first CXACAIX cross-reference. Only
    ``account`` is typed at the terminal; ``first_name`` can only come from the
    CXACAIX -> CUSTDAT leg of the join and ``opened`` from the ACCTDAT leg, so
    they are what distinguishes a rendered account from "Account not found".

    Record layouts: CVACT03Y CUST-ID 9(9)@16, ACCT-ID 9(11)@25; CVCUS01Y
    CUST-ID 9(9)@0, FIRST-NAME X(25)@9; CVACT01Y ACCT-ID 9(11)@0, OPEN-DATE
    X(10)@48.
    """

    account: str
    first_name: str
    opened: str


def _account_view() -> _AccountView:
    xref = _records("AWS.M2.CARDDEMO.CARDXREF.PS", 50)[0]
    customer, account = xref[16:25].decode("cp037"), xref[25:36].decode("cp037")
    (custdat,) = (
        r
        for r in _records("AWS.M2.CARDDEMO.CUSTDATA.PS", 500)
        if r[:9].decode("cp037") == customer
    )
    (acctdat,) = (
        r
        for r in _records("AWS.M2.CARDDEMO.ACCTDATA.PS", 300)
        if r[:11].decode("cp037") == account
    )
    return _AccountView(
        account=account,
        first_name=custdat[9:34].decode("cp037").strip(),
        opened=acctdat[48:58].decode("cp037"),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_signon_menu_account_view_and_back(tmp_path, bridge_jar, monkeypatch):
    monkeypatch.setenv("FORGE_ROOT", str(REPO_ROOT))
    config = load_config(_CONFIG)
    expected = _account_view()

    with served_session(config, bridge_jar, tmp_path) as served:
        # closing() terminates the emulator however the test ends — a failed
        # assertion inside S3270.run must not leave an s3270 behind.
        with closing(S3270()) as terminal:
            terminal.connect(served.port)
            assert "User ID" in terminal.screen()
            terminal.run('String("USER0001")')
            # An 8-character user id fills USERID exactly, so the 3270 auto-skip already
            # leaves the cursor in PASSWD; tabbing here would overshoot to the one-byte
            # unprotected stopper field COSGN00 places after the password.
            terminal.run('String("PASSWORD")')
            assert "Main Menu" in terminal.enter()
            terminal.run('String("01")')
            assert "View Account" in terminal.enter()
            terminal.run(f'String("{expected.account}")')
            shown = terminal.enter()
            assert expected.account in shown
            assert expected.first_name in shown
            assert expected.opened in shown
            assert "Tran:" in shown.splitlines()[0]
            assert "Main Menu" in terminal.enter("PF(3)")
