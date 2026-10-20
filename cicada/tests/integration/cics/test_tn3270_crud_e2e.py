"""Wire CRUD tests: CardDemo account update (COACTUPC) and card update
(COCRDUPC), each driven through a real s3270 emulator, each proving the
underlying VSAM record actually changed.

Both flows are the standard CardDemo find -> edit -> validate -> PF5-commit
shape: an ENTER that shows current values, an ENTER that validates the edit
("Changes validated.Press F5 to save"), and a PF5 that commits
("Changes committed to database"). PF5 is only honoured after the validating
ENTER (COACTUPC.cbl:898-915,:2600-2603; COCRDUPC.cbl mirrors this), so all
three turns are driven in order.

On the wire, every editable field the program force-sets (COACTUPC/COCRDUPC's
own ATTRB overrides, e.g. DFHBMFSE/DFHBMPRF) survives a turn untyped; fields
without a force override do not, and are retyped here exactly as a real
terminal would. Screen text alone is not proof: after PF5, the changed bytes
are read back through the live VsamEngine, and the record is re-displayed over
the wire -- a plain ENTER drops each program back into its own "search again"
prompt, and re-entering the same key re-fetches and re-renders the committed
record -- to confirm the new value renders too. A PF3 back to the menu is
exercised once (account update, after the redisplay) to prove SYNCPOINT's
no-op does not hang or error post-commit; PF3-then-reselect now works
(forge-1zu.6, fixed) but this module still does not drive it -- see
forge-1zu.6's follow-up bead for simplifying the "search again" workaround
above in light of that fix.

Admin user CRUD (COUSR01C/02C/03C, admin menu options 2/3/4) follows the same
shape but through a different sign-on path: an ADMIN-type USRSEC row
(COSGN00C.cbl:227-237) routes to COADM01C, the admin menu, instead of
COMEN01C. COUSR2A/COUSR3A's I- and O-map areas are the same physical storage
(COUSR2AO/COUSR3AO REDEFINES COUSR2AI/COUSR3AI in cpy-bms/COUSR02.CPY and
COUSR03.CPY), so a field RECEIVEd into FNAMEI etc. is already present at
FNAMEO etc. without any MOVE the program would need to make -- the post-PF5
redisplay already shows the committed value with no extra turn, and a further
turn (re-entering the id, or -- for delete -- retyping it after the
commit clears it) proves the key still exists post-commit (delete: proves it
doesn't) -- the VSAM read is what proves the value in every case.

The update test retypes every editable field on its PF5 turn, not just the
one under test: COUSR02C's re-entry path never re-initialises its map area
between RECEIVE and SEND, so an untyped FSET field's MDT is genuinely lost on
this program (forge-1zu.8, closed as faithful BMS A/F-byte-overlap behaviour,
not a cicada defect) -- unlike COACTUPC/COCRDUPC, this flow does not exercise
fields surviving a turn untyped.
"""

from __future__ import annotations

from cics.vsam.record_read import RecordRead
from cics.vsam.no_record import NoRecord
import os
from contextlib import closing
from pathlib import Path

import pytest

from interpreter.cobol.features import CobolFeature
from interpreter.cobol.zoned_decimal import decode_zoned
from tests.covers import covers
from tests.integration.cics.tn3270_helpers import (
    S3270,
    carddemo_package,
    records,
    served_session,
)
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401

pytestmark = [pytest.mark.carddemo_e2e, pytest.mark.tn3270_e2e]

_PROGRAMS = {
    "CC00": "COSGN00C",
    "CM00": "COMEN01C",
    "CA00": "COADM01C",
    "CAUP": "COACTUPC",
    "CCUP": "COCRDUPC",
    "CT02": "COTRN02C",
    "CB00": "COBIL00C",
    "CU01": "COUSR01C",
    "CU02": "COUSR02C",
    "CU03": "COUSR03C",
}


def _package(
    tmp_path: Path,
    bridge_jar: str,
    transids: tuple[str, ...],
    callees: tuple[str, ...] = (),
) -> Path:
    """A package linking only the programs this flow's transactions run, plus
    the programs they CALL -- compiling all of CardDemo for every test is
    avoidable slowness."""
    return carddemo_package(
        tmp_path, bridge_jar, (*(_PROGRAMS[t] for t in transids), *callees)
    )


def _ebcdic_records(name: str, length: int) -> list[bytes]:
    return records(Path(os.environ["CARDDEMO_HOME"]) / "data/EBCDIC", name, length)


def _signon(terminal: S3270, port: int) -> None:
    terminal.connect(port)
    assert "User ID" in terminal.screen()
    terminal.run('String("USER0001")')
    # An 8-character user id fills USERID exactly, so the 3270 auto-skip already
    # leaves the cursor in PASSWD; tabbing here would overshoot to the one-byte
    # unprotected stopper field COSGN00 places after the password.
    terminal.run('String("PASSWORD")')
    assert "Main Menu" in terminal.enter()


