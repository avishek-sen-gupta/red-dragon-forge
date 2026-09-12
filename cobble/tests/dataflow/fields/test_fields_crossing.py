"""Crossing a commarea: the rebase, its direction, and how far it travels."""

import json
from itertools import pairwise

import pytest
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fixpoint.query import Side, cli, crossing, store_of
from test_fields_query import _declared, _edge


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


def _linkage_declared(name: str, level: int, low: int, high: int, program: str) -> dict:
    """One field of a commarea record as the callee declares it.

    ``_declared`` lays every field in working storage, and ``ByteRange.overlaps``
    compares the region, so a group and its child in LINKAGE cannot be spelled with
    it.
    """
    return {
        "id": f"{program}.{name}",
        "level": level,
        "usage": "" if level == 1 else "DISPLAY",
        "extents": [f"{name}@linkage[{low}:{high}]"],
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


def test_a_dead_end_row_never_crosses():
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


def _two_program_extent_rows():
    return (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _declared("WS-SINK", 1, ((16, 20),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGB"),
        _declared("SUB-REC", 1, ((0, 12),), program="XPROGB"),
    )


def _two_program_edge_rows():
    return (
        _edge(
            "DFHCOMMAREA",
            "SUB-REC",
            "SUB/1",
            "DFHCOMMAREA@linkage[0:12]",
            "SUB-REC@working_storage[0:12]",
            program="XPROGB",
        ),
    )


def _two_program_store(*aliases: dict):
    return store_of(
        _two_program_extent_rows(),
        _two_program_edge_rows(),
        (),
        aliases or (_alias_row(),),
    )


def _landings(found):
    return tuple((one.hops, one.field_id, one.via) for one in found.landings)


def test_a_crossing_walk_continues_into_the_callee():
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert (1, "XPROGB.DFHCOMMAREA", "XPROGA:MAIN/2") in _landings(found)
    assert (1, "XPROGB.SUB-REC", "XPROGA:MAIN/2") in _landings(found)


def test_without_a_hop_budget_the_walk_never_leaves_the_caller():
    """``hops=0`` is the plain walk's setting, which no CLI invocation reaches:
    ``_hop_budget`` rejects ``--max-hops 0``."""
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=0)

    assert _landings(found) == ()


def _onward_from_the_callee():
    """XPROGB passes what it received on, so a one-hop budget has something to cut."""
    return _alias_row(
        caller="XPROGB",
        node="SUB/9",
        transfer="XCTL",
        callee="XPROGD",
        caller_extent="SUB-REC@working_storage[0:12]",
        callee_extent="DFHCOMMAREA@linkage[0:12]",
        returns=False,
    )


def test_the_hop_limit_holds_the_walk_short_of_the_next_callee():
    store = _two_program_store(_alias_row(), _onward_from_the_callee())
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=1)

    assert max(one.hops for one in found.landings) == 1
    assert not any(one.field_id.startswith("XPROGD") for one in found.landings)


def test_a_mutual_link_terminates_with_finite_landings():
    """XPROGA links XPROGB links XPROGA: the walk must terminate."""
    back = _alias_row(
        caller="XPROGB",
        node="SUB/9",
        callee="XPROGA",
        caller_extent="SUB-REC@working_storage[0:12]",
        callee_extent="DFHCOMMAREA@linkage[0:12]",
    )
    store = _two_program_store(_alias_row(), back)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=6)

    landing_pairs = {(one.field_id, one.hops) for one in found.landings}
    assert landing_pairs == {
        ("XPROGB.DFHCOMMAREA", 1),
        ("XPROGB.SUB-REC", 1),
        ("XPROGA.DFHCOMMAREA", 2),
    }


def test_the_start_field_is_not_its_own_landing_after_a_symmetric_link():
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert not any(one.field_id == "XPROGA.WS-AREA" for one in found.landings)


