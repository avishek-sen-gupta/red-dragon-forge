"""Task 11 (2026-09-19-carddemo-db2-tier): CardDemo's two Db2 screens, driven
headlessly against a live Db2 through the composed region.

This is what tasks 4-10 were for. Admin option 06 (COTRTUPC / CTTU) and admin
option 05 (COTRTLIC / CTLI) are signed on to and driven a terminal turn at a
time through ``PseudoConversationalDriver``, exactly as
``cics.tn3270.session`` drives them over the wire.

**Every assertion about committed state goes through ``db2_probe_conn``** -- a
connection separate from the one the region's ``Db2Backend`` holds. Reading
back through the program's own connection cannot distinguish "committed" from
"still pending on this session", so a suite built that way passes on every
unit-of-work defect Task 6 fixed. See the fixture's own docstring in
``conftest.py``.

**The padding contract.** Both programs compute ``DCL-TR-DESCRIPTION-LEN`` as
``FUNCTION LENGTH`` of a ``PIC X(50)`` item (``COTRTUPC.cbl:1541-1542``,
``COTRTLIC.cbl:1843-1844``), so the VARCHAR they write is ALWAYS 50 characters,
never the text's real length. Every committed-state assertion therefore checks
``RTRIM(TR_DESCRIPTION)`` *and* ``LENGTH(TR_DESCRIPTION) = 50``. The seed rows
are loaded unpadded (``carddemo_db2_schema``), so the length going from 6 to 50
is itself evidence the program wrote the row rather than the seed still
standing.

**Why ``_Terminal`` sends back fields the test never typed.** A 3270 transmits
every field whose modified-data tag is set, and both maps mark their key and
row fields ``FSET`` -- ``COTRTUP.bms``'s TRNNAME, ``COTRTLI.bms``'s TRTSELn /
TRTTYPn / TRTYPDn. COTRTUPC and COTRTLIC rely on that: ``1100-RECEIVE-SCREEN``
(COTRTLIC.cbl:930-953) re-reads the row's protected type code out of the map to
build the UPDATE's key. The wire path already behaves this way --
``cics.tn3270.session`` builds its ``InputEvent`` from ``decode_inbound``, the
real inbound datastream. ``_Terminal.press`` reproduces it for the headless
driver by sending every MDT-set field's current content, with the test's own
keystrokes overlaid. Supplying only the typed fields is not a smaller version
of the same thing: it silently blanks the key, and an UPDATE then writes
nowhere.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

import ibm_db
import pytest
from cics.dispatcher import InputEvent
from cics.screen.terminal_screen import TerminalScreen
from tests.carddemo_packages import DB2, local_env
from tests.carddemo_system import installed_carddemo
from squall.backends.db2 import Db2Backend

from red_dragon_forge.cics_command import cics_region

# Task 12: CardDemo's own defects (Part E of
# .superpowers/sdd/db2-epic/carddemo-db2-behaviour.md), pinned as
# characterisation tests below or noted here as not worth (or not able to
# be) a live-Db2 test. These are CardDemo's bugs, present in vendor/carddemo
# (never edited here), not defects in this Db2 tier. Items 4 and 2 each get a
# characterisation test at the bottom of this file, and item 5 gets a test of
# the boundary that keeps it from being observable at all; the rest are
# recorded here rather than tested, because they need no live Db2 turn to
# observe (3, 6-8) or duplicate what a targeted unit/isolation test already
# covers better (1, already pinned by this suite's "padding contract"
# docstring above):
#   1. Every description either screen writes is stored 50-byte blank-padded,
#      because DCL-TR-DESCRIPTION-LEN is computed from a PIC X(50) field, not
#      the actual text length (COTRTUPC.cbl:1541-1542, COTRTLIC.cbl:1843-1844).
#   3. 9800-DELETE-PROCESSING STRINGs SQLERRM OF SQLCA twice into the -532
#      message (COTRTUPC.cbl:1645-1646) -- verified by execution that this
#      has NO observable effect: WS-RETURN-MSG is PIC X(75), and the first
#      copy of SQLERRM alone already fills the field, so the STRING
#      statement's implicit truncation (COBOL, no ON OVERFLOW) discards the
#      second copy before it can ever reach the screen.
#   5. 9300-DELETE-RECORD's WHEN OTHER (COTRTLIC.cbl:1926-1934) never sets
#      WS-CA-DELETE-FLAG, so a non--532 delete failure leaves the flag
#      exactly as the dispatcher's CA-DELETE-SUCCEEDED test at
#      COTRTLIC.cbl:817 found it. The code shape is real and the branch IS
#      live-reachable -- COTRTLIC.cbl:580-581 and 667-668 are DISJUNCTIONS,
#      admitting PF10 on CA-UPDATE-REQUESTED alone, so 9300-DELETE-RECORD
#      genuinely runs on a session where nothing ever set the delete flag
#      (test_admin_five_delete_failure_after_an_update_selection below
#      drives that path and observes the failure message WHEN OTHER builds).
#      The false success it looks like it should produce is nonetheless NOT
#      observable, for a reason independent of reachability: every write
#      that leaves WS-CA-DELETE-FLAG "unset" is an INITIALIZE
#      (COTRTLIC.cbl:516, 548, 742, 827), which COBOL defines as SPACES,
#      while CA-DELETE-SUCCEEDED is an 88 on LOW-VALUES (item 6) -- so
#      COTRTLIC.cbl:817 is FALSE and the operator is correctly told the
#      delete failed. The only statement that ever stores LOW-VALUES there
#      is SET CA-DELETE-SUCCEEDED after a SUCCESSFUL delete
#      (COTRTLIC.cbl:1910), and COTRTLIC.cbl:826-833 INITIALIZEs the
#      commarea back to spaces within that same turn, so LOW-VALUES never
#      survives into a turn in which WHEN OTHER could run.
#   6. CA-DELETE-SUCCEEDED/CA-DELETE-NOT-REQUESTED and
#      CA-UPDATE-SUCCEEDED/CA-UPDATE-NOT-REQUESTED are the same LOW-VALUES
#      encoding on the same field (COTRTLIC.cbl:411-418) -- the collision
#      item 5 above would need, and which only ever holds for the one turn
#      in which a delete has just succeeded.
#   7. WHEN CCARD-AID-PFK07 AND CA-FIRST-PAGE is dispatched twice
#      (COTRTLIC.cbl:721-722 and 726-727) -- harmless fall-through.
#   8. Dead code: TTUP-REVIEW-NEW-RECORD ('V'), FOUND-TRANTYPE-DATA,
#      DATA-WAS-CHANGED-BEFORE-UPDATE, NO-SEARCH-CRITERIA-RECEIVED,
#      WS-NAME-MUST-BE-ALPHA, CODING-TO-BE-DONE, WS-TYPE-CD-DELETE-FILTER
#      (COTRTLIC.cbl:279-301, never used in any SQL), SEND-PLAIN-TEXT, and the
#      F6=Add map label.


# DFHAID.cpy's attention identifiers, as the terminal sends them.
_ENTER = "\x7d"
_PF4 = "\xf4"
_PF5 = "\xf5"
_PF7 = "\xf7"
_PF8 = "\xf8"
_PF10 = "\x7a"

_ADMIN = {"USERID": "ADMIN001", "PASSWD": "PASSWORD"}
_TABLE = "CARDDEMO.TRANSACTION_TYPE"


class _Terminal:
    """One 3270 session against the region, carrying the screen between turns.

    Holds the ``TerminalScreen`` the driver's payloads paint, so ``press`` can
    send back the MDT-set fields a real terminal would (see the module
    docstring) rather than only what the test typed.
    """

    def __init__(self, region) -> None:
        self._region = region
        self.screen = TerminalScreen()

    def _apply(self, turn) -> None:
        for payload in turn.screens:
            self.screen = self.screen.apply_payload(payload, self._region.catalog)

    def start(self, transid: str) -> None:
        self.screen = TerminalScreen()
        self._apply(self._region.driver.start(transid))

    def press(self, aid: str = _ENTER, **typed: str) -> None:
        self._apply(self._region.driver.respond(InputEvent(aid, self._inbound(typed))))

    def _inbound(self, typed: Mapping[str, str]) -> dict[str, str]:
        transmitted = {
            field.name: field.content
            for field in self.screen.fields
            if field.name and field.modified
        }
        return {**transmitted, **typed}

    def text(self) -> str:
        return self.screen.text()

    def value(self, name: str) -> str:
        return self.screen.field(name).content.strip()

    def sign_on_to_admin_option(self, option: str) -> None:
        self.start("CC00")
        self.press(**_ADMIN)
        self.press(OPTION=option)


class _SqlSpy:
    """Every SQL statement the region's backend executed, in order.

    Patched onto ``Db2Backend`` itself rather than the region's instance so it
    catches cursor OPENs too, and so "no SQL at all was issued this turn" is a
    statement about the whole backend surface, not one method of it.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.statements: list[str] = []
        for name in ("execute", "open_cursor"):
            monkeypatch.setattr(Db2Backend, name, self._recording(name))

    def _recording(self, name: str):
        original = getattr(Db2Backend, name)

        def recorded(backend, sql_or_name, *args):
            self.statements.append(sql_or_name if name == "execute" else args[0])
            return original(backend, sql_or_name, *args)

        return recorded

    def clear(self) -> None:
        self.statements.clear()