def _select(terminal: S3270, option: str, expect: str) -> None:
    terminal.run(f'String("{option}")')
    assert expect in terminal.enter()


def _field(screen: str, row: int, col: int, length: int) -> str:
    """The exact content of a BMS field: ``row``/``col`` are the map's
    1-origin POS coordinates; data starts one column after the attribute
    byte BMS allocates at ``col``, i.e. at 0-origin index ``col`` on
    ``row - 1``. A bare substring check can pass on stray leftover text from
    an earlier turn; slicing the exact field width confirms this is what the
    field itself now holds."""
    return screen.splitlines()[row - 1][col : col + length]


# ---------------------------------------------------------------------------
# Account update (COACTUPC, menu option 02)
# ---------------------------------------------------------------------------

# CVACT03Y CARDXREF: CARD-NUM X(16)@0, CUST-ID 9(9)@16, ACCT-ID 9(11)@25.
# CVCUS01Y CUSTDATA: CUST-ID 9(9)@0, FIRST-NAME X(25)@9, SSN 9(9)@279,
# FICO-SCORE 9(3)@329. CardDemo's synthetic data sprinkles values that fail
# COACTUPC's own field edits (SSN ranges, US state/zip combos) on otherwise
# unrelated accounts; account 00000000020 (customer 000000020) passes SSN and
# FICO edits already, and its state/zip are corrected here exactly as a real
# operator fixing a bad screen would, alongside the field under test.
_ACCT_ID = "00000000020"
_CUST_ID = "000000020"
_NEW_FIRST_NAME = "JANE"


def _custdat_first_name(engine) -> str:
    rec_read = engine.read("CUSTDAT", _CUST_ID.encode("cp037"))
    assert isinstance(rec_read, RecordRead), "customer vanished"
    rec = rec_read.record
    return bytes(rec[9:34]).decode("cp037").strip()


def _custdat_untouched(engine) -> tuple[str, str]:
    """CUST-SSN 9(9)@279 and CUST-FICO-CREDIT-SCORE 9(3)@329 (CVCUS01Y) --
    fields this flow's edit never touches, to prove the REWRITE didn't
    corrupt the rest of the 500-byte record."""
    rec_read = engine.read("CUSTDAT", _CUST_ID.encode("cp037"))
    assert isinstance(rec_read, RecordRead), "customer vanished"
    rec = rec_read.record
    b = bytes(rec)
    return b[279:288].decode("cp037"), b[329:332].decode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_account_update_rewrites_custdat(tmp_path, bridge_jar, carddemo_system):
    package = _package(tmp_path, bridge_jar, ("CC00", "CM00", "CAUP"))
    original_record = [
        r
        for r in _ebcdic_records("AWS.M2.CARDDEMO.CUSTDATA.PS", 500)
        if r[:9].decode("cp037") == _CUST_ID
    ][0]
    original_first_name = original_record[9:34].decode("cp037").strip()
    original_ssn = original_record[279:288].decode("cp037")
    original_fico = original_record[329:332].decode("cp037")
    assert original_first_name != _NEW_FIRST_NAME  # the edit must be a real change

    with served_session(package, carddemo_system) as served:
        with closing(S3270()) as terminal:
            _signon(terminal, served.port)
            _select(terminal, "02", "Update Account")

            # Turn 1: find the account -> current details render (CACTUPA).
            terminal.run(f'String("{_ACCT_ID}")')
            found = terminal.enter()
            assert _ACCT_ID in found
            assert original_first_name in found
            assert "Update account details presented above" in found

            # Turn 2: edit the customer first name (ACSFNAM; MoveCursor rows/
            # cols below are 0-origin, one less than the BMS map's 1-origin
            # POS=(15,1)) plus the state/zip this account's seed data would
            # otherwise fail validation on (ACSSTTE POS=(16,73), ACSZIPC
            # POS=(17,73)); every other visible field is force-set by
            # COACTUPC and survives untyped.
            terminal.run("MoveCursor(14,1)")
            terminal.run(f'String("{_NEW_FIRST_NAME.ljust(25)}")')
            terminal.run("MoveCursor(15,73)")
            terminal.run('String("NY")')
            terminal.run("MoveCursor(16,73)")
            terminal.run('String("10001")')
            validated = terminal.enter()
            assert _NEW_FIRST_NAME in validated
            assert "Changes validated.Press F5 to save" in validated

            # The validating ENTER only checks and re-displays; VSAM must
            # still hold the old value until PF5 actually REWRITEs it.
            assert _custdat_first_name(served.region.vsam_engine) == original_first_name

            # Turn 3: PF5 commits the REWRITE.
            committed = terminal.enter("PF(5)")
            assert "Changes committed to database" in committed

            assert _custdat_first_name(served.region.vsam_engine) == _NEW_FIRST_NAME
            committed_ssn, committed_fico = _custdat_untouched(
                served.region.vsam_engine
            )
            assert committed_ssn == original_ssn
            assert committed_fico == original_fico

            # A plain ENTER after the commit re-prompts for an account id
            # (COACTUPC's own "search again" cycle); re-fetching the SAME
            # account over the wire shows the committed name, not just what
            # this test itself typed into a field.
            assert "Enter or update id" in terminal.enter()
            terminal.run(f'String("{_ACCT_ID}")')
            redisplayed = terminal.enter()
            assert _field(redisplayed, 5, 38, 11).strip() == _ACCT_ID
            assert _field(redisplayed, 15, 1, 25).strip() == _NEW_FIRST_NAME

            # PF3 exits back to the menu -- SYNCPOINT is a no-op (Task A), so
            # this must not hang or error after a commit.
            assert "Main Menu" in terminal.enter("PF(3)")


