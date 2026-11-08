"""The Horn lowering's answers on CardDemo, against answers read from the COBOL by hand."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import pytest
from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.depgraph.cics_cache import cached_asg_dialect_parsers_registered
from cobble.experimental.horn.answer import Answer
from cobble.experimental.horn.condition import Condition, Digits, Op, Part, Visited
from cobble.experimental.horn.conversation import converse
from cobble.experimental.horn.leading_to import leading_to
from cobble.experimental.horn.lower import HornSystem, lower
from cobble.experimental.horn.named_fields import NamedFields
from cobble.experimental.horn.point import Point
from cobble.experimental.horn.program import Program, program_of
from cobble.experimental.horn.reaches import reaches
from cobble.parsing.asg_cache import cache_path, first_program_at
from tests.carddemo.conftest import CardDemoRun

logger = logging.getLogger(__name__)

SIGNON = "COSGN00C"
USER_MENU = Point(SIGNON, "READ-USER-SEC-FILE/1.when.0.0.then.5.else.0")
ADMIN_MENU = Point(SIGNON, "READ-USER-SEC-FILE/1.when.0.0.then.5.then.0")

BILLPAY = "COBIL00C"
CONFIRMED = Point(BILLPAY, "PROCESS-ENTER-KEY/4.then.0.then.0")
REWRITE = Point(BILLPAY, "UPDATE-ACCTDAT-FILE/0")
WRITE_TRANSACT = Point(BILLPAY, "WRITE-TRANSACT-FILE/0")
READ_ACCOUNT = Point(BILLPAY, "READ-ACCTDAT-FILE/0")
BILLPAY_WATCHED = ("TRAN-AMT", "ACCT-CURR-BAL", "ACCT-ID", "ACTIDINI")
CONFIRM_PROMPT = Point(BILLPAY, "PROCESS-ENTER-KEY/4.then.0.else.0")

CARD_UPDATE = "COCRDUPC"
CARD_LIST = "COCRDLIC"
MAIN_MENU = "COMEN01C"
CARD_REWRITE = Point(CARD_UPDATE, "9200-WRITE-PROCESSING/13")
CHANGES_CHECKED = (
    Point(CARD_UPDATE, "1200-EDIT-MAP-INPUTS/19.else.0"),
    Point(CARD_UPDATE, "2000-DECIDE-ACTION/0.when.1.0.else.0"),
)
CARD_STATE = NamedFields(frozenset({"EIBCALEN", "CCUP-CHANGE-ACTION"}))
CARD_HANDOVER = NamedFields(
    frozenset(
        {
            "EIBCALEN",
            "CCUP-CHANGE-ACTION",
            "CDEMO-PGM-CONTEXT",
            "CDEMO-FROM-PROGRAM",
            "LIT-MENUPGM",
            "LIT-CCLISTPGM",
            "LIT-THISPGM",
            "WS-PGMNAME",
        }
    )
)


def _program(run: CardDemoRun, program: str) -> Program:
    with cached_asg_dialect_parsers_registered():
        asg = first_program_at(cache_path(run.asg, run.cobol / f"{program}.cbl"))
        return program_of(asg)


def _lowered(run: CardDemoRun, program: str, watched: Sequence[str] = ()) -> HornSystem:
    return lower(_program(run, program), watched)


def _links(run: CardDemoRun) -> tuple[LinkRow, ...]:
    lines = (run.combine / "links.jsonl").read_text(encoding="utf-8").splitlines()
    return tuple(LinkRow.model_validate_json(line) for line in lines if line.strip())


@pytest.fixture(scope="module")
def signon(carddemo: CardDemoRun) -> HornSystem:
    return _lowered(carddemo, SIGNON)


@pytest.fixture(scope="module")
def billpay(carddemo: CardDemoRun) -> Program:
    return _program(carddemo, BILLPAY)


def _toward(program: Program, goal: Point) -> HornSystem:
    return lower(program, BILLPAY_WATCHED, kept=leading_to(program.cfg, goal.node))


def _ask(
    system: HornSystem, point: Point, conditions: Sequence[Condition | Visited]
) -> Answer:
    verdict = reaches(system, point, conditions, time.perf_counter)
    logger.info(
        "%s %s: %s in %.3fs", point.node, conditions, verdict.answer, verdict.seconds
    )
    return verdict.answer


def test_signon_can_transfer_to_the_user_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:230 IF CDEMO-USRTYP-ADMIN, :235-237 ELSE EXEC CICS XCTL
    PROGRAM ('COMEN01C'). Some run reaches it."""
    assert _ask(signon, USER_MENU, ()) == Answer.SAT