def _description(probe_conn, tr_type: str) -> tuple[str, int]:
    """``(RTRIM(TR_DESCRIPTION), LENGTH(TR_DESCRIPTION))`` for *tr_type*, read
    on the probe connection. Raises if the row is absent -- a missing row is
    never the answer a caller of this function wants silently coerced."""
    stmt = ibm_db.exec_immediate(
        probe_conn,
        "SELECT RTRIM(TR_DESCRIPTION), LENGTH(TR_DESCRIPTION) "
        f"FROM {_TABLE} WHERE TR_TYPE = '{tr_type}'",
    )
    row = ibm_db.fetch_tuple(stmt)  # type: ignore[reportArgumentType]
    assert row, f"no {_TABLE} row for TR_TYPE {tr_type!r} on the probe connection"
    text, length = tuple(row)
    return str(text), int(length)  # type: ignore[reportArgumentType]


def _row_count(probe_conn) -> int:
    stmt = ibm_db.exec_immediate(probe_conn, f"SELECT COUNT(*) FROM {_TABLE}")
    row = ibm_db.fetch_tuple(stmt)  # type: ignore[reportArgumentType]
    # ibm_db's stub types fetch_tuple()'s row as tuple[object, ...]; the driver
    # returns a real int for an integer column (see squall.backends.db2's own
    # docstring on this stub boundary).
    return int(tuple(row)[0])  # type: ignore[reportArgumentType]