# ---------------------------------------------------------------------------
# Card update (COCRDUPC, menu option 05)
# ---------------------------------------------------------------------------

# CVACT02Y CARDDATA: CARD-NUM X(16)@0, ACCT-ID 9(11)@16, CVV 9(3)@27,
# EMBOSSED-NAME X(50)@30, EXPIRY X(10)@80, STATUS X(1)@90.
_CARD_ACCT_ID = "00000000050"
_CARD_NUM = "0500024453765740"
_NEW_EMBOSSED_NAME = "JANE VON"


def _carddat_embossed_name(engine) -> str:
    rec_read = engine.read("CARDDAT", _CARD_NUM.encode("cp037"))
    assert isinstance(rec_read, RecordRead), "card vanished"
    rec = rec_read.record
    return bytes(rec[30:80]).decode("cp037").strip()


def _carddat_acct_id(engine) -> str:
    """CARD-ACCT-ID 9(11)@16 (CVACT02Y) -- the one field this flow's screen
    never edits AND COCRDUPC's own 9200-WRITE-PROCESSING carries forward
    intact. CARD-CVV-CD@27 and the trailing FILLER@91 are NOT safe
    untouched-field candidates here: COCRDUPC INITIALIZEs the whole
    CARD-UPDATE-RECORD working copy before REWRITE but never re-populates
    CCUP-NEW-CVV-CD from the read record (CCUP-NEW-DETAILS has no CVV input
    field on this screen), so every card update genuinely zeroes CARD-CVV-CD
    and blanks FILLER in VSAM -- confirmed live (747 -> 000); that is real
    COCRDUPC behaviour, not a cicada REWRITE-offset bug."""
    rec_read = engine.read("CARDDAT", _CARD_NUM.encode("cp037"))
    assert isinstance(rec_read, RecordRead), "card vanished"
    rec = rec_read.record
    return bytes(rec[16:27]).decode("cp037")