def test_signon_can_transfer_to_the_admin_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:230-232 IF CDEMO-USRTYP-ADMIN EXEC CICS XCTL PROGRAM
    ('COADM01C'). Some run reaches it."""
    assert _ask(signon, ADMIN_MENU, ()) == Answer.SAT


def test_signon_never_sends_an_admin_to_the_user_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:227 MOVE SEC-USR-TYPE TO CDEMO-USER-TYPE, then :230 IF
    CDEMO-USRTYP-ADMIN, which COCOM01Y.cpy:27 declares as VALUE 'A'. The XCTL to
    COMEN01C is on the ELSE, and nothing writes CDEMO-USER-TYPE between the test and
    the XCTL."""
    admin = Condition("CDEMO-USER-TYPE", Op.EQ, "'A'")
    assert _ask(signon, USER_MENU, (admin,)) == Answer.UNSAT


def test_signon_never_sends_a_user_to_the_admin_menu(signon: HornSystem) -> None:
    """COSGN00C.cbl:227 and :230, as above: the XCTL to COADM01C is on the THEN of
    CDEMO-USER-TYPE = 'A'."""
    other = Condition("CDEMO-USER-TYPE", Op.NE, "'A'")
    assert _ask(signon, ADMIN_MENU, (other,)) == Answer.UNSAT


def _never_with(system: HornSystem, field: str, value: str) -> Answer:
    return _ask(system, USER_MENU, (Condition(field, Op.EQ, value),))


def test_signon_never_transfers_with_a_blank_user_id(signon: HornSystem) -> None:
    """COSGN00C.cbl:118-119 WHEN USERIDI OF COSGN0AI = SPACES OR LOW-VALUES MOVE 'Y'
    TO WS-ERR-FLG, and :138-139 IF NOT ERR-FLG-ON PERFORM READ-USER-SEC-FILE, the
    paragraph holding the XCTL. ERR-FLG-ON is VALUE 'Y' (:41). Nothing between
    writes WS-ERR-FLG or USERIDI."""
    assert _never_with(signon, "USERIDI", "SPACES") == Answer.UNSAT


def test_signon_never_transfers_with_a_low_values_user_id(signon: HornSystem) -> None:
    """COSGN00C.cbl:118-119 and :138-139, as above, for LOW-VALUES."""
    assert _never_with(signon, "USERIDI", "LOW-VALUES") == Answer.UNSAT


def test_signon_never_transfers_with_a_blank_password(signon: HornSystem) -> None:
    """COSGN00C.cbl:123-124 WHEN PASSWDI OF COSGN0AI = SPACES OR LOW-VALUES MOVE 'Y'
    TO WS-ERR-FLG, and :138-139. A blank user id takes the first WHEN, which sets the
    same flag."""
    assert _never_with(signon, "PASSWDI", "SPACES") == Answer.UNSAT


def test_signon_never_transfers_with_a_low_values_password(signon: HornSystem) -> None:
    """COSGN00C.cbl:123-124 and :138-139, as above, for LOW-VALUES."""
    assert _never_with(signon, "PASSWDI", "LOW-VALUES") == Answer.UNSAT


@pytest.mark.slow
def test_billpay_proceeds_only_on_a_y_or_lowercase_y_in_the_confirm_field(
    billpay: Program,
) -> None:
    """COBIL00C.cbl:156 SET CONF-PAY-NO TO TRUE; :173-176 EVALUATE CONFIRMI WHEN 'Y'
    WHEN 'y' SET CONF-PAY-YES TO TRUE; :210 IF CONF-PAY-YES PERFORM
    READ-CXACAIX-FILE (:211). Nothing else sets CONF-PAY-YES."""
    system = _toward(billpay, CONFIRMED)
    neither = (
        Condition("CONFIRMI", Op.NE, "'Y'"),
        Condition("CONFIRMI", Op.NE, "'y'"),
    )
    assert (
        _ask(system, CONFIRMED, ()),
        _ask(system, CONFIRMED, neither),
    ) == (
        Answer.SAT,
        Answer.UNSAT,
    )