def _shows_info_prompt(terminal: _Terminal, message: str) -> bool:
    """Whether INFOMSG is showing exactly *message*.

    Both programs centre the prompt before sending it (COTRTUPC.cbl:1249-1262,
    COTRTLIC.cbl:1560-1577). That centring used to render truncated -- the
    bridge discarded everything but the FUNCTION inside ``COMPUTE
    WS-STRING-MID = (FUNCTION LENGTH(WS-INFO-MSG) - WS-STRING-LEN) / 2 + 1``,
    so the text landed at ``LENGTH(WS-INFO-MSG) / 2 + 1`` and ran off the end
    of the item. Fixed upstream in red-dragon 8f432872 (forge-84k); this
    asserts the whole prompt rather than a surviving prefix.
    """
    return terminal.value("INFOMSG") == message


@pytest.fixture(scope="module", autouse=True)
def region(tmp_path_factory, request):
    """The composed CardDemo Db2 region, assembled ONCE for this module from
    the package config/carddemo/build-db2.toml builds, by forge-run's own
    ``cics_region`` over config/carddemo/env-db2.toml.

    Autouse and module-scoped on purpose: building the package lowers all of
    its programs through the ProLeap bridge, which is far too slow per test.
    The region carries its own builtins table, so nothing it composes reaches
    another module's runs.
    """
    if not os.environ.get("SQUALL_DB2_DSN"):
        pytest.skip("SQUALL_DB2_DSN not set; source tests/integration/db2_env.sh")
    package = request.getfixturevalue("carddemo_db2_package")
    root = tmp_path_factory.mktemp("db2_region")
    env = local_env(DB2, root, package, installed_carddemo(root), DB2.port)
    yield cics_region(env, os.environ)


@pytest.fixture
def terminal(region) -> _Terminal:
    return _Terminal(region)


@pytest.fixture
def sql_spy(monkeypatch) -> _SqlSpy:
    return _SqlSpy(monkeypatch)


@pytest.fixture(autouse=True)
def _bounded_probe_waits(db2_probe_conn):
    """Bound how long the probe can ever wait on a lock -- belt and braces,
    not what makes the commit-boundary proof falsifiable.

    With ``db2_probe_conn`` pinned to READ_COMMITTED (see conftest.py), a
    cursor-stability read against a row another connection has updated but
    not committed does not block at all under Db2's default ``cur_commit``
    behaviour: it returns the currently-committed version instead (confirmed
    by this suite's own negative control -- reverting SYNCPOINT to a no-op
    makes the probe return the stale row, not hang). So in the configuration
    this suite actually runs under, this timeout is dead code for that path.
    It still matters as a guard against any future or differently-configured
    Db2 that *does* block a CS reader (``cur_commit=DISABLED``, a higher
    isolation level, etc.) -- ten seconds there turns an indefinite hang into
    an SQL0911N instead.
    """
    ibm_db.exec_immediate(db2_probe_conn, "SET CURRENT LOCK TIMEOUT 10")


# ── Step 1: admin 6, the update path ────────────────────────────────────────


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_six_updates_a_transaction_type(terminal, sql_spy, db2_probe_conn):
    """Verified by execution. Sign on, option 06, key '3' (COTRTUPC normalises
    it to '03' at 834-842 before the SELECT at 1475-1482), overtype the
    description, ENTER to validate, F5 to save.

    The ENTER turn must issue NO SQL: 1200-EDIT-MAP-INPUTS only compares old
    against new and sets TTUP-CHANGES-OK-NOT-CONFIRMED, and 9600-WRITE-PROCESSING
    is reached only from the F5 branch at 514-520. A runtime that wrote on
    ENTER would still leave the right row behind at the end of the test, so the
    spy is what makes the intermediate turn's behaviour assertable at all.
    """
    terminal.sign_on_to_admin_option("06")

    terminal.press(TRTYPCD="3")
    assert terminal.value("TRTYPCD") == "03"
    assert terminal.value("TRTYDSC") == "CREDIT"

    sql_spy.clear()
    terminal.press(TRTYDSC="CREDIT BALANCE")
    assert _shows_info_prompt(terminal, "Changes validated.Press F5 to save")
    assert sql_spy.statements == []
    assert _description(db2_probe_conn, "03") == ("CREDIT", 6)

    terminal.press(_PF5)
    assert _description(db2_probe_conn, "03") == ("CREDIT BALANCE", 50)