@covers(CobolFeature.EXEC_CICS)
def test_card_update_rewrites_carddat(tmp_path, bridge_jar, carddemo_system):
    package = _package(tmp_path, bridge_jar, ("CC00", "CM00", "CCUP"))
    original_record = [
        r
        for r in _ebcdic_records("AWS.M2.CARDDEMO.CARDDATA.PS", 150)
        if r[:16].decode("cp037") == _CARD_NUM
    ][0]
    original_embossed_name = original_record[30:80].decode("cp037").strip()
    original_acct_id_field = original_record[16:27].decode("cp037")
    assert original_embossed_name.upper() != _NEW_EMBOSSED_NAME  # a real change

    with served_session(package, carddemo_system) as served:
        with closing(S3270()) as terminal:
            _signon(terminal, served.port)
            _select(terminal, "05", "Please enter Account and Card Number")

            # Turn 1: find the card -> current details render (CCRDUPA). A
            # full-width ACCTSID auto-advances the cursor straight into
            # CARDSID (standard 3270 field-fill behaviour) -- no Tab() needed.
            terminal.run(f'String("{_CARD_ACCT_ID}")')
            terminal.run(f'String("{_CARD_NUM}")')
            found = terminal.enter()
            assert original_embossed_name.upper() in found
            assert "Details of selected card shown above" in found

            # Turn 2: edit the embossed name (CRDNAME POS=(11,25); MoveCursor
            # rows/cols below are 0-origin, one less than the BMS map's
            # 1-origin POS), plus the status (CRDSTCD POS=(13,25)) and expiry
            # (EXPMON/EXPYEAR POS=(15,25)/(15,30)) this card's fields require
            # every turn.
            terminal.run("MoveCursor(10,25)")
            terminal.run(f'String("{_NEW_EMBOSSED_NAME.ljust(50)}")')
            terminal.run("MoveCursor(12,25)")
            terminal.run('String("Y")')
            terminal.run("MoveCursor(14,25)")
            terminal.run('String("12")')
            terminal.run("MoveCursor(14,30)")
            terminal.run('String("2099")')
            validated = terminal.enter()
            assert _NEW_EMBOSSED_NAME in validated
            assert "Changes validated.Press F5 to save" in validated

            # The validating ENTER only checks and re-displays; VSAM must
            # still hold the old value until PF5 actually REWRITEs it.
            assert (
                _carddat_embossed_name(served.region.vsam_engine)
                == original_embossed_name
            )

            # Turn 3: PF5 commits the REWRITE.
            committed = terminal.enter("PF(5)")
            assert "Changes committed to database" in committed

            assert (
                _carddat_embossed_name(served.region.vsam_engine) == _NEW_EMBOSSED_NAME
            )
            assert _carddat_acct_id(served.region.vsam_engine) == original_acct_id_field

            # A plain ENTER after the commit re-prompts for account/card
            # (COCRDUPC's own "search again" cycle); re-fetching the SAME card
            # over the wire shows the committed embossed name, not just what
            # this test itself typed into a field.
            assert "Please enter Account and Card Number" in terminal.enter()
            terminal.run(f'String("{_CARD_ACCT_ID}")')
            terminal.run(f'String("{_CARD_NUM}")')
            redisplayed = terminal.enter()
            assert _field(redisplayed, 7, 45, 11).strip() == _CARD_ACCT_ID
            assert _field(redisplayed, 8, 45, 16).strip() == _CARD_NUM
            assert _field(redisplayed, 11, 25, 50).strip() == _NEW_EMBOSSED_NAME


# ---------------------------------------------------------------------------
# Add transaction (COTRN02C, menu option 08) and bill pay (COBIL00C, menu
# option 10) both WRITE a TRANSACT record whose id neither test types -- each
# server-mints it via STARTBR(HIGH-VALUES) + READPREV over the seeded
# DALYTRAN.PS + 1 (COTRN02C.cbl:444-451; COBIL00C.cbl mirrors this). Both
# derive their account (and, for add-transaction, card) from CARDXREF.PS
# (CVACT03Y: CARD-NUM X(16)@0, ACCT-ID 9(11)@25) rather than a literal, and
# every field either program's own BMS map marks ATTRB=FSET -- effectively
# every editable field on both screens -- survives a turn untyped exactly as
# the account/card update tests above rely on.
# ---------------------------------------------------------------------------


def _cxacaix_pairs() -> list[tuple[str, str]]:
    return [
        (r[0:16].decode("cp037"), r[25:36].decode("cp037"))
        for r in _ebcdic_records("AWS.M2.CARDDEMO.CARDXREF.PS", 50)
    ]


def _next_transaction_id() -> str:
    ids = {
        int(r[:16].decode("cp037"))
        for r in _ebcdic_records("AWS.M2.CARDDEMO.DALYTRAN.PS", 350)
    }
    return str(max(ids) + 1).zfill(16)


def _transact_fields(engine, tran_id: str) -> dict[str, str]:
    """CVTRA05Y TRAN-RECORD field slices (matches the headless regression
    test's own offsets: id, type, category, source, description, merchant id,
    merchant name, card number)."""
    rec_read = engine.read("TRANSACT", tran_id.encode("cp037"))
    assert isinstance(rec_read, RecordRead), f"transaction {tran_id} was not written"
    rec = rec_read.record
    b = bytes(rec)
    return {
        "id": b[0:16].decode("cp037").strip(),
        "type": b[16:18].decode("cp037").strip(),
        "category": b[18:22].decode("cp037").strip(),
        "source": b[22:32].decode("cp037").strip(),
        "description": b[32:132].decode("cp037").strip(),
        "merchant_id": b[143:152].decode("cp037").strip(),
        "merchant_name": b[152:202].decode("cp037").strip(),
        "card_num": b[262:278].decode("cp037").strip(),
    }


