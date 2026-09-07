"""Commarea alias rows: the shared window, its direction, and its dead ends."""

import json
from pathlib import Path

from cobble.dataflow.fields.aliases import (
    CALLEE_HAS_NO_COMMAREA,
    CALL_USING,
    DYNAMIC_TARGET,
    NOT_IN_CACHE,
    NO_COMMAREA_OPERAND,
    commarea_aliases,
)
from cobble.dataflow.fields.side_tables import alias_row


def _link(program: str, area: str) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {
            "PROGRAM": {"text": f"'{program}'", "is_literal": True},
            "COMMAREA": {"text": area, "is_literal": False},
        },
    }


def _caller(
    area_children: tuple[dict, ...], statement: dict, program_of, field
) -> dict:
    return program_of(
        [statement],
        data_fields=[{**field(1, "WS-AREA"), "children": list(area_children)}],
    )


def _callee_json(directory: Path, program: str, size: int, program_of, field) -> None:
    asg_dict = {
        "program_id": program,
        "paragraphs": [],
        "linkage_fields": [field(1, "DFHCOMMAREA", pic=f"X({size})")],
    }
    (directory / f"{program}.json").write_text(json.dumps(asg_dict), encoding="utf-8")


def _rows(asg, asg_dir: Path, index_of):
    return commarea_aliases(asg, index_of(asg), asg_dir)


def test_link_shares_the_whole_area_when_both_sides_agree(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, program_of, field)
    asg = _caller(
        (
            field(5, "WS-KEY", pic="X(4)", offset=0),
            field(5, "WS-REST", pic="X(8)", offset=4),
        ),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.callee == "XPROGB"
    assert row.caller_extent == "WS-AREA@working_storage[0:12]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:12]"
    assert row.returns is True
    assert row.reason == ""


def test_the_window_narrows_to_the_shorter_side(tmp_path, program_of, field, index_of):
    _callee_json(tmp_path, "XPROGB", 8, program_of, field)
    asg = _caller(
        (
            field(5, "WS-KEY", pic="X(4)", offset=0),
            field(5, "WS-REST", pic="X(8)", offset=4),
        ),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.caller_extent == "WS-AREA@working_storage[0:8]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:8]"


def _xctl(program: str, area: str) -> dict:
    return {
        "type": "EXEC_CICS",
        "verb": "XCTL",
        "options": {
            "PROGRAM": {"text": f"'{program}'", "is_literal": True},
            "COMMAREA": {"text": area, "is_literal": False},
        },
    }


def test_xctl_never_returns_so_the_alias_is_inbound_only(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, program_of, field)
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _xctl("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.returns is False
    assert row.transfer == "XCTL"


def test_an_absent_callee_is_a_named_dead_end(tmp_path, program_of, field, index_of):
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGZ", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason == NOT_IN_CACHE
    assert (row.callee, row.caller_extent, row.callee_extent) == ("", "", "")


def test_a_dynamic_target_is_a_named_dead_end(tmp_path, program_of, field, index_of):
    statement = {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {
            "PROGRAM": {"text": "WS-TARGET", "is_literal": False},
            "COMMAREA": {"text": "WS-AREA", "is_literal": False},
        },
    }
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),), statement, program_of, field
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason == DYNAMIC_TARGET


def test_a_callee_without_a_commarea_is_a_named_dead_end(
    tmp_path, program_of, field, index_of
):
    empty = {
        "program_id": "XPROGB",
        "paragraphs": [],
        "linkage_fields": [],
    }
    (tmp_path / "XPROGB.json").write_text(json.dumps(empty), encoding="utf-8")
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason == CALLEE_HAS_NO_COMMAREA


def test_a_link_without_a_commarea_shares_nothing(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, program_of, field)
    statement = {
        "type": "EXEC_CICS",
        "verb": "LINK",
        "options": {"PROGRAM": {"text": "'XPROGB'", "is_literal": True}},
    }
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),), statement, program_of, field
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason == NO_COMMAREA_OPERAND


def test_a_call_site_is_refused_rather_than_guessed():
    from cobble.dataflow.fields.aliases import _refused
    from cobble.dataflow.srccfg.link import CallSite

    site = CallSite(
        caller="PROGA",
        node="MAIN/1",
        transfer="CALL",
        program="XPROGB",
        resolved=True,
        commarea="WS-AREA",
    )

    assert _refused(site) == CALL_USING


def test_the_row_keys_on_the_site_and_the_window(tmp_path, program_of, field, index_of):
    _callee_json(tmp_path, "XPROGB", 12, program_of, field)
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)
    key, payload = alias_row(row)

    assert key == f"PROGA\x00{row.node}\x00WS-AREA@working_storage[0:12]"
    assert json.loads(payload)["returns"] is True
