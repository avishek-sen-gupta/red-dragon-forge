import pytest

from cics.tn3270.codes import (
    DO,
    DONT,
    IAC,
    OPTION_BINARY,
    OPTION_EOR,
    OPTION_TERMINAL_TYPE,
    WILL,
    WONT,
)
from cics.tn3270.negotiation import (
    Command,
    Subnegotiation,
    UnsupportedTerminal,
    negotiate,
)
from tests.covers import NotLanguageFeature, covers


class _Peer:
    def __init__(self, events):
        self.events, self.sent = list(events), []

    def send(self, data):
        self.sent.append(data)

    def next_event(self):
        return self.events.pop(0)

    def next_record(self):
        return b""


def _handshake(name=b"IBM-3278-2-E"):
    return [
        Command(WILL, 99),
        Command(WILL, OPTION_TERMINAL_TYPE),
        Subnegotiation(OPTION_TERMINAL_TYPE, b"\x00" + name),
        Command(WILL, OPTION_EOR),
        Command(DO, OPTION_EOR),
        Command(WILL, OPTION_BINARY),
        Command(DO, OPTION_BINARY),
    ]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_negotiates_terminal_type_binary_and_eor():
    peer = _Peer(_handshake())
    assert negotiate(peer).extended
    assert peer.sent[0] == bytes((IAC, DO, OPTION_TERMINAL_TYPE))
    assert bytes((IAC, DONT, 99)) in peer.sent
    assert peer.events == []


@covers(NotLanguageFeature.INFRASTRUCTURE)
@pytest.mark.parametrize("name", [b"IBM-3278-4", b"IBM-3279-5-E"])
def test_every_3278_3279_model_is_accepted(name):
    assert negotiate(_Peer(_handshake(name))).name == name.decode()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unsupported_terminal_and_declined_option_are_refused():
    with pytest.raises(UnsupportedTerminal):
        negotiate(_Peer(_handshake(b"IBM-DYNAMIC")))
    with pytest.raises(UnsupportedTerminal):
        negotiate(_Peer([Command(WONT, OPTION_TERMINAL_TYPE)]))