@covers(CobolFeature.EXEC_CICS)
def test_add_transaction_writes_transact(tmp_path, bridge_jar, carddemo_system):
    package = _package(
        tmp_path,
        bridge_jar,
        ("CC00", "CM00", "CT02"),
        ("CSUTLDTC", "CEEDAYS"),
    )
    card_num, acct_id = _cxacaix_pairs()[0]
    new_tran_id = _next_transaction_id()

    with served_session(package, carddemo_system) as served:
        # Pre-condition: the id STARTBR/READPREV will mint does not exist yet.
        assert isinstance(
            served.region.vsam_engine.read("TRANSACT", new_tran_id.encode("cp037")),
            NoRecord,
        )

        with closing(S3270()) as terminal:
            _signon(terminal, served.port)
            _select(terminal, "08", "Add Transaction")

            # Turn 1: fill every field (COTRN2A; MoveCursor rows/cols below are
            # 0-origin, one less than the BMS map's 1-origin POS row, same
            # col) with CONFIRM left blank -> validates against the account
            # xref, normalises the amount, and prompts to confirm
            # (COTRN02C.cbl:169-178).
            terminal.run("MoveCursor(5,21)")
            terminal.run(f'String("{acct_id}")')
            terminal.run("MoveCursor(5,55)")
            terminal.run(f'String("{card_num}")')
            terminal.run("MoveCursor(9,15)")
            terminal.run('String("01")')
            terminal.run("MoveCursor(9,36)")
            terminal.run('String("0001")')
            terminal.run("MoveCursor(9,54)")
            terminal.run('String("POS")')
            terminal.run("MoveCursor(11,19)")
            terminal.run('String("TEST TRANSACTION")')
            terminal.run("MoveCursor(13,14)")
            terminal.run('String("+00000100.00")')
            terminal.run("MoveCursor(13,42)")
            terminal.run('String("2024-01-01")')
            terminal.run("MoveCursor(13,68)")
            terminal.run('String("2024-01-01")')
            terminal.run("MoveCursor(15,19)")
            terminal.run('String("000000001")')
            terminal.run("MoveCursor(15,48)")
            terminal.run('String("TEST MERCHANT")')
            terminal.run("MoveCursor(17,21)")
            terminal.run('String("CHICAGO")')
            terminal.run("MoveCursor(17,67)")
            terminal.run('String("60601")')
            validated = terminal.enter()
            assert "confirm to add this transaction" in validated.lower()
            assert _field(validated, 14, 14, 12).strip() == "+00000100.00"

            # The confirm prompt only validates and re-displays; the WRITE
            # must not have happened until CONFIRM='Y' actually commits.
            assert isinstance(
                served.region.vsam_engine.read("TRANSACT", new_tran_id.encode("cp037")),
                NoRecord,
            )

            # Turn 2: CONFIRM='Y' -- every other field above is BMS ATTRB=FSET
            # so it survives untyped; the success message names the
            # server-minted id, not anything this test typed.
            terminal.run("MoveCursor(20,63)")
            terminal.run('String("Y")')
            committed = terminal.enter()
            assert "transaction added successfully" in committed.lower()
            assert new_tran_id in committed
            # The PF5 redisplay below rests on INITIALIZE-ALL-FIELDS having
            # cleared the map on commit; check that premise directly.
            assert _field(committed, 12, 19, 60).strip() == ""

            written = _transact_fields(served.region.vsam_engine, new_tran_id)
            assert written["card_num"] == card_num
            assert written["type"] == "01"
            assert written["category"] == "0001"
            assert written["source"] == "POS"
            assert written["description"] == "TEST TRANSACTION"
            assert written["merchant_id"] == "000000001"
            assert written["merchant_name"] == "TEST MERCHANT"

            # PF5 "copy last tran data" re-reads the just-written record over
            # the wire -- the numerically-highest TRAN-ID again, via the same
            # STARTBR/READPREV (COTRN02C.cbl:472-491) -- once an account is
            # retyped (ACTIDIN was cleared by the commit's own
            # INITIALIZE-ALL-FIELDS); the rendered fields are proof the server
            # read them back, not just what this test typed earlier.
            terminal.run("MoveCursor(5,21)")
            terminal.run(f'String("{acct_id}")')
            copied = terminal.enter("PF(5)")
            assert _field(copied, 6, 55, 16).strip() == card_num
            assert _field(copied, 12, 19, 60).strip() == "TEST TRANSACTION"
            assert _field(copied, 16, 48, 30).strip() == "TEST MERCHANT"


def _acctdat_balance(engine, acct_id: str) -> float:
    rec_read = engine.read("ACCTDAT", acct_id.encode("cp037"))
    assert isinstance(rec_read, RecordRead), "account vanished"
    rec = rec_read.record
    return decode_zoned(bytes(rec[12:24]), decimal_digits=2)


def _acctdat_balance_from_seed(acct_id: str) -> float:
    """The account's pre-run balance straight out of the vendored ACCTDATA.PS
    (CVACT01Y: ACCT-ID 9(11)@0, ACCT-CURR-BAL S9(10)V99@12)."""
    matches = [
        r
        for r in _ebcdic_records("AWS.M2.CARDDEMO.ACCTDATA.PS", 300)
        if r[0:11].decode("cp037") == acct_id
    ]
    return decode_zoned(bytes(matches[0][12:24]), decimal_digits=2)