# ── Step 2: the commit boundary ─────────────────────────────────────────────


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_the_update_is_committed_before_the_task_returns(
    terminal, region, db2_probe_conn, monkeypatch
):
    """Verified by execution. The proof Task 6 bought: the row is visible on a
    SEPARATE connection *during* the task, not merely by the time it ends.

    This is a direct, interleaved assertion rather than a spy on COMMIT.
    COTRTUPC's F5 path runs 9600-WRITE-PROCESSING (SYNCPOINT at 1557), then
    3000-SEND-MAP, then RETURN TRANSID at 567. The SEND MAP puts its payload on
    the region's screen channel (cics/builtins/screen.py:188), so probing from
    inside that ``put`` reads committed state at a point that is unambiguously
    after the syncpoint and before task end. Task end commits too, so a probe
    taken after ``press`` returns could not tell the two apart -- which is
    exactly the defect Task 6 fixed (SYNCPOINT was a no-op) and exactly what
    this test would miss if it probed a moment later.
    """
    terminal.sign_on_to_admin_option("06")
    terminal.press(TRTYPCD="3")
    terminal.press(TRTYDSC="CREDIT BALANCE")

    channel = region.driver.screen_channel
    original_put = channel.put
    at_send_map: list[tuple[str, int]] = []

    def probing_put(item):
        at_send_map.append(_description(db2_probe_conn, "03"))
        original_put(item)

    monkeypatch.setattr(channel, "put", probing_put)

    terminal.press(_PF5)

    assert at_send_map == [("CREDIT BALANCE", 50)]


# ── Step 3: admin 6, insert and the -532 delete ─────────────────────────────


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_six_inserts_a_new_transaction_type(terminal, db2_probe_conn):
    """Verified by execution, and the direct proof of Task 8's ``+100`` fix.

    COTRTUPC has no "add" branch of its own: 9600-WRITE-PROCESSING always
    issues the UPDATE first (1544-1548) and only reaches 9700-INSERT-RECORD
    from ``WHEN SQLCODE = +100`` at 1558-1560. Before Task 8,
    ``resolve_dml_sqlcode`` reported 0 for a DML statement that matched zero
    rows, so that branch could never fire: the UPDATE of the absent '08' looked
    successful, the EVALUATE took ``WHEN SQLCODE = ZERO``, SYNCPOINT committed
    nothing, and the table stayed at 7 rows with no '08' at all. Verified to
    fail that way by execution -- forcing ``squall.binding.resolve_dml_sqlcode``
    to return 0 for a zero-row result makes this test end at 7 rows (see
    task-11-report.md).
    """
    terminal.sign_on_to_admin_option("06")

    terminal.press(TRTYPCD="08")
    assert "No record found for this key in database" in terminal.text()

    terminal.press(_PF5)
    terminal.press(TRTYDSC="TEST TYPE")
    assert _shows_info_prompt(terminal, "Changes validated.Press F5 to save")
    assert _row_count(db2_probe_conn) == 7

    terminal.press(_PF5)
    assert _row_count(db2_probe_conn) == 8
    assert _description(db2_probe_conn, "08") == ("TEST TYPE", 50)


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_six_delete_reports_the_real_minus_532(terminal, db2_probe_conn):
    """Verified by execution. Every seeded transaction type has child rows in
    TRANSACTION_TYPE_CATEGORY and the FK is ON DELETE RESTRICT, so the DELETE
    at 1627-1630 gets a genuine Db2 -532, which COTRTUPC handles explicitly at
    1638-1649. This exercises a real negative SQLCODE end to end -- the backend
    reporting it, ``SQLERRM`` reaching the message, and the table unchanged.
    """
    terminal.sign_on_to_admin_option("06")

    terminal.press(TRTYPCD="03")
    assert terminal.value("TRTYDSC") == "CREDIT"

    terminal.press(_PF4)
    assert _shows_info_prompt(terminal, "Delete this record ? Press F4 to confirm")

    terminal.press(_PF4)
    assert "Please delete associated child records first" in terminal.text()
    assert "-532" in terminal.text()
    assert _row_count(db2_probe_conn) == 7
    assert _description(db2_probe_conn, "03") == ("CREDIT", 6)


