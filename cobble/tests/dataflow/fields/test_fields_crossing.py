"""Crossing a commarea: the rebase, its direction, and where it stops."""

import json

import pytest
from cobble.dataflow.fields.extent_text import byte_range
from cobble.dataflow.fields.query import cli, store_of


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


from cobble.dataflow.fields.query import Side, crossing

from test_fields_query import _declared, _edge, _range


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


def test_the_hop_limit_is_a_named_stop():
    store = _two_program_store()
    start = (byte_range("WS-AREA@working_storage[0:4]", "XPROGA"),)

    found = crossing(store, start, Side.SOURCE, depth=6, hops=1)

    assert max(one.hops for one in found.landings) == 1
    assert "hop limit 1" in found.stops


def test_a_cycle_stops_as_a_cycle_not_as_a_hop_limit():
    """XPROGA links XPROGB links XPROGA: the walk must terminate and say why."""
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

    assert any(stop.startswith("cycle at ") for stop in found.stops)
    assert "hop limit 6" not in found.stops


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