def _edited_balance(balance: float) -> str:
    """WS-CURR-BAL's edit picture, PIC +9999999999.99 (COBIL00C.cbl:53)."""
    cents = round(balance * 100)
    return f"+{cents // 100:010d}.{cents % 100:02d}"


@covers(CobolFeature.EXEC_CICS)
def test_bill_pay_rewrites_acctdat_and_writes_transact(
    tmp_path, bridge_jar, carddemo_system
):
    package = _package(tmp_path, bridge_jar, ("CC00", "CM00", "CB00"))
    card_num, acct_id = _cxacaix_pairs()[1]
    new_tran_id = _next_transaction_id()

    original_balance = _acctdat_balance_from_seed(acct_id)
    assert original_balance > 0  # COBIL00C refuses to pay a zero balance
    original_edited = _edited_balance(original_balance)
    zero_edited = _edited_balance(0.0)
    assert original_edited != zero_edited  # the payment must be a real change

    with served_session(package, carddemo_system) as served:
        assert isinstance(
            served.region.vsam_engine.read("TRANSACT", new_tran_id.encode("cp037")),
            NoRecord,
        )

        with closing(S3270()) as terminal:
            _signon(terminal, served.port)
            _select(terminal, "10", "Bill Payment")

            # Turn 1: enter the account id, CONFIRM blank (COBIL0A;
            # ACTIDIN's IC attribute already parks the cursor there) -> READ
            # ACCTDAT renders the current balance and prompts to confirm
            # (COBIL00C.cbl:237).
            terminal.run(f'String("{acct_id}")')
            shown = terminal.enter()
            assert _field(shown, 11, 32, 14).strip() == original_edited
            assert "confirm to make a bill payment" in shown.lower()

            # The confirm prompt only displays the balance; the REWRITE to
            # zero must not have happened until CONFIRM='Y' actually commits.
            assert (
                _acctdat_balance(served.region.vsam_engine, acct_id) == original_balance
            )

            # Turn 2: CONFIRM='Y' -- ACTIDIN is BMS ATTRB=FSET so it survives
            # untyped -- REWRITEs ACCTDAT to zero and WRITEs the payment
            # transaction (COBIL00C.cbl:379,:512,:527).
            terminal.run("MoveCursor(14,60)")
            terminal.run('String("Y")')
            paid = terminal.enter()
            assert "payment successful" in paid.lower()
            assert new_tran_id in paid

            assert _acctdat_balance(served.region.vsam_engine, acct_id) == 0.0
            tran = _transact_fields(served.region.vsam_engine, new_tran_id)
            assert tran["card_num"] == card_num

            # Turn 3: ACTIDIN was cleared by the commit's own
            # INITIALIZE-ALL-FIELDS, so retype it -- the re-displayed balance
            # is READ fresh from ACCTDAT, not merely what this test typed.
            terminal.run(f'String("{acct_id}")')
            redisplayed = terminal.enter()
            assert _field(redisplayed, 11, 32, 14).strip() == zero_edited


# ---------------------------------------------------------------------------
# Admin user add/update/delete (COUSR01C/02C/03C, admin menu options 2/3/4).
# ADMIN-type sign-on (COSGN00C.cbl:227-237) routes to COADM01C, not COMEN01C.
# CSUSR01Y SEC-USER-DATA (80 bytes): SEC-USR-ID X(8)@0, SEC-USR-FNAME X(20)@8,
# SEC-USR-LNAME X(20)@28, SEC-USR-PWD X(8)@48, SEC-USR-TYPE X(1)@56.
# ---------------------------------------------------------------------------

_USRSEC_NAME = "AWS.M2.CARDDEMO.USRSEC.PS"
_USRSEC_LEN = 80


def _usrsec_records() -> list[bytes]:
    return _ebcdic_records(_USRSEC_NAME, _USRSEC_LEN)


def _usrsec_ids() -> list[str]:
    return [r[0:8].decode("cp037") for r in _usrsec_records()]


def _next_admin_id() -> str:
    """The vendored seed holds ADMIN001..ADMIN005; the next id in the same
    series is guaranteed absent without hard-coding an arbitrary literal."""
    nums = [int(uid[5:8]) for uid in _usrsec_ids() if uid.startswith("ADMIN")]
    return f"ADMIN{max(nums) + 1:03d}"


def _usrsec_fields(engine, user_id: str) -> dict[str, str]:
    rec_read = engine.read("USRSEC", user_id.encode("cp037"))
    assert isinstance(rec_read, RecordRead), f"user {user_id} vanished"
    rec = rec_read.record
    b = bytes(rec)
    return {
        "fname": b[8:28].decode("cp037").strip(),
        "lname": b[28:48].decode("cp037").strip(),
        "pwd": b[48:56].decode("cp037").strip(),
        "type": b[56:57].decode("cp037").strip(),
    }


