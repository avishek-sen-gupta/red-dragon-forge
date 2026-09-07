"""Crossing a commarea: the rebase, its direction, and where it stops."""

import json

import pytest
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.query import (
    MAX_STOPS_PRINTED,
    Side,
    cli,
    crossing,
    store_of,
)
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
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=0)

    assert _landings(found) == ()
    assert "hop limit 0" in found.stops


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


def test_the_hop_limit_is_a_named_stop():
    store = _two_program_store(_alias_row(), _onward_from_the_callee())
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=1)

    assert max(one.hops for one in found.landings) == 1
    assert not any(one.field_id.startswith("XPROGD") for one in found.landings)
    assert "hop limit 1" in found.stops


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
    assert "hop limit" not in " ".join(found.stops)


def test_a_dead_end_in_a_program_the_walk_entered_is_a_named_stop():
    blocked = _alias_row(
        caller="XPROGB",
        node="SUB/7",
        callee="",
        caller_extent="",
        callee_extent="",
        returns=False,
        reason="callee-not-in-cache",
    )
    store = _two_program_store(_alias_row(), blocked)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    assert "callee-not-in-cache at XPROGB" in found.stops


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
    assert "hop limit 2" not in found.stops


def test_the_last_levels_dead_ends_are_named():
    blocked = _alias_row(
        caller="XPROGB",
        node="SUB/7",
        callee="",
        caller_extent="",
        callee_extent="",
        returns=False,
        reason="callee-not-in-cache",
    )
    store = _two_program_store(_alias_row(), blocked)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=1, hops=3)

    assert "callee-not-in-cache at XPROGB" in found.stops


def test_stops_are_deduped():
    blocked1 = _alias_row(
        caller="XPROGB",
        node="SUB/7",
        callee="",
        caller_extent="",
        callee_extent="",
        returns=False,
        reason="callee-not-in-cache",
    )
    blocked2 = _alias_row(
        caller="XPROGB",
        node="SUB/8",
        callee="",
        caller_extent="",
        callee_extent="",
        returns=False,
        reason="callee-not-in-cache",
    )
    store = _two_program_store(_alias_row(), blocked1, blocked2)
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=3)

    count = sum(1 for stop in found.stops if stop == "callee-not-in-cache at XPROGB")
    assert count == 1


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


def test_the_flag_reports_the_hop_the_site_and_the_stop(tmp_path, capsys):
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
    assert "stopped:" in printed


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


def test_identical_landing_sets_at_two_budgets_have_identical_stops():
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
    assert found_3.stops == found_2.stops


def test_cut_crossing_still_reports_hop_limit():
    """The other direction of the same rule: XPROGD is reachable only through XPROGB,
    so a one-hop budget really does lose it and has to say so."""
    store = _two_program_store(_alias_row(), _onward_from_the_callee())
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    cut = crossing(store, start, Side.SOURCE, depth=6, hops=1)
    whole = crossing(store, start, Side.SOURCE, depth=6, hops=2)

    assert "XPROGD.DFHCOMMAREA" in {one.field_id for one in whole.landings}
    assert "XPROGD.DFHCOMMAREA" not in {one.field_id for one in cut.landings}
    assert "hop limit 1" in cut.stops
    assert "hop limit 2" not in whole.stops


def test_a_partly_covered_blocked_crossing_is_still_a_hop_limit():
    """Sharing some of the refused candidate's bytes is not reaching them.

    Two callers pass windows at different offsets into one callee's commarea: the
    cheap route (``MAIN/9``, one hop) lands ``[0:4]``, the route the cap refuses would
    have landed ``[2:6]``, and ``XPROGB``'s flow leaves ``[4:6]`` -- bytes only the
    refused crossing reaches. So the one-hop budget really loses ``XPROGB.B-SINK``.

    Whole-tuple assertions rather than membership, because the published order is
    itself user-visible: the coarser budget first, then the hop cap.
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
    assert cut.stops == ("depth limit 3", "hop limit 1")
    assert whole.stops == ("depth limit 3",)


WITHHELD_STOPS = 10


def _one_dead_end_per_callee(count: int):
    """``count`` callees the walk lands in, each with a dead end of its own.

    Distinct callers, because ``_stops`` dedups on the whole ``reason at caller``
    string, so one caller repeated is one stop however many of its sites are dead.
    And live crossings into them, because a dead end is only reported for a program
    the frontier stands in.
    """
    return tuple(
        row
        for i in range(count)
        for row in (
            _alias_row(
                caller="XPROGA",
                node=f"MAIN/{i}",
                transfer="XCTL",
                callee=f"XPROG{i:04d}",
                caller_extent="WS-AREA@working_storage[0:12]",
                callee_extent="DFHCOMMAREA@linkage[0:12]",
                returns=False,
            ),
            _alias_row(
                caller=f"XPROG{i:04d}",
                node="SUB/1",
                callee="",
                caller_extent="",
                callee_extent="",
                returns=False,
                reason="callee-not-in-cache",
            ),
        )
    )


def _artefact_of(out, aliases) -> None:
    out.mkdir()
    _written(
        out,
        "extents.jsonl",
        (_declared("WS-AREA", 1, ((0, 12),), program="XPROGA"),),
    )
    _written(out, "edges.jsonl", ())
    _written(out, "aliases.jsonl", aliases)


def test_many_stops_prints_cap_worth_of_lines(tmp_path, capsys):
    out = tmp_path / "out"
    _artefact_of(out, _one_dead_end_per_callee(MAX_STOPS_PRINTED + WITHHELD_STOPS))

    assert cli(["reaches", "XPROGA.WS-AREA", "--out", str(out), "--across-calls"]) == 0

    printed = capsys.readouterr().out
    stop_lines = [
        line
        for line in printed.split("\n")
        if line.strip().startswith("callee-not-in-cache")
    ]
    assert len(stop_lines) == MAX_STOPS_PRINTED


def test_overflow_count_equals_stops_withheld(tmp_path, capsys):
    out = tmp_path / "out"
    _artefact_of(out, _one_dead_end_per_callee(MAX_STOPS_PRINTED + WITHHELD_STOPS))

    assert cli(["reaches", "XPROGA.WS-AREA", "--out", str(out), "--across-calls"]) == 0

    printed = capsys.readouterr().out
    assert f"... and {WITHHELD_STOPS} more" in printed
