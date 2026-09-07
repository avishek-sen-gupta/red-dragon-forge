"""ByteRange.__str__ round-trip: the inverse of byte_range()."""

from cobble.dataflow.fields.extent_text import NO_RANGE, byte_range


def test_an_exact_range_round_trips_through_str():
    r = byte_range("WS-AREA@working_storage[0:12]", "XPROGA")
    assert byte_range(str(r), r.program) == r


def test_a_clamped_range_round_trips_with_the_mark():
    r = byte_range("WS-AREA@working_storage[40:52]~", "XPROGA")
    assert byte_range(str(r), r.program) == r


def test_no_range_renders_as_unparseable():
    assert str(NO_RANGE) == "(not storage)"
    assert byte_range("(not storage)", "XPROGA") == NO_RANGE