def _admin_signon(terminal: S3270, port: int, admin_id: str = "ADMIN001") -> None:
    terminal.connect(port)
    assert "User ID" in terminal.screen()
    terminal.run(f'String("{admin_id}")')
    terminal.run('String("PASSWORD")')
    assert "Admin Menu" in terminal.enter()


@covers(CobolFeature.EXEC_CICS)
def test_admin_add_user_writes_usrsec(tmp_path, bridge_jar, carddemo_system):
    package = _package(
        tmp_path,
        bridge_jar,
        ("CC00", "CA00", "CU01", "CU02"),
    )
    new_id = _next_admin_id()
    assert new_id not in _usrsec_ids()  # verified absent, not assumed
    new_fname, new_lname, new_pwd, new_type = "TESTFNAME", "TESTLNAME", "PASSWD01", "A"

    with served_session(package, carddemo_system) as served:
        assert isinstance(
            served.region.vsam_engine.read("USRSEC", new_id.encode("cp037")),
            NoRecord,
        )

        with closing(S3270()) as terminal:
            _admin_signon(terminal, served.port)
            _select(terminal, "02", "Add User")

            # Turn 1: fill every field (COUSR1A; MoveCursor rows/cols below
            # are 0-origin, one less than the BMS map's 1-origin POS row,
            # same col) -- a plain ENTER commits, no PF5 step for add
            # (COUSR01C.cbl:240, message at :257).
            terminal.run("MoveCursor(7,18)")
            terminal.run(f'String("{new_fname}")')
            terminal.run("MoveCursor(7,56)")
            terminal.run(f'String("{new_lname}")')
            terminal.run("MoveCursor(10,15)")
            terminal.run(f'String("{new_id}")')
            terminal.run("MoveCursor(10,55)")
            terminal.run(f'String("{new_pwd}")')
            terminal.run("MoveCursor(13,17)")
            terminal.run(f'String("{new_type}")')
            committed = terminal.enter()
            assert f"User {new_id} has been added" in committed

            written = _usrsec_fields(served.region.vsam_engine, new_id)
            assert written["fname"] == new_fname
            assert written["lname"] == new_lname
            assert (
                written["pwd"] == new_pwd
            )  # DRK field: proven in VSAM, never on screen
            assert written["type"] == new_type

            # Turn 2: PF3 back to the admin menu, then Update User (option
            # 03) re-reads the just-added USRSEC row over the wire --
            # COUSR2AI/COUSR2AO share storage (cpy-bms/COUSR02.CPY), so the
            # RECEIVEd id's fields render straight from the fresh READ, not
            # from anything this test typed into COUSR01C.
            assert "Admin Menu" in terminal.enter("PF(3)")
            _select(terminal, "03", "Update User")
            terminal.run("MoveCursor(5,21)")
            terminal.run(f'String("{new_id}")')
            redisplayed = terminal.enter()
            assert _field(redisplayed, 11, 18, 20).strip() == new_fname
            assert _field(redisplayed, 11, 56, 20).strip() == new_lname


