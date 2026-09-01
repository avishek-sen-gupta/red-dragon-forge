"""Decoding fixed-format mainframe members.

A member is 8-bit text, not UTF-8. Measured on a production corpus: 110 of 4639
members carry bytes >= 0x80 — mostly 0xA6, the broken bar used to draw boxes in
report layouts, and 146 of those bytes sit in the code area inside VALUE
literals. So the codec has to be lossless, not merely non-raising: errors=
"replace" would turn load-bearing literal characters into U+FFFD.
"""

from interpreter.cobol.source_text import decode_source


def test_every_byte_survives_the_round_trip() -> None:
    """latin-1 is the byte-identity codec: defined for all 256 values."""
    raw = bytes(range(256))
    assert decode_source(raw).encode("latin-1") == raw


def test_a_high_byte_becomes_its_latin_1_character() -> None:
    """0xA6 is the broken bar, by far the commonest high byte in the corpus."""
    assert decode_source(b"\xa6") == "¦"


def test_one_byte_stays_one_character_so_column_positions_hold() -> None:
    """Fixed-format COBOL is column-addressed; a multi-byte decode would shift
    everything right of a high byte out of its area."""
    line = b"      * \xa6 comment"
    assert len(decode_source(line)) == len(line)
    assert decode_source(line).index("¦") == line.index(0xA6)


def test_bytes_that_are_not_valid_utf_8_decode_anyway() -> None:
    """0xA6 0xA6 is not a legal UTF-8 sequence — this is the case that raised
    UnicodeDecodeError before the source ever reached a parser."""
    assert decode_source(b"\xa6\xa6") == "¦¦"
