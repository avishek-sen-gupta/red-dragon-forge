import pytest

from cics.dispatcher import InputEvent
from cics.screen.cursor import NO_CURSOR, Cursor
from cics.screen.terminal_screen import ScreenField, TerminalScreen
from cics.tn3270.codes import encode_address
from cics.tn3270.decoder import decode_inbound
from tests.covers import NotLanguageFeature, covers

_SCREEN = TerminalScreen(
    fields=(
        ScreenField(1482, 8, "USERID", 0x01, 0, 0, ""),
        ScreenField(1562, 8, "PASSWD", 0x0D, 0, 0, ""),
        ScreenField(1600, 1, "", 0x0C, 0, 0, ""),
    )
)


def _sba(offset, text):
    return b"\x11" + encode_address(offset) + text.encode("cp037")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_enter_with_modified_fields():
    record = (
        bytes((0x7D,))
        + encode_address(1491)
        + _sba(1483, "USER0001")
        + _sba(1563, "PASSWORD")
    )
    inbound = decode_inbound(record, _SCREEN)
    assert inbound.event == InputEvent(
        "\x7d", {"USERID": "USER0001", "PASSWD": "PASSWORD"}, Cursor(1491)
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_modified_unnamed_field_is_ignored_and_unknown_address_is_loud():
    assert (
        decode_inbound(
            bytes((0x7D,)) + encode_address(0) + _sba(1601, "X"), _SCREEN
        ).event.fields
        == {}
    )
    with pytest.raises(KeyError):
        decode_inbound(bytes((0x7D,)) + encode_address(0) + _sba(5, "X"), _SCREEN)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_short_reads_carry_only_the_aid():
    assert decode_inbound(bytes((0x6D,)), _SCREEN).event == InputEvent(
        "\x6d", {}, NO_CURSOR
    )
    assert decode_inbound(
        bytes((0xF3,)) + encode_address(7), _SCREEN
    ).event == InputEvent("\xf3", {}, Cursor(7))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unformatted_screen_text():
    record = bytes((0x7D,)) + encode_address(6) + "cc00 x".encode("cp037")
    assert decode_inbound(record, TerminalScreen()).unformatted_text == "cc00 x"