@covers(CobolFeature.EXEC_CICS)
def test_admin_update_user_rewrites_usrsec(tmp_path, bridge_jar, carddemo_system):
    package = _package(tmp_path, bridge_jar, ("CC00", "CA00", "CU02"))
    update_id = "USER0002"
    assert update_id in _usrsec_ids()
    seeded = [r for r in _usrsec_records() if r[0:8].decode("cp037") == update_id][0]
    original_fname = seeded[8:28].decode("cp037").strip()
    original_lname = seeded[28:48].decode("cp037").strip()
    original_pwd = seeded[48:56].decode("cp037").strip()
    original_type = seeded[56:57].decode("cp037").strip()
    new_fname = "AJITHKUMAR"
    assert new_fname != original_fname  # the edit must be a real change

    with served_session(package, carddemo_system) as served:
        with closing(S3270()) as terminal:
            _admin_signon(terminal, served.port)
            _select(terminal, "03", "Update User")

            # Turn 1: find the user -> current details render (COUSR02C.cbl
            # READ-USER-SEC-FILE).
            terminal.run("MoveCursor(5,21)")
            terminal.run(f'String("{update_id}")')
            found = terminal.enter()
            assert original_fname in found
            assert "Press PF5 key to save your updates" in found

            # The find turn only READs and displays; VSAM must still hold
            # the old value until PF5 actually REWRITEs it.
            assert _usrsec_fields(served.region.vsam_engine, update_id)["fname"] == (
                original_fname
            )

            # Turn 2: edit the first name (FNAME POS=(11,18); MoveCursor
            # rows/cols below are 0-origin, one less than the BMS map's
            # 1-origin POS). LNAME/PASSWD/USRTYPE are BMS ATTRB=FSET, but
            # COUSR02C's re-entry path (COUSR02C.cbl:106-111) RECEIVEs and
            # re-SENDs without ever re-initialising COUSR2AO -- the same
            # A/F-byte overlap real BMS documents (RECEIVE's "field arrived
            # empty" flag at <f>F is the same byte as <f>A, COUSR02.CPY:
            # FILLER REDEFINES <f>F) means an untyped FSET field's MDT would
            # be dropped by this exact program on real CICS too (forge-1zu.8,
            # closed as faithful behaviour, not a cicada defect). Retyping
            # every field is what a real operator would be forced to do
            # against this program, not a workaround for a bug of ours.
            terminal.run("MoveCursor(10,18)")
            terminal.run(f'String("{new_fname}")')
            terminal.run("MoveCursor(10,56)")
            terminal.run(f'String("{original_lname}")')
            terminal.run("MoveCursor(12,16)")
            terminal.run(f'String("{original_pwd}")')
            terminal.run("MoveCursor(14,17)")
            terminal.run(f'String("{original_type}")')
            committed = terminal.enter("PF(5)")
            assert f"User {update_id} has been updated" in committed
            # COUSR2AO REDEFINES COUSR2AI, so this is an echo of typed input,
            # not proof of the REWRITE -- the VSAM read below is what proves
            # the committed value.
            assert _field(committed, 11, 18, 20).strip() == new_fname

            written = _usrsec_fields(served.region.vsam_engine, update_id)
            assert written["fname"] == new_fname
            assert (
                written["lname"] == original_lname
            )  # the retype above didn't corrupt this
            assert (
                written["pwd"] == original_pwd
            )  # the retype above didn't corrupt this
            assert written["type"] == original_type

            # Turn 3: USRIDIN is still populated (FSET) -- a plain ENTER
            # re-runs PROCESS-ENTER-KEY, doing a fresh READ. This is not
            # proof of the new fname by itself (COUSR2AO REDEFINES COUSR2AI,
            # so FNAMEO already held what was typed even before any COBOL
            # MOVE ran) -- what it proves is that the record still exists
            # and the READ comes back NORMAL after the REWRITE, i.e. the key
            # survived the update. The VSAM read above is what proves the
            # value.
            redisplayed = terminal.enter()
            assert "Press PF5 key to save your updates" in redisplayed
            assert _field(redisplayed, 11, 18, 20).strip() == new_fname


@covers(CobolFeature.EXEC_CICS)
def test_admin_delete_user_removes_usrsec(tmp_path, bridge_jar, carddemo_system):
    package = _package(tmp_path, bridge_jar, ("CC00", "CA00", "CU03"))
    delete_id = "USER0004"
    neighbour_ids = ("USER0003", "USER0005")
    ids = _usrsec_ids()
    assert delete_id in ids
    assert all(n in ids for n in neighbour_ids)
    seeded = [r for r in _usrsec_records() if r[0:8].decode("cp037") == delete_id][0]
    original_fname = seeded[8:28].decode("cp037").strip()
    original_lname = seeded[28:48].decode("cp037").strip()

    with served_session(package, carddemo_system) as served:
        with closing(S3270()) as terminal:
            _admin_signon(terminal, served.port)
            _select(terminal, "04", "Delete User")

            # Turn 1: find the user -> current details render read-only
            # (FNAME/LNAME/USRTYPE are ASKIP on COUSR3A -- display fields,
            # never retyped).
            terminal.run("MoveCursor(5,21)")
            terminal.run(f'String("{delete_id}")')
            found = terminal.enter()
            assert original_fname in found
            assert original_lname in found
            assert "Press PF5 key to delete this user" in found

            # The find turn only READs and displays; the record must still
            # exist in VSAM until PF5 actually DELETEs it.
            assert isinstance(
                served.region.vsam_engine.read("USRSEC", delete_id.encode("cp037")),
                RecordRead,
            )

            # Turn 2: PF5 DELETEs (COUSR03C.cbl:307, message at :320).
            committed = terminal.enter("PF(5)")
            assert f"User {delete_id} has been deleted" in committed

            engine = served.region.vsam_engine
            assert isinstance(
                engine.read("USRSEC", delete_id.encode("cp037")), NoRecord
            )
            for neighbour in neighbour_ids:
                assert isinstance(
                    engine.read("USRSEC", neighbour.encode("cp037")), RecordRead
                )

            # Turn 3: INITIALIZE-ALL-FIELDS cleared USRIDIN on success, so
            # retype the now-deleted id -- a fresh READ over the wire returns
            # NOTFND, confirming the DELETE persisted rather than merely
            # this test's own turn 2 belief that it worked.
            terminal.run(f'String("{delete_id}")')
            redisplayed = terminal.enter()
            assert "User ID NOT found" in redisplayed
