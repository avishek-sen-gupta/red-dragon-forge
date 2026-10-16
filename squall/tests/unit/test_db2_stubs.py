"""The Db2 stub programs squall names are exactly the stub sources it ships."""

from squall.db2_stubs import DB2_STUB_PROGRAMS, DB2_STUBS_DIR, read_db2_stub_sources


def test_the_named_stubs_are_the_shipped_stub_sources() -> None:
    assert (
        DB2_STUB_PROGRAMS,
        tuple(sorted(p.stem for p in DB2_STUBS_DIR.glob("*.cbl"))),
        tuple(sorted(read_db2_stub_sources())),
    ) == (("DSNTIAC",), ("DSNTIAC",), ("DSNTIAC",))
