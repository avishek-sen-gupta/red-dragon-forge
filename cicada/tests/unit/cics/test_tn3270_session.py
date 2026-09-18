from bms_copybook_gen.parser import parse_mapsets
from cics.bms.catalog import catalog_from_mapsets
from cics.screen.cursor import NO_CURSOR
from cics.screen.driver import Abended, AwaitingInput, Ended, Returned
from cics.screen.payload import SendMapPayload, SendMode, SendTextPayload
from cics.tn3270.codes import (
    DO,
    EOR,
    IAC,
    OPTION_BINARY,
    OPTION_EOR,
    OPTION_TERMINAL_TYPE,
    WILL,
    encode_address,
)
from cics.tn3270.negotiation import Command, Subnegotiation
from cics.tn3270.session import run_session
from tests.covers import NotLanguageFeature, covers

_CATALOG = catalog_from_mapsets(
    parse_mapsets(
        [
            {"name": "DFHMSD", "label": "SET", "args": {"TYPE": "MAP"}},
            {"name": "DFHMDI", "label": "MAP", "args": {"SIZE": "(24,80)"}},
            {
                "name": "DFHMDF",
                "label": "NAME",
                "args": {"POS": "(1,2)", "LENGTH": "4", "ATTRB": "(UNPROT,IC)"},
            },
        ]
    )
)
_MAP = SendMapPayload(
    "MAP", "SET", SendMode.FULL, True, False, False, True, NO_CURSOR, {}, {}
)


class _Peer:
    def __init__(self, records):
        self.records, self.sent = list(records), []
        self.events = [
            Command(WILL, OPTION_TERMINAL_TYPE),
            Subnegotiation(OPTION_TERMINAL_TYPE, b"\x00IBM-3278-2"),
            Command(WILL, OPTION_EOR),
            Command(DO, OPTION_EOR),
            Command(WILL, OPTION_BINARY),
            Command(DO, OPTION_BINARY),
        ]

    def send(self, data):
        self.sent.append(data)

    def next_event(self):
        return self.events.pop(0)

    def next_record(self):
        return self.records.pop(0) if self.records else b""

    def painted(self):
        return [s for s in self.sent if s.endswith(bytes((IAC, EOR)))]


class _Driver:
    def __init__(self, turns):
        self.turns, self.events, self.started = list(turns), [], []

    def knows(self, transid):
        return transid == "CC00"

    def start(self, transid):
        self.started.append(transid)
        return AwaitingInput((_MAP,))

    def respond(self, event):
        self.events.append(event)
        return self.turns.pop(0)


def _enter(text=""):
    return bytes((0x7D,)) + encode_address(0) + text.encode("cp037")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_initial_transaction_input_and_abend():
    typed = (
        bytes((0x7D,))
        + encode_address(5)
        + b"\x11"
        + encode_address(2)
        + "ABCD".encode("cp037")
    )
    driver = _Driver([Ended((), Abended("ASRA"))])
    peer = _Peer([typed])
    final = run_session(peer, driver, _CATALOG, "CC00")
    assert driver.started == ["CC00"]
    assert driver.events[0].fields == {"NAME": "ABCD"}
    assert "abended: ASRA" in peer.painted()[-1].decode("cp037")
    assert not final.in_task


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_idle_screen_starts_known_transids_and_rejects_others():
    driver = _Driver([Ended((SendTextPayload("bye"),), Returned())])
    peer = _Peer([_enter("zzzz"), _enter("cc00"), _enter(), _enter()])
    final = run_session(peer, driver, _CATALOG, "")
    assert "Transaction ZZZZ is not recognized." in peer.painted()[1].decode("cp037")
    assert driver.started == ["CC00"]
    assert final.screen.unformatted == "" and not final.in_task
