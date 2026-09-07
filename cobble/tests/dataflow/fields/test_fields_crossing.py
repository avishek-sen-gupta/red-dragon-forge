"""Crossing a commarea: the rebase, its direction, and where it stops."""

from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.query import store_of


def _alias_row(
    caller="XPROGA",
    node="MAIN/2",
    transfer="LINK",
    callee="XPROGB",
    caller_extent="WS-AREA@working_storage[0:12]",
    callee_extent="DFHCOMMAREA@linkage[0:12]",
    returns=True,
    reason="",
) -> dict:
    return {
        "caller": caller,
        "node": node,
        "transfer": transfer,
        "callee": callee,
        "caller_extent": caller_extent,
        "callee_extent": callee_extent,
        "returns": returns,
        "reason": reason,
    }


def _crossed(store, text: str, program: str):
    return tuple(
        (alias.site, str(landing))
        for alias, landing in store.across((byte_range(text, program),))
    )


def test_a_caller_range_rebases_onto_the_callee_bytes():
    store = store_of((), (), (), (_alias_row(),))

    assert _crossed(store, "WS-ITEM@working_storage[4:8]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[4:8]"),
    )


def test_the_rebase_shifts_by_the_difference_of_the_two_window_starts():
    """The caller's area does not start at zero; the callee's always does."""
    store = store_of(
        (), (), (), (_alias_row(caller_extent="WS-AREA@working_storage[40:52]"),)
    )

    assert _crossed(store, "WS-ITEM@working_storage[44:48]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[4:8]"),
    )


def test_a_link_travels_back_from_the_callee():
    store = store_of((), (), (), (_alias_row(),))

    assert _crossed(store, "DFHCOMMAREA@linkage[8:12]", "XPROGB") == (
        ("XPROGA:MAIN/2", "WS-AREA@working_storage[8:12]"),
    )


def test_an_xctl_does_not_travel_back():
    store = store_of((), (), (), (_alias_row(transfer="XCTL", returns=False),))

    assert _crossed(store, "DFHCOMMAREA@linkage[8:12]", "XPROGB") == ()
    assert _crossed(store, "WS-ITEM@working_storage[0:4]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[0:4]"),
    )


def test_a_range_past_the_shared_window_does_not_cross():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(
                caller_extent="WS-AREA@working_storage[0:8]",
                callee_extent="DFHCOMMAREA@linkage[0:8]",
            ),
        ),
    )

    assert _crossed(store, "WS-TAIL@working_storage[8:12]", "XPROGA") == ()


def test_a_range_straddling_the_window_edge_is_clipped_to_it():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(
                caller_extent="WS-AREA@working_storage[0:8]",
                callee_extent="DFHCOMMAREA@linkage[0:8]",
            ),
        ),
    )

    assert _crossed(store, "WS-WIDE@working_storage[4:12]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[4:8]"),
    )


def test_a_dead_end_row_never_crosses_but_is_reportable():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(
                callee="",
                caller_extent="",
                callee_extent="",
                returns=False,
                reason="dynamic-target",
            ),
        ),
    )

    assert _crossed(store, "WS-ITEM@working_storage[0:4]", "XPROGA") == ()
    assert [alias.reason for alias in store.dead_ends("XPROGA")] == ["dynamic-target"]


def test_a_range_before_the_window_is_clipped_at_the_low_edge():
    store = store_of(
        (), (), (), (_alias_row(caller_extent="WS-AREA@working_storage[40:52]"),)
    )

    assert _crossed(store, "WS-BLOCK@working_storage[36:44]", "XPROGA") == (
        ("XPROGA:MAIN/2", "DFHCOMMAREA@linkage[0:4]"),
    )


def test_the_landing_carries_the_far_programs_name():
    store = store_of((), (), (), (_alias_row(),))

    landings = store.across((byte_range("WS-ITEM@working_storage[4:8]", "XPROGA"),))
    assert len(landings) == 1
    assert landings[0][1].program == "XPROGB"


def test_dead_ends_filters_by_caller_and_reason():
    store = store_of(
        (),
        (),
        (),
        (
            _alias_row(caller="XPROGA", reason=""),
            _alias_row(caller="XPROGA", reason="unreadable"),
            _alias_row(caller="XPROGC", reason="dynamic-target"),
        ),
    )

    found = store.dead_ends("XPROGA")
    assert len(found) == 1
    assert found[0].reason == "unreadable"