# ── Step 4: admin 5, list / page / filter ───────────────────────────────────


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_lists_every_seeded_type_on_one_page(terminal):
    """Verified by execution. Seven seed rows fill exactly one screen
    (WS-MAX-SCREEN-LINES = 7), read through the C-TR-TYPE-FORWARD cursor
    COTRTLIC declares in WORKING-STORAGE -- the DECLARE recovery Task 8 added.
    """
    terminal.sign_on_to_admin_option("05")

    assert terminal.value("PAGENO") == "1"
    shown = [terminal.value(f"TRTTYP{row}") for row in range(1, 8)]
    assert shown == ["01", "02", "03", "04", "05", "06", "07"]
    assert terminal.value("TRTYPD1") == "PURCHASE"
    assert terminal.value("TRTYPD7") == "ADJUSTMENT"


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_f7_on_the_first_page_says_so(terminal):
    """Verified by execution. 2500-SETUP-MESSAGE:1532-1535."""
    terminal.sign_on_to_admin_option("05")
    assert "No previous pages to display" not in terminal.text()

    terminal.press(_PF7)

    assert "No previous pages to display" in terminal.text()


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_needs_two_f8_presses_to_report_the_last_page(terminal):
    """Verified by execution. Pinned as written, because it is the program's
    behaviour and not a bug to fix: the first F8 falls into 2500-SETUP-MESSAGE's
    1541-1549 branch, which only SETs CA-LAST-PAGE-SHOWN; only the second press
    satisfies 1536-1540's ``CA-NEXT-PAGE-NOT-EXISTS AND CA-LAST-PAGE-SHOWN`` and
    produces the message.
    """
    terminal.sign_on_to_admin_option("05")

    terminal.press(_PF8)
    assert "No more pages to display" not in terminal.text()

    terminal.press(_PF8)
    assert "No more pages to display" in terminal.text()


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_type_filter_narrows_to_one_row(terminal, sql_spy):
    """Verified by execution. A valid 2-digit filter reaches 9100-CHECK-FILTERS'
    ``SELECT COUNT(1)`` (1803-1814) and then the cursor, leaving exactly the
    one matching row on screen."""
    terminal.sign_on_to_admin_option("05")

    sql_spy.clear()
    terminal.press(TRTYPE="03")

    assert terminal.value("TRTTYP1") == "03"
    assert terminal.value("TRTYPD1") == "CREDIT"
    assert terminal.value("TRTTYP2") == ""
    assert any("COUNT(1)" in statement for statement in sql_spy.statements)


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_rejects_a_non_numeric_type_filter_without_any_sql(
    terminal, sql_spy
):
    """Verified by execution. 1220-EDIT-TYPECD (1109-1123) rejects a
    non-numeric filter before 9100-CHECK-FILTERS is ever performed, so the turn
    must touch TRANSACTION_TYPE not at all -- the spy is the only way to assert
    the negative, since the screen alone cannot distinguish "no query" from
    "query whose result was discarded".

    The one statement that does run is COTRTLIC's own 9998-PRIMING-QUERY
    (performed at 684, before any branch decides anything): a
    ``SELECT 1 FROM SYSIBM.SYSDUMMY1`` connectivity check against no user
    table. Asserting on the table name rather than on an empty list keeps that
    distinction rather than blurring it.
    """
    terminal.sign_on_to_admin_option("05")

    sql_spy.clear()
    terminal.press(TRTYPE="AB")

    assert "TYPE CODE FILTER,IF SUPPLIED MUST BE A 2 DIGIT NUMBER" in terminal.text()
    assert [s for s in sql_spy.statements if "TRANSACTION_TYPE" in s] == []
    assert any("SYSDUMMY1" in statement for statement in sql_spy.statements)


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_updates_the_highlighted_row(terminal, db2_probe_conn):
    """Selecting row 5 with 'U' and overtyping its description highlights the
    row and asks for F10 (2500-SETUP-MESSAGE:1523-1531, no DML on that turn);
    F10 then runs 9200-UPDATE-RECORD's UPDATE (1846-1850) and SYNCPOINTs at
    1856, keying off the row's protected TRTTYP5 read back out of the map.

    Took two upstream fixes to reach green. red-dragon 10d2e1f8 fixed INSPECT
    TALLYING operand resolution (forge-twn), making the F10 branch reachable at
    all; d76d0380 then fixed the subscript being dropped on an intrinsic
    FUNCTION argument (forge-d79), without which 9200-UPDATE-RECORD wrote row
    01's description under row 05's key.
    """
    terminal.sign_on_to_admin_option("05")

    terminal.press(TRTSEL5="U", TRTYPD5="REFUND PROCESSED")
    assert _shows_info_prompt(terminal, "Update HIGHLIGHTED row. Press F10 to save")
    assert _description(db2_probe_conn, "05") == ("REFUND", 6)

    terminal.press(_PF10)
    assert _description(db2_probe_conn, "05") == ("REFUND PROCESSED", 50)


