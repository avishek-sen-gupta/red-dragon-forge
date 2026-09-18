from cics.screen.terminal_screen import ScreenField, TerminalScreen
from cics.tn3270.codes import decode_address, encode_address, frame_record
from cics.tn3270.encoder import encode_screen
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_address_codec_round_trips_every_24x80_position():
    assert all(decode_address(*encode_address(a)) == a for a in range(1920))
    assert encode_address(0) == b"\x40\x40" and encode_address(1483) == b"\xd7\x4b"
    assert decode_address(0x05, 0xCB) == 1483


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_records_double_iac_and_end_with_eor():
    assert frame_record(b"\x01\xff") == b"\x01\xff\xff\xff\xef"


_FIELD = ScreenField(
    address=1482,
    length=8,
    name="USERID",
    attribute=0x01,
    color=0xF4,
    hilight=0xF0,
    content="AB",
)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_basic_encoding():
    record = encode_screen(
        TerminalScreen(fields=(_FIELD,), cursor=1483), extended=False
    )
    assert record == bytes((0xF5, 0xC2, 0x11, 0xD7, 0x4A, 0x1D, 0xC1)) + "AB".encode(
        "cp037"
    ) + bytes((0x11, 0xD7, 0x4B, 0x13))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_extended_encoding_and_alarm():
    record = encode_screen(
        TerminalScreen(fields=(_FIELD,), cursor=0, alarm=True), extended=True
    )
    assert record[:2] == bytes((0xF5, 0xC6))
    assert bytes((0x29, 3, 0xC0, 0xC1, 0x41, 0xF0, 0x42, 0xF4)) in record


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unformatted_text_starts_at_offset_zero():
    assert (
        encode_screen(TerminalScreen(unformatted="HI"), False).startswith(
            bytes((0xF5, 0xC2, 0x11, 0x40, 0x40)) + "HI".encode("cp037")
        )
        == True
    )