@pytest.mark.slow
def test_billpay_never_proceeds_with_a_blank_or_low_values_account_id(
    billpay: Program,
) -> None:
    """COBIL00C.cbl:159-160 WHEN ACTIDINI OF COBIL0AI = SPACES OR LOW-VALUES MOVE
    'Y' TO WS-ERR-FLG, and :208 IF NOT ERR-FLG-ON guards :210-211. Nothing between
    clears the flag or writes ACTIDINI."""
    system = _toward(billpay, CONFIRMED)
    assert (
        _ask(
            system,
            CONFIRMED,
            (Condition("ACTIDINI", Op.EQ, "SPACES"),),
        ),
        _ask(
            system,
            CONFIRMED,
            (Condition("ACTIDINI", Op.EQ, "LOW-VALUES"),),
        ),
    ) == (Answer.UNSAT, Answer.UNSAT)


@pytest.mark.slow
def test_billpay_rewrites_the_balance_after_a_failed_transaction_write(
    billpay: Program,
) -> None:
    """COBIL00C.cbl:233 PERFORM WRITE-TRANSACT-FILE, then :234-235 COMPUTE and
    PERFORM UPDATE-ACCTDAT-FILE with no test between. A successful write clears the
    screen (:523-524, :563-565: CONFIRMI to SPACES); a failed one sets WS-ERR-FLG to
    'Y' (:535, :542) and leaves CONFIRMI as typed. So the REWRITE can run with
    CONFIRMI still 'Y' only after a failed write."""
    system = _toward(billpay, REWRITE)
    confirmed = Condition("CONFIRMI", Op.EQ, "'Y'")
    assert (
        _ask(
            system,
            REWRITE,
            (confirmed, Condition("WS-ERR-FLG", Op.EQ, "'N'")),
        ),
        _ask(
            system,
            REWRITE,
            (confirmed, Condition("WS-ERR-FLG", Op.EQ, "'Y'")),
        ),
    ) == (Answer.UNSAT, Answer.SAT)


@pytest.mark.slow
def test_billpay_writes_the_balance_it_read_less_its_leading_digit(
    billpay: Program,
) -> None:
    """COBIL00C.cbl:224 MOVE ACCT-CURR-BAL (S9(10)V99) TO TRAN-AMT (S9(9)V99), then
    :233 PERFORM WRITE-TRANSACT-FILE before :234 COMPUTE ACCT-CURR-BAL. The move
    lines the two up on the decimal point, so TRAN-AMT's digits are digits 2-12 of
    the balance as read, and the balance's leading digit may be non-zero there: the
    amount equals the balance except its top digit, and differs from it for a
    balance of 1,000,000,000.00 or more. The zones and sign are the compiler's, so
    the bytes themselves may differ."""
    system = _toward(billpay, WRITE_TRANSACT)
    amount, low = Digits("TRAN-AMT", 1, 11), Digits("ACCT-CURR-BAL", 2, 11)
    assert (
        _ask(
            system,
            WRITE_TRANSACT,
            (Condition(amount, Op.NE, low),),
        ),
        _ask(
            system,
            WRITE_TRANSACT,
            (Condition(amount, Op.EQ, low),),
        ),
        _ask(
            system,
            WRITE_TRANSACT,
            (Condition(Digits("ACCT-CURR-BAL", 1, 1), Op.NE, "'0'"),),
        ),
        _ask(
            system,
            WRITE_TRANSACT,
            (Condition("TRAN-AMT", Op.NE, Part("ACCT-CURR-BAL", 2, 11)),),
        ),
    ) == (Answer.UNSAT, Answer.SAT, Answer.SAT, Answer.SAT)