# ── Characterisation tests: CardDemo's own defects (Task 12) ───────────────
#
# The first two tests below are NOT specifications of desired behaviour. Each
# pins a real bug in vendor/carddemo (read-only here, never edited) so that if
# a future change to vendor/carddemo or to this Db2 tier accidentally "fixes"
# CardDemo's own defect, that is caught as a behaviour change rather than
# silently passing. A green run of either test is proof the defect is STILL
# PRESENT, not proof anything works correctly.
#
# The third is the opposite and says so in its own docstring: it drives Part E
# item 5's defective branch and pins the ONE thing keeping that defect from
# producing a false success, so that if that thing ever changes the false
# success shows up here as a failure instead of in front of an operator.


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_backward_fetch_exhaustion_misreports_end_of_data_as_a_db2_error(
    terminal, db2_probe_conn
):
    """CHARACTERISATION TEST for a CardDemo defect, not a spec of correct
    behaviour: COTRTLIC.cbl:1761-1790 (8100-READ-BACKWARDS)'s EVALUATE has a
    ``WHEN SQLCODE = ZERO`` branch and a ``WHEN OTHER`` branch, but no
    explicit ``WHEN SQLCODE = +100`` -- so exhausting the backward cursor
    before filling the page (the ordinary "you've reached the top of the
    list" case, which is exactly the same +100 the *forward* reader at
    COTRTLIC.cbl:1657-1673 already treats as expected end-of-data) falls into
    ``WHEN OTHER``, sets ``WS-DB2-ERROR``, and reports
    'Error on fetch Cursor C-TR-TYPE-BACKWARD SQLCODE:  100' to the operator
    (the message is built by 9999-FORMAT-DB2-MESSAGE, CSDB2RPY.cpy:74-84, and
    ``WS-DISP-SQLCODE`` is ``PIC ----9``, CSDB2RWY.cpy:22 -- five columns of
    floating-sign editing, so +100 renders '  100', never '+100').

    THIS IS CARDDEMO'S OWN DEFECT (Part E, item 4 of
    .superpowers/sdd/db2-epic/carddemo-db2-behaviour.md), not ours --
    vendor/carddemo is read-only here. Correct behaviour would treat +100 the
    same way 8000-READ-FORWARD's look-ahead does: stop the loop, keep the
    rows already fetched, and show them as the top of the list with no error
    at all -- and in particular ``ERRMSG`` would stay empty.

    Repro, verified by execution (a two-page repro is not enough: with only
    one deleted row before the current page, backward re-landing on page 1
    ALSO triggers 2500-SETUP-MESSAGE's ``WHEN CCARD-AID-PFK07 AND
    CA-FIRST-PAGE`` branch, which unconditionally overwrites ``WS-RETURN-MSG``
    with 'No previous pages to display' -- masking this defect's own message
    behind a DIFFERENT one). Seeding types '08'-'16' gives a third page, so
    paging back from page 3 to page 2 leaves ``CA-FIRST-PAGE`` false and
    nothing overwrites the message. Deleting '07'-'14' (and their FK
    children) leaves only '01'-'06' before page 3's first key ('15'), so the
    backward cursor exhausts on its 7th fetch -- a real +100, not a mock.
    """
    for code in range(8, 17):
        tr_type = f"{code:02d}"
        ibm_db.exec_immediate(
            db2_probe_conn,
            "INSERT INTO CARDDEMO.TRANSACTION_TYPE (TR_TYPE, TR_DESCRIPTION) "
            f"VALUES ('{tr_type}', 'TYPE{tr_type}')",
        )
        ibm_db.exec_immediate(
            db2_probe_conn,
            "INSERT INTO CARDDEMO.TRANSACTION_TYPE_CATEGORY "
            "(TRC_TYPE_CODE, TRC_TYPE_CATEGORY, TRC_CAT_DATA) "
            f"VALUES ('{tr_type}', '0001', 'CAT{tr_type}')",
        )

    terminal.sign_on_to_admin_option("05")
    terminal.press(_PF8)
    assert terminal.value("PAGENO") == "2"
    terminal.press(_PF8)
    assert terminal.value("PAGENO") == "3"
    assert terminal.value("TRTTYP1") == "15"

    for tr_type in ("07", "08", "09", "10", "11", "12", "13", "14"):
        ibm_db.exec_immediate(
            db2_probe_conn,
            "DELETE FROM CARDDEMO.TRANSACTION_TYPE_CATEGORY "
            f"WHERE TRC_TYPE_CODE = '{tr_type}'",
        )
        ibm_db.exec_immediate(
            db2_probe_conn,
            f"DELETE FROM CARDDEMO.TRANSACTION_TYPE WHERE TR_TYPE = '{tr_type}'",
        )

    terminal.press(_PF7)

    # WRONG: a mid-list backward-fetch exhaustion (+100) is reported to the
    # operator as a Db2 error rather than being treated as reaching the top
    # of the available rows.
    #
    # Asserted whole, not by prefix, because the tail is the other half of the
    # evidence. Everything up to 'SQLCODE:  100' is CardDemo's own STRING of
    # WS-DISP-SQLCODE, and everything after it is the DSNTIAC stub's reading
    # of the SQLCA the FETCH actually left behind. The two agree: Db2 really
    # did return +100, which is end-of-data, and 8100-READ-BACKWARDS still
    # routed it to WHEN OTHER. The stub's text is trailing-truncated by
    # ERRMSG's own field width ('+10'), which is the screen's doing, not the
    # stub's -- WS-LONG-MSG holds the full '+100'.
    assert terminal.value("PAGENO") == "2"
    assert terminal.value("ERRMSG") == (
        "Error on fetch Cursor C-TR-TYPE-BACKWARD SQLCODE:  100 " "DSNTIAC: SQLCODE=+10"
    )


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_six_insert_failure_reports_the_update_s_stale_sqlcode(
    terminal, db2_probe_conn, monkeypatch
):
    """CHARACTERISATION TEST for a CardDemo defect, not a spec of correct
    behaviour: COTRTUPC.cbl:1596-1618 (9700-INSERT-RECORD)'s ``EVALUATE TRUE
    WHEN SQLCODE = ZERO ... WHEN OTHER`` branches correctly on the FRESH
    ``SQLCODE`` special register left by the INSERT itself, but the message
    it builds on a failure STRINGs ``WS-DISP-SQLCODE`` -- a copy made by
    9600-WRITE-PROCESSING's preceding UPDATE (COTRTUPC.cbl:1553) and never
    refreshed after the INSERT runs. So when the INSERT itself fails, the
    operator is told the UPDATE's SQLCODE (always +100 on this path -- that
    is exactly why 9700-INSERT-RECORD was reached at all), not the INSERT's
    real one.

    THIS IS CARDDEMO'S OWN DEFECT (Part E, item 2 of
    .superpowers/sdd/db2-epic/carddemo-db2-behaviour.md), not ours --
    vendor/carddemo is read-only here. Correct behaviour would refresh
    ``WS-DISP-SQLCODE`` from ``SQLCODE`` right after the INSERT (as
    9600-WRITE-PROCESSING and 9800-DELETE-PROCESSING both already do for
    their own statements) and report the INSERT's real failure code.

    (An earlier round of this file chose item 2 over Part E item 5 on the
    false premise that PF10 is gated on ``CA-DELETE-REQUESTED``. It is not:
    COTRTLIC.cbl:580-581 and 667-668 are disjunctions. Item 5 now has its own
    test -- ``test_admin_five_delete_failure_after_an_update_selection`` --
    which drives the branch and shows why the false success still cannot be
    observed. This test stands on its own merits, not as a substitute.)

    Repro: a genuine Db2 duplicate-key error, not a mocked SQLCODE. Add type
    '09' (absent, so 9100-GET-TRANSACTION-TYPE's SELECT and
    9600-WRITE-PROCESSING's UPDATE both correctly see 0 rows -- the real
    +100 that reaches 9700-INSERT-RECORD on every successful add, see
    ``test_admin_six_inserts_a_new_transaction_type``). A hook on
    ``Db2Backend.execute`` inserts '09' on a separate connection, committed,
    the instant it sees the program's own INSERT statement text but before
    calling through to it -- so the program's INSERT collides with a row
    that did not exist when it decided to take this branch, and Db2 itself
    returns the real -803.
    """
    raced = False
    original_execute = Db2Backend.execute
    # ``\b`` after the table name is load-bearing: a bare substring test would
    # also match an INSERT into TRANSACTION_TYPE_CATEGORY, of which COTRTUPC
    # has none today (its one INSERT is at COTRTUPC.cbl:1598) but might.
    the_programs_insert = re.compile(r"INSERT\s+INTO\s+CARDDEMO\.TRANSACTION_TYPE\b")

    def race_the_insert(backend, sql, params):
        nonlocal raced
        if not raced and the_programs_insert.search(sql):
            raced = True
            ibm_db.exec_immediate(
                db2_probe_conn,
                "INSERT INTO CARDDEMO.TRANSACTION_TYPE (TR_TYPE, TR_DESCRIPTION) "
                "VALUES ('09', 'RACED IN FROM UNDER THE TASK')",
            )
        return original_execute(backend, sql, params)

    monkeypatch.setattr(Db2Backend, "execute", race_the_insert)

    terminal.sign_on_to_admin_option("06")

    terminal.press(TRTYPCD="09")
    assert "No record found for this key in database" in terminal.text()

    terminal.press(_PF5)
    terminal.press(TRTYDSC="RACED TYPE")
    assert _shows_info_prompt(terminal, "Changes validated.Press F5 to save")

    terminal.press(_PF5)

    # WRONG: the INSERT genuinely failed with a real Db2 -803 (duplicate
    # key), but the operator is told SQLCODE +100 -- the earlier UPDATE's
    # code, never refreshed after the INSERT that actually failed.
    assert raced
    assert "Error inserting record into: TRANSACTION_TYPE Table. SQLCODE:  100" in (
        terminal.value("ERRMSG")
    )
    assert _description(db2_probe_conn, "09") == ("RACED IN FROM UNDER THE TASK", 28)


