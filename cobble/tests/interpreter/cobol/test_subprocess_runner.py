"""The charset on the wire between cobble and the ProLeap bridge.

The bridge declares one codec for everything crossing it -- ``SOURCE_CHARSET =
ISO_8859_1`` in Main.java, applied to the file it parses, the copybooks it opens
and the JSON it writes. Nothing on this side is negotiated, so this side has to
match it, and ``text=True`` does not: it uses the locale encoding, which
round-trips only by coincidence when that happens to be UTF-8 at both ends.

It stopped being a coincidence. Main reads stdin with ``System.in.readAllBytes``
and writes those bytes to its temp file verbatim, then hands the temp file to
ProLeap with the ISO-8859-1 charset. So a UTF-8 wire turns one 0xA6 into 0xC2
0xA6, ProLeap reads two characters where the member had one, and every column
right of it shifts. In FIXED format that is not cosmetic: a member whose
terminating period sat in column 72 has it pushed to 73, outside the code area,
where ProLeap truncates it away. The entry never terminates and the next line's
FILLER arrives as ``extraneous input 'FILLER'`` -- a syntax error hundreds of
lines from anything that is actually malformed.

These tests use a Python subprocess rather than the bridge, because what has to
hold is a property of the wire and holds without a JVM: the bytes the bridge
receives are the member's bytes, and the bytes it sends back are read as they
were written.
"""

import sys

from interpreter.cobol.subprocess_runner import RealSubprocessRunner

# 0xA6, the broken bar, is by far the commonest high byte in a real corpus -- it
# draws the boxes in report layouts. One character in latin-1, two bytes in UTF-8.
BROKEN_BAR = "\xa6"


def _byte_count_command() -> list[str]:
    """A subprocess that reports how many BYTES it received on stdin."""
    return [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write(str(len(sys.stdin.buffer.read())))",
    ]


def _emit_high_byte_command() -> list[str]:
    """A subprocess that writes a raw 0xA6 to stdout, as the bridge's JSON does."""
    return [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'\\xa6')",
    ]


def test_a_high_byte_reaches_the_bridge_as_one_byte() -> None:
    """The wire is byte-identity, so the bridge parses the member's own columns.

    Under the locale encoding this is 2, ProLeap reads ISO-8859-1, and the parse
    sees a line one character longer than the member's.
    """
    received = RealSubprocessRunner().run(_byte_count_command(), BROKEN_BAR)

    assert received == "1"


def test_every_byte_reaches_the_bridge_unchanged() -> None:
    """Not just 0xA6: no byte a member can hold may expand on the way in."""
    all_bytes = bytes(range(256)).decode("latin-1")

    received = RealSubprocessRunner().run(_byte_count_command(), all_bytes)

    assert received == "256"


def test_a_high_byte_in_the_bridge_output_is_read_back() -> None:
    """The return path is the same codec. Main pins its stdout to SOURCE_CHARSET,
    so a high byte in a VALUE literal arrives as 0xA6 -- which is not legal UTF-8
    and raises UnicodeDecodeError on a locale-encoded read, costing the whole
    program for a byte that was never in doubt."""
    emitted = RealSubprocessRunner().run(_emit_high_byte_command(), "")

    assert emitted == BROKEN_BAR