@pytest.mark.slow
def test_billpay_reads_for_update_the_account_the_user_typed(
    billpay: Program,
) -> None:
    """COBIL00C.cbl:170 MOVE ACTIDINI OF COBIL0AI TO ACCT-ID XREF-ACCT-ID; both
    PERFORMs of READ-ACCTDAT-FILE (:177, :184) follow it, and nothing between
    writes either field; :345-351 EXEC CICS READ INTO(ACCOUNT-RECORD) RIDFLD(ACCT-ID)
    UPDATE, the read whose record the REWRITE at :379 replaces. ACCT-ID is a
    number, so it holds the typed digits under the compiler's zones."""
    system = _toward(billpay, READ_ACCOUNT)
    key, typed = Digits("ACCT-ID", 1, 11), Digits("ACTIDINI", 1, 11)
    assert (
        _ask(
            system,
            READ_ACCOUNT,
            (Condition(key, Op.NE, typed),),
        ),
        _ask(
            system,
            READ_ACCOUNT,
            (Condition(key, Op.EQ, typed),),
        ),
    ) == (Answer.UNSAT, Answer.SAT)


def _card_rewrite(system: HornSystem) -> tuple[Answer, Answer, Answer]:
    def visited(value: bool) -> tuple[Visited, ...]:
        return tuple(Visited(point, value) for point in CHANGES_CHECKED)

    return (
        _ask(system, CARD_REWRITE, ()),
        _ask(system, CARD_REWRITE, visited(True)),
        _ask(system, CARD_REWRITE, visited(False)),
    )


def test_a_card_rewrite_in_card_updates_own_chain_follows_a_check_of_the_changes(
    carddemo: CardDemoRun,
) -> None:
    """COCRDUPC.cbl:988-990 WHEN CCUP-CHANGES-OK-NOT-CONFIRMED AND CCARD-AID-PFK05
    PERFORM 9200-WRITE-PROCESSING, the REWRITE at :1478. CCUP-CHANGE-ACTION is
    'N' only after :713, the end of the edits, or :976, and a task without a
    commarea INITIALIZEs it (:388-394). Here the chain starts cold and only card
    update hands it on, so those two fields are all the proof needs."""
    links = tuple(link for link in _links(carddemo) if link.caller == CARD_UPDATE)
    system = converse(
        (_program(carddemo, CARD_UPDATE),),
        links,
        marks=CHANGES_CHECKED,
        kept=CARD_STATE,
    )
    assert _card_rewrite(system) == (Answer.SAT, Answer.SAT, Answer.UNSAT)


@pytest.mark.slow
def test_a_card_rewrite_always_follows_a_check_of_the_changes(
    carddemo: CardDemoRun,
) -> None:
    """As above, with the menu and the card list handing over too. One from the
    menu with CDEMO-PGM-ENTER INITIALIZEs (:502-510), and one from the card list
    sets 'S' (:482-494), COCRDLIC.cbl :548-551 having set its own name and
    CDEMO-PGM-ENTER. The menu and the card list hand over 160 bytes, so the state
    byte past them is whatever storage holds; the program never reads it there.
    The proof keeps only the tests on the entry fields and the program names they
    are compared with."""
    system = converse(
        tuple(_program(carddemo, p) for p in (CARD_UPDATE, CARD_LIST, MAIN_MENU)),
        _links(carddemo),
        marks=CHANGES_CHECKED,
        kept=CARD_HANDOVER,
    )
    assert _card_rewrite(system) == (Answer.SAT, Answer.SAT, Answer.UNSAT)


@pytest.mark.slow
def test_billpay_pays_on_the_press_that_shows_the_balance(
    carddemo: CardDemoRun,
) -> None:
    """COBIL00C.cbl:173-176 sets CONF-PAY-YES when CONFIRMI is 'Y' on the same
    Enter that carries the account id, and :210-235 then pays; the prompt at
    :237-239 need never have been shown."""
    system = converse(
        (_program(carddemo, BILLPAY),), _links(carddemo), marks=(CONFIRM_PROMPT,)
    )
    assert _ask(system, REWRITE, (Visited(CONFIRM_PROMPT, False),)) == Answer.SAT