@pytest.mark.usefixtures("carddemo_db2_schema")
def test_admin_five_delete_failure_after_an_update_selection(terminal, db2_probe_conn):
    """NOT a characterisation test -- the inverse. This drives Part E item 5's
    defective branch (9300-DELETE-RECORD's ``WHEN OTHER`` at
    COTRTLIC.cbl:1926-1934, which sets no ``WS-CA-DELETE-FLAG``) and asserts
    the CORRECT behaviour it nonetheless produces, pinning the one fact that
    saves it.

    The branch IS live-reachable, contrary to an earlier round of this file.
    PF10 is admitted by COTRTLIC.cbl:580-581 on ``CA-DELETE-REQUESTED`` OR
    ``CA-UPDATE-REQUESTED`` -- a disjunction, not a delete-only gate, repeated
    at 667-668 -- and those are separate bytes (COTRTLIC.cbl:411-418). So:
    select a row with 'U' and press ENTER (dispatch at COTRTLIC.cbl:838), and
    2300-SCREEN-ARRAY-INIT:1410 sets ONLY ``CA-UPDATE-REQUESTED``; overtype
    that same field to 'D' and press PF10, and 1210-EDIT-ARRAY (reached every
    turn from 1000-RECEIVE-MAP:923) recomputes ``WS-DELETES-REQUESTED`` = 1
    while ``FLG-ROW-SELECTION-CHANGED-NO`` still holds -- 1210-EDIT-ARRAY:1042
    compares only ``I-SELECTED``, the row index, never the action letter -- so
    667-671 CONTINUEs and COTRTLIC.cbl:810 runs 9300-DELETE-RECORD with a
    delete flag this session never wrote.

    What saves it is the flag's UNSET value, not its reachability. Every write
    that leaves ``WS-CA-DELETE-FLAG`` unset is an INITIALIZE (here
    COTRTLIC.cbl:548, on entry from the menu), and COBOL's INITIALIZE stores
    SPACES into a PIC X -- whereas ``CA-DELETE-SUCCEEDED`` is an 88 on
    LOW-VALUES. So COTRTLIC.cbl:817 is FALSE, FLG-DELETED-NO is set, and the
    operator is correctly told the delete failed. The only statement that ever
    stores LOW-VALUES is ``SET CA-DELETE-SUCCEEDED`` after a SUCCESSFUL delete
    (COTRTLIC.cbl:1910), and COTRTLIC.cbl:826-833 INITIALIZEs the commarea back
    to spaces inside that same turn, so LOW-VALUES cannot survive into a turn
    where ``WHEN OTHER`` could run.

    Both halves are asserted, because ``ERRMSG`` alone cannot tell them apart:
    ``WHEN OTHER`` builds the failure message into ``WS-RETURN-MSG``
    regardless, and 2500-SETUP-MESSAGE:1557 moves it to the screen either way.
    It is INFOMSG that discriminates -- on the false-success path
    2500-SETUP-MESSAGE:1507-1508's ``WHEN FLG-DELETED-YES`` would put
    'HIGHLIGHTED row deleted.Hit Enter to continue' in front of the operator.

    Failure is a genuine Db2 +100, not a mocked SQLCODE: row '05' (and its FK
    children) is deleted on the probe connection between the two turns, so the
    program's own DELETE at COTRTLIC.cbl:1900-1903 matches nothing.
    """
    terminal.sign_on_to_admin_option("05")

    terminal.press(TRTSEL5="U")
    assert _shows_info_prompt(terminal, "Update HIGHLIGHTED row. Press F10 to save")

    ibm_db.exec_immediate(
        db2_probe_conn,
        "DELETE FROM CARDDEMO.TRANSACTION_TYPE_CATEGORY WHERE TRC_TYPE_CODE = '05'",
    )
    ibm_db.exec_immediate(
        db2_probe_conn,
        "DELETE FROM CARDDEMO.TRANSACTION_TYPE WHERE TR_TYPE = '05'",
    )

    terminal.press(_PF10, TRTSEL5="D")

    # Asserted whole, not by prefix: the DSNTIAC tail is what proves the
    # failure reaching the operator is the DELETE's own, freshly read from the
    # SQLCA rather than inherited. 'SQLCODE:  100' is CardDemo's
    # WS-DISP-SQLCODE and 'DSNTIAC: SQLCODE=+100' is the stub's independent
    # reading of the same SQLCA -- they agree, so the +100 is genuinely this
    # DELETE matching no rows.
    assert terminal.value("ERRMSG") == (
        "Delete failed with message: SQLCODE:  100 DSNTIAC: SQLCODE=+100"
    )
    assert not _shows_info_prompt(
        terminal, "HIGHLIGHTED row deleted.Hit Enter to continue"
    )
    assert _row_count(db2_probe_conn) == 6