def test_hops_is_minimal_among_routes_within_depth():
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _declared("WS-MID", 1, ((16, 20),), program="XPROGA"),
        _declared("WS-Q", 1, ((24, 28),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGC"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGZ"),
        _declared("Z-SINK", 1, ((16, 20),), program="XPROGZ"),
    )
    edges = (
        _edge(
            "WS-AREA",
            "WS-MID",
            "MAIN/5",
            "WS-AREA@working_storage[0:4]",
            "WS-MID@working_storage[16:20]",
            program="XPROGA",
        ),
        _edge(
            "WS-MID",
            "WS-Q",
            "MAIN/6",
            "WS-MID@working_storage[16:20]",
            "WS-Q@working_storage[24:28]",
            program="XPROGA",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/1",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="MAIN/9",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="WS-Q@working_storage[24:28]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    z_landings = [one for one in found.landings if one.field_id == "XPROGZ.DFHCOMMAREA"]
    assert len(z_landings) == 1
    assert z_landings[0].hops == 1
    assert z_landings[0].via == "XPROGA:MAIN/9"


def _converging_routes():
    """Two routes of different cost onto one range, **and a flow leaving it**.

    ``XPROGA`` XCTLs ``XPROGB`` XCTLs ``XPROGC``, which is the dear way onto
    ``XPROGC.DFHCOMMAREA`` (two hops) and from there to ``C-REC`` by a flow.
    ``XPROGC`` also LINKs ``XPROGA``, so the same ``C-REC`` bytes are one symmetric
    hop back from ``M1``. Both arrive in the same level, and ``C-REC`` flows on to
    ``C-SINK``: without a cost-canonical level the flow is priced off whichever
    arrival the step built first, so what the convergence costs is only observable
    downstream of it.
    """
    declared = (
        _declared("WS-A", 1, ((0, 4),), program="XPROGA"),
        _declared("M0", 1, ((8, 12),), program="XPROGA"),
        _linkage_declared("M1", 1, 0, 4, program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 4, program="XPROGB"),
        _declared("B-REC", 1, ((0, 4),), program="XPROGB"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 4, program="XPROGC"),
        _declared("C-REC", 1, ((0, 4),), program="XPROGC"),
        _declared("C-SINK", 1, ((16, 20),), program="XPROGC"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 4, program="XPROGF"),
    )
    edges = (
        _edge(
            "WS-A",
            "M0",
            "AMAIN/1",
            "WS-A@working_storage[0:4]",
            "M0@working_storage[8:12]",
            program="XPROGA",
        ),
        _edge(
            "M0",
            "M1",
            "AMAIN/2",
            "M0@working_storage[8:12]",
            "M1@linkage[0:4]",
            program="XPROGA",
        ),
        _edge(
            "DFHCOMMAREA",
            "B-REC",
            "BMAIN/1",
            "DFHCOMMAREA@linkage[0:4]",
            "B-REC@working_storage[0:4]",
            program="XPROGB",
        ),
        _edge(
            "DFHCOMMAREA",
            "C-REC",
            "CMAIN/1",
            "DFHCOMMAREA@linkage[0:4]",
            "C-REC@working_storage[0:4]",
            program="XPROGC",
        ),
        _edge(
            "C-REC",
            "C-SINK",
            "CMAIN/2",
            "C-REC@working_storage[0:4]",
            "C-SINK@working_storage[16:20]",
            program="XPROGC",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="AMAIN/9",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-A@working_storage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGB",
            node="BMAIN/9",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="DFHCOMMAREA@linkage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/5",
            transfer="LINK",
            callee="XPROGA",
            caller_extent="C-REC@working_storage[0:4]",
            callee_extent="M1@linkage[0:4]",
            returns=True,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/7",
            transfer="XCTL",
            callee="XPROGF",
            caller_extent="C-SINK@working_storage[16:20]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
    )
    return store_of(declared, edges, (), aliases)


def _converging_walk(hops: int):
    return crossing(
        _converging_routes(),
        (byte_range("WS-A@working_storage[0:4]", "XPROGA"),),
        Side.SOURCE,
        depth=6,
        hops=hops,
    )


def test_a_flow_leaving_a_convergence_is_priced_off_the_cheap_route():
    found = _converging_walk(3)

    sink = [one for one in found.landings if one.field_id == "XPROGC.C-SINK"]
    assert [(one.hops, one.via) for one in sink] == [(1, "XPROGC:CMAIN/5")]


def test_raising_the_hop_budget_never_raises_a_landings_cost():
    """Monotonicity, which the first-match cost broke outright: the same landing
    reported one hop at a budget of one and two hops at a budget of two, so a
    reader who widened the search was told the answer got further away.

    Keyed by field and bytes, because the walk publishes one landing per field
    *and* non-overlapping range -- the reason ``Landing.at`` exists. Keying on the
    field alone keeps whichever landing came last and compares two different
    answers, which can pass while monotonicity is broken. A landing the wider
    budget lost fails here too, by absence.
    """
    costs = tuple(
        {(one.field_id, one.at): one.hops for one in _converging_walk(hops).landings}
        for hops in (1, 2, 3)
    )

    for tighter, wider in pairwise(costs):
        assert all(wider[place] <= cost for place, cost in tighter.items())


def test_the_whole_answer_at_two_budgets_loses_no_landing():
    """A whole tuple, because the cost defects were invisible to a membership test:
    ``XPROGF`` is two hops away, so a two-hop budget must find it at two hops."""
    wide, tight = _converging_walk(3), _converging_walk(2)

    assert _landings(tight) == _landings(wide)
    assert _landings(wide) == (
        (0, "XPROGA.M0", ""),
        (0, "XPROGA.M1", ""),
        (1, "XPROGB.DFHCOMMAREA", "XPROGA:AMAIN/9"),
        (1, "XPROGB.B-REC", "XPROGA:AMAIN/9"),
        (1, "XPROGC.C-REC", "XPROGC:CMAIN/5"),
        (1, "XPROGC.C-SINK", "XPROGC:CMAIN/5"),
        (2, "XPROGC.DFHCOMMAREA", "XPROGB:BMAIN/9"),
        (2, "XPROGF.DFHCOMMAREA", "XPROGC:CMAIN/7"),
    )


def test_the_budget_that_really_cuts_the_last_crossing_loses_it():
    """The other direction of the same store: one hop does lose ``XPROGF``."""
    found = _converging_walk(1)

    assert "XPROGF.DFHCOMMAREA" not in {one.field_id for one in found.landings}


def test_a_flow_off_two_frontier_entries_is_priced_off_the_cheaper_one():
    """Two *different* names over shared bytes, at different costs, in one level.

    Deduping the level cannot merge these -- ``XPROGC.C-WIDE[0:8]`` and
    ``XPROGC.C-NARROW[4:8]`` are two entries, not one seen twice -- so which of them
    a flow leaving the shared ``[4:8]`` is priced off is entirely ``_from``'s
    choice. The dear one is built first, being flowed rather than crossed.
    """
    declared = (
        _declared("WS-A", 1, ((0, 4),), program="XPROGA"),
        _declared("M0", 1, ((8, 12),), program="XPROGA"),
        _linkage_declared("M1", 1, 0, 4, program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 4, program="XPROGB"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 4, program="XPROGC"),
        _declared("C-WIDE", 1, ((0, 8),), program="XPROGC"),
        _declared("C-NARROW", 1, ((4, 8),), program="XPROGC"),
        _declared("C-SINK", 1, ((16, 20),), program="XPROGC"),
    )
    edges = (
        _edge(
            "WS-A",
            "M0",
            "AMAIN/1",
            "WS-A@working_storage[0:4]",
            "M0@working_storage[8:12]",
            program="XPROGA",
        ),
        _edge(
            "M0",
            "M1",
            "AMAIN/2",
            "M0@working_storage[8:12]",
            "M1@linkage[0:4]",
            program="XPROGA",
        ),
        _edge(
            "DFHCOMMAREA",
            "C-WIDE",
            "CMAIN/1",
            "DFHCOMMAREA@linkage[0:4]",
            "C-WIDE@working_storage[0:8]",
            program="XPROGC",
        ),
        _edge(
            "C-WIDE",
            "C-SINK",
            "CMAIN/2",
            "C-WIDE@working_storage[4:8]",
            "C-SINK@working_storage[16:20]",
            program="XPROGC",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="AMAIN/9",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-A@working_storage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGB",
            node="BMAIN/9",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="DFHCOMMAREA@linkage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/5",
            transfer="LINK",
            callee="XPROGA",
            caller_extent="C-NARROW@working_storage[4:8]",
            callee_extent="M1@linkage[0:4]",
            returns=True,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-A@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    sink = [one for one in found.landings if one.field_id == "XPROGC.C-SINK"]
    assert [(one.hops, one.via) for one in sink] == [(1, "XPROGC:CMAIN/5")]


def _repack_store(write_back: str):
    """The caller passes a key in and reads a result back out of the same window.

    ``write_back`` picks the callee's last MOVE: ``whole`` repacks the record over
    the entire window (``MOVE SUB-REC TO DFHCOMMAREA``, the shape the corpus
    measurement found), ``part`` writes only the result bytes.
    """
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _declared("WS-OUT-KEY", 5, ((0, 4),), program="XPROGA"),
        _declared("WS-IN-RESULT", 5, ((8, 12),), program="XPROGA"),
        _declared("WS-SINK", 1, ((16, 20),), program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGB"),
        _declared("SUB-REC", 1, ((0, 12),), program="XPROGB"),
        _declared("SUB-KEY", 5, ((0, 4),), program="XPROGB"),
        _declared("SUB-RESULT", 5, ((8, 12),), program="XPROGB"),
    )
    whole = write_back == "whole"
    edges = (
        _edge(
            "DFHCOMMAREA",
            "SUB-REC",
            "SUB/1",
            "DFHCOMMAREA@linkage[0:12]",
            "SUB-REC@working_storage[0:12]",
            program="XPROGB",
        ),
        _edge(
            "SUB-KEY",
            "SUB-RESULT",
            "SUB/2",
            "SUB-KEY@working_storage[0:4]",
            "SUB-RESULT@working_storage[8:12]",
            program="XPROGB",
        ),
        _edge(
            "SUB-REC" if whole else "SUB-RESULT",
            "DFHCOMMAREA",
            "SUB/3",
            (
                "SUB-REC@working_storage[0:12]"
                if whole
                else "SUB-RESULT@working_storage[8:12]"
            ),
            "DFHCOMMAREA@linkage[0:12]" if whole else "DFHCOMMAREA@linkage[8:12]",
            program="XPROGB",
        ),
        _edge(
            "WS-IN-RESULT",
            "WS-SINK",
            "MAIN/9",
            "WS-IN-RESULT@working_storage[8:12]",
            "WS-SINK@working_storage[16:20]",
            program="XPROGA",
        ),
    )
    return store_of(declared, edges, (), (_alias_row(node="MAIN/3"),))


def _repack_walk(write_back: str):
    return crossing(
        _repack_store(write_back),
        (byte_range("WS-OUT-KEY@working_storage[0:4]", "XPROGA"),),
        Side.SOURCE,
        depth=6,
        hops=2,
    )


def test_a_partial_write_back_comes_all_the_way_home():
    found = _repack_walk("part")

    assert ("XPROGA.WS-SINK", 2) in {(one.field_id, one.hops) for one in found.landings}


def test_a_whole_record_write_back_does_not_reach_the_callers_sink():
    """The measured corpus shape, and a limitation of the pruning rule rather than a
    fact about the two programs (bead ``nsv``): the repack lands on bytes the inbound
    hop already stood on, so overlap pruning drops it and ``WS-SINK`` is never
    reached. Pinned so that fixing ``nsv`` has to change this expectation.
    """
    found = _repack_walk("whole")

    assert "XPROGA.WS-SINK" not in {one.field_id for one in found.landings}


def test_a_drop_a_later_level_covers_anyway_still_reaches_the_sink():
    """``XPROGC.DFHCOMMAREA[0:8]`` is dropped at the level ``XPROGB:BMAIN/9``
    crosses, and only later does the caller's own crossing land the whole
    ``DFHCOMMAREA@linkage[0:12]`` on it at the same cost and carry on to
    ``XPROGC.C-SINK`` -- so a drop is not a loss until the walk has finished.
    """
    declared = (
        _declared("WS-A", 1, ((0, 4),), program="XPROGA"),
        _declared("WS-M", 1, ((8, 12),), program="XPROGA"),
        _declared("WS-N", 1, ((16, 28),), program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGB"),
        _declared("B-REC", 1, ((0, 8),), program="XPROGB"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGC"),
        _declared("C-SINK", 1, ((16, 20),), program="XPROGC"),
    )
    edges = (
        _edge(
            "WS-A",
            "WS-M",
            "AMAIN/1",
            "WS-A@working_storage[0:4]",
            "WS-M@working_storage[8:12]",
            program="XPROGA",
        ),
        _edge(
            "WS-M",
            "WS-N",
            "AMAIN/2",
            "WS-M@working_storage[8:12]",
            "WS-N@working_storage[16:28]",
            program="XPROGA",
        ),
        _edge(
            "DFHCOMMAREA",
            "B-REC",
            "BMAIN/1",
            "DFHCOMMAREA@linkage[0:4]",
            "B-REC@working_storage[0:8]",
            program="XPROGB",
        ),
        _edge(
            "DFHCOMMAREA",
            "C-SINK",
            "CMAIN/4",
            "DFHCOMMAREA@linkage[4:8]",
            "C-SINK@working_storage[16:20]",
            program="XPROGC",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="AMAIN/8",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-A@working_storage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGB",
            node="BMAIN/8",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="DFHCOMMAREA@linkage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[4:8]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGB",
            node="BMAIN/9",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="B-REC@working_storage[0:8]",
            callee_extent="DFHCOMMAREA@linkage[0:8]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="AMAIN/9",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="WS-N@working_storage[16:28]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-A@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)
    reached = {(one.field_id, str(one.at)): one.hops for one in found.landings}

    assert reached["XPROGC.DFHCOMMAREA", "DFHCOMMAREA@linkage[0:12]"] == 1
    assert reached["XPROGC.C-SINK", "C-SINK@working_storage[16:20]"] == 1


def test_the_walk_crosses_from_a_field_within_the_hop_budget():
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _declared("WS-MID", 1, ((16, 20),), program="XPROGA"),
        _declared("WS-Q", 1, ((24, 28),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGC"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGZ"),
        _declared("Z-SINK", 1, ((16, 20),), program="XPROGZ"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGY"),
    )
    edges = (
        _edge(
            "WS-AREA",
            "WS-MID",
            "MAIN/5",
            "WS-AREA@working_storage[0:4]",
            "WS-MID@working_storage[16:20]",
            program="XPROGA",
        ),
        _edge(
            "WS-MID",
            "WS-Q",
            "MAIN/6",
            "WS-MID@working_storage[16:20]",
            "WS-Q@working_storage[24:28]",
            program="XPROGA",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/1",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="MAIN/9",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="WS-Q@working_storage[24:28]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGZ",
            node="ZMAIN/3",
            transfer="XCTL",
            callee="XPROGY",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=2)

    y_landings = [one for one in found.landings if one.field_id == "XPROGY.DFHCOMMAREA"]
    assert len(y_landings) > 0


def test_landings_are_sorted_by_hops_then_depth_then_field_id():
    declared = (
        _declared("WS-A", 1, ((0, 4),), program="XPROGA"),
        _declared("WS-B", 1, ((8, 12),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGB"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGC"),
    )
    edges = (
        _edge(
            "WS-A",
            "WS-B",
            "MAIN/5",
            "WS-A@working_storage[0:4]",
            "WS-B@working_storage[8:12]",
            program="XPROGA",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-A@working_storage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="MAIN/3",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="WS-B@working_storage[8:12]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-A@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    keys = [(one.hops, one.depth, one.field_id) for one in found.landings]
    assert keys == sorted(keys)


def test_fresh_distinguishes_two_ranges_of_the_same_field():
    declared = (
        _declared("WS-A", 1, ((0, 4),), program="XPROGA"),
        _declared("WS-B", 1, ((8, 12),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGB"),
    )
    edges = (
        _edge(
            "WS-A",
            "WS-B",
            "MAIN/5",
            "WS-A@working_storage[0:4]",
            "WS-B@working_storage[8:12]",
            program="XPROGA",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-A@working_storage[0:4]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="MAIN/3",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-B@working_storage[8:12]",
            callee_extent="DFHCOMMAREA@linkage[4:8]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-A@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    b_landings = [one for one in found.landings if one.field_id == "XPROGB.DFHCOMMAREA"]
    assert len(b_landings) == 2
    assert {one.via for one in b_landings} == {"XPROGA:MAIN/2", "XPROGA:MAIN/3"}


def test_qualified_uppercases_field_names():
    declared = (
        _declared("ws-area", 1, ((0, 12),), program="xproga"),
        _declared("dfhcommarea", 1, ((0, 12),), program="xprogb"),
    )
    edges = ()
    aliases = (
        _alias_row(
            caller="xproga",
            node="main/2",
            transfer="XCTL",
            callee="xprogb",
            caller_extent="ws-area@working_storage[0:12]",
            callee_extent="dfhcommarea@linkage[0:12]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("ws-area@working_storage[0:4]", "xproga"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert any(one.field_id == "XPROGB.DFHCOMMAREA" for one in found.landings)


def _written(out, name: str, payloads) -> None:
    (out / name).write_text(
        "".join(f"{json.dumps(payload)}\n" for payload in payloads), encoding="utf-8"
    )


def test_the_default_answer_does_not_mention_crossing(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())
    _written(out, "edges.jsonl", _two_program_edge_rows())
    _written(out, "aliases.jsonl", (_alias_row(),))

    assert cli(["reaches", "XPROGA.WS-AREA", "--out", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "across calls" not in printed
    assert "XPROGB" not in printed


def test_the_flag_reports_the_hop_and_the_site(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())
    _written(out, "edges.jsonl", _two_program_edge_rows())
    _written(out, "aliases.jsonl", (_alias_row(),))

    assert (
        cli(
            [
                "reaches",
                "XPROGA.WS-AREA",
                "--out",
                str(out),
                "--across-calls",
                "--max-hops",
                "2",
            ]
        )
        == 0
    )

    printed = capsys.readouterr().out
    assert "across calls (depth 6, max 2 hops" in printed
    assert "hop 1" in printed
    assert "via XPROGA:MAIN/2" in printed


def test_a_landing_line_names_the_bytes_it_landed_on(tmp_path, capsys):
    """Two ranges of one field are two answers, and depth is not what tells them
    apart: without the range the rows read as one row printed twice."""
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())
    _written(out, "edges.jsonl", _two_program_edge_rows())
    _written(out, "aliases.jsonl", (_alias_row(),))

    assert cli(["reaches", "XPROGA.WS-AREA", "--out", str(out), "--across-calls"]) == 0

    printed = capsys.readouterr().out
    assert "XPROGB.DFHCOMMAREA  DFHCOMMAREA@linkage[0:12]" in printed


@pytest.mark.parametrize(
    "query", ("writers", "readers", "contains", "within", "overlapping", "extents")
)
def test_a_question_that_cannot_cross_a_call_refuses_the_flag(tmp_path, query):
    """Refused rather than ignored: answering without the flag is indistinguishable
    from a corpus in which no call site shares any bytes."""
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())

    with pytest.raises(SystemExit) as refused:
        cli([query, "XPROGA.WS-AREA", "--out", str(out), "--across-calls"])

    assert refused.value.code == 2


def test_asking_to_cross_zero_hops_is_rejected(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    _written(out, "extents.jsonl", _two_program_extent_rows())

    with pytest.raises(SystemExit):
        cli(
            [
                "reaches",
                "XPROGA.WS-AREA",
                "--out",
                str(out),
                "--across-calls",
                "--max-hops",
                "0",
            ]
        )


def test_deduped_orders_by_cost_before_name():
    """``_deduped``'s order is the published one now that ``_ordered`` is gone, so the
    cheap landing comes first even when its name sorts last: XPROGZ at one hop before
    XPROGB at two."""
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGZ"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGB"),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGZ",
            node="ZMAIN/1",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
    )
    store = store_of(declared, (), (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:12]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert [(one.hops, one.field_id) for one in found.landings] == [
        (1, "XPROGZ.DFHCOMMAREA"),
        (2, "XPROGB.DFHCOMMAREA"),
    ]


def test_fresh_distinguishes_group_and_child_in_linkage():
    """Two declared names over shared bytes in one region, which is the only shape
    that can see ``_fresh``'s ``field_id`` half: ``overlaps`` already demands the same
    program and region, so the group arriving first must not prune its own child."""
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGB"),
        _linkage_declared("COMM-KEY", 5, 0, 4, program="XPROGB"),
        _linkage_declared("COMM-BODY", 5, 4, 12, program="XPROGB"),
    )
    edges = (
        _edge(
            "COMM-BODY",
            "COMM-KEY",
            "SUB/4",
            "COMM-BODY@linkage[4:12]",
            "COMM-KEY@linkage[0:4]",
            program="XPROGB",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:12]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    field_ids = {one.field_id for one in found.landings}
    assert "XPROGB.DFHCOMMAREA" in field_ids
    assert "XPROGB.COMM-KEY" in field_ids


def test_large_number_of_landings_does_not_crash():
    """One caller with more distinct XCTL callees than the interpreter's stack allows a
    landing apiece, at depth 1 and with no cycle: supersession has to be iterative."""
    declared = (_declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),) + tuple(
        _declared("DFHCOMMAREA", 1, ((0, 12),), program=f"XPROG{i:04d}")
        for i in range(1200)
    )
    aliases = tuple(
        _alias_row(
            caller="XPROGA",
            node=f"MAIN/{i}",
            transfer="XCTL",
            callee=f"XPROG{i:04d}",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        )
        for i in range(1200)
    )
    store = store_of(declared, (), (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=1, hops=1)

    assert len(found.landings) == 1200


def test_identical_landing_sets_at_two_budgets_have_identical_costs():
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _declared("WS-MID", 1, ((16, 20),), program="XPROGA"),
        _declared("WS-Q", 1, ((24, 28),), program="XPROGA"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGC"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGZ"),
        _declared("DFHCOMMAREA", 1, ((0, 12),), program="XPROGY"),
    )
    edges = (
        _edge(
            "WS-AREA",
            "WS-MID",
            "MAIN/5",
            "WS-AREA@working_storage[0:4]",
            "WS-MID@working_storage[16:20]",
            program="XPROGA",
        ),
        _edge(
            "WS-MID",
            "WS-Q",
            "MAIN/6",
            "WS-MID@working_storage[16:20]",
            "WS-Q@working_storage[24:28]",
            program="XPROGA",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/1",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="MAIN/9",
            transfer="XCTL",
            callee="XPROGZ",
            caller_extent="WS-Q@working_storage[24:28]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGZ",
            node="ZMAIN/3",
            transfer="XCTL",
            callee="XPROGY",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found_3 = crossing(store, start, Side.SOURCE, depth=6, hops=3)
    found_2 = crossing(store, start, Side.SOURCE, depth=6, hops=2)

    y_3 = [one for one in found_3.landings if one.field_id == "XPROGY.DFHCOMMAREA"]
    y_2 = [one for one in found_2.landings if one.field_id == "XPROGY.DFHCOMMAREA"]
    assert len(y_3) == 1 and len(y_2) == 1
    assert y_3[0].hops == y_2[0].hops


def test_a_cut_crossing_loses_the_callee_only_it_reached():
    """The other direction of the same rule: XPROGD is reachable only through XPROGB,
    so a one-hop budget really does lose it."""
    store = _two_program_store(_alias_row(), _onward_from_the_callee())
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    cut = crossing(store, start, Side.SOURCE, depth=6, hops=1)
    whole = crossing(store, start, Side.SOURCE, depth=6, hops=2)

    assert "XPROGD.DFHCOMMAREA" in {one.field_id for one in whole.landings}
    assert "XPROGD.DFHCOMMAREA" not in {one.field_id for one in cut.landings}


def test_bytes_only_the_refused_crossing_reaches_are_lost_with_it():
    """Sharing some of the refused candidate's bytes is not reaching them.

    Two callers pass windows at different offsets into one callee's commarea: the
    cheap route (``MAIN/9``, one hop) lands ``[0:4]``, the route the cap refuses would
    have landed ``[2:6]``, and ``XPROGB``'s flow leaves ``[4:6]`` -- bytes only the
    refused crossing reaches. So the one-hop budget really loses ``XPROGB.B-SINK``.
    """
    declared = (
        _declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),
        _declared("WS-MID", 1, ((16, 20),), program="XPROGA"),
        _declared("WS-Q", 1, ((24, 28),), program="XPROGA"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 12, program="XPROGC"),
        _linkage_declared("DFHCOMMAREA", 1, 0, 14, program="XPROGB"),
        _declared("B-SINK", 1, ((40, 44),), program="XPROGB"),
    )
    edges = (
        _edge(
            "WS-AREA",
            "WS-MID",
            "MAIN/5",
            "WS-AREA@working_storage[0:4]",
            "WS-MID@working_storage[16:20]",
            program="XPROGA",
        ),
        _edge(
            "WS-MID",
            "WS-Q",
            "MAIN/6",
            "WS-MID@working_storage[16:20]",
            "WS-Q@working_storage[24:28]",
            program="XPROGA",
        ),
        _edge(
            "DFHCOMMAREA",
            "B-SINK",
            "SUB/2",
            "DFHCOMMAREA@linkage[4:6]",
            "B-SINK@working_storage[40:44]",
            program="XPROGB",
        ),
    )
    aliases = (
        _alias_row(
            caller="XPROGA",
            node="MAIN/2",
            transfer="XCTL",
            callee="XPROGC",
            caller_extent="WS-AREA@working_storage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[0:12]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGC",
            node="CMAIN/1",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="DFHCOMMAREA@linkage[0:12]",
            callee_extent="DFHCOMMAREA@linkage[2:14]",
            returns=False,
        ),
        _alias_row(
            caller="XPROGA",
            node="MAIN/9",
            transfer="XCTL",
            callee="XPROGB",
            caller_extent="WS-Q@working_storage[24:28]",
            callee_extent="DFHCOMMAREA@linkage[0:4]",
            returns=False,
        ),
    )
    store = store_of(declared, edges, (), aliases)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    cut = crossing(store, start, Side.SOURCE, depth=3, hops=1)
    whole = crossing(store, start, Side.SOURCE, depth=3, hops=2)

    assert "XPROGB.B-SINK" not in {one.field_id for one in cut.landings}
    assert "XPROGB.B-SINK" in {one.field_id for one in whole.landings}
