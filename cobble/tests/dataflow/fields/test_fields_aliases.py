"""Commarea alias rows: the shared window, its direction, and its dead ends."""

import json
from pathlib import Path

from cobble.dataflow.fields.aliases import (
    CALLEE_HAS_NO_COMMAREA,
    CALLEE_HAS_NO_PARAMETER,
    CALLER_FIELD_UNKNOWN,
    DYNAMIC_TARGET,
    EMPTY_WINDOW,
    NO_COMMAREA_OPERAND,
    NOT_IN_CACHE,
    UNREADABLE,
    commarea_aliases,
)
from cobble.dataflow.fields import aliases
from cobble.dataflow.fields.side_tables import alias_row
from cobol_asg.asg_types import CobolASG
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId


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
    area_children: tuple[dict, ...],
    statement: dict,
    program_of,
    field,
    ahead: tuple[dict, ...] = (),
) -> CobolASG:
    return program_of(
        [statement],
        data_fields=[
            *ahead,
            {**field(1, "WS-AREA"), "children": list(area_children)},
        ],
    )


def _callee_json(directory: Path, program: str, size: int, field) -> None:
    _callee_linkage(directory, program, [field(1, "DFHCOMMAREA", pic=f"X({size})")])


def _callee_linkage(directory: Path, program: str, linkage_fields: list) -> None:
    asg_dict = {
        "program_id": program,
        "paragraphs": [],
        "linkage_fields": linkage_fields,
    }
    (directory / f"{program}.json").write_text(json.dumps(asg_dict), encoding="utf-8")


def _rows(asg, asg_dir: Path, index_of):
    return commarea_aliases(asg, index_of(asg), asg_dir)


def test_link_shares_the_whole_area_when_both_sides_agree(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, field)
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
    _callee_json(tmp_path, "XPROGB", 8, field)
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


def test_the_shorter_side_is_the_callers_when_the_caller_declares_less(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, field)
    asg = _caller(
        (
            field(5, "WS-KEY", pic="X(4)", offset=0),
            field(5, "WS-REST", pic="X(4)", offset=4),
        ),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.caller_extent == "WS-AREA@working_storage[0:8]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:8]"


def test_the_callee_window_starts_at_zero_wherever_the_callers_area_sits(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, field)
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
        ahead=(
            {
                **field(1, "WS-HEADER"),
                "children": [field(5, "WS-STAMP", pic="X(6)", offset=0)],
            },
        ),
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.caller_extent == "WS-AREA@working_storage[6:18]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:12]"


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
    _callee_json(tmp_path, "XPROGB", 12, field)
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
    assert row.callee == "XPROGZ"
    assert (row.caller_extent, row.callee_extent) == ("", "")


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
    assert row.callee == ""


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
    """Still names the callee: nothing is shared, and which program was handed
    nothing is a fact the site states literally."""
    _callee_json(tmp_path, "XPROGB", 12, field)
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
    assert row.callee == "XPROGB"


def test_an_argument_past_the_callees_parameters_is_a_named_dead_end(
    tmp_path, program_of, field, index_of
):
    (tmp_path / "XPROGB.json").write_text(
        json.dumps(
            {
                "program_id": "XPROGB",
                "linkage_fields": [field(1, "LK-A", pic="X(12)")],
                "procedure_using": [{"name": "LK-A", "type": "REFERENCE"}],
            }
        ),
        encoding="utf-8",
    )
    asg = _caller(
        (field(5, "WS-ID", pic="X(12)", offset=0),),
        {
            "type": "CALL",
            "program": "'XPROGB'",
            "using": [{"name": "WS-AREA"}, {"name": "WS-AREA"}],
        },
        program_of,
        field,
    )

    assert [
        (row.caller_extent, row.callee_extent, row.returns, row.reason)
        for row in _rows(asg, tmp_path, index_of)
    ] == [
        ("WS-AREA@working_storage[0:12]", "LK-A@linkage[0:12]", True, ""),
        ("", "", False, CALLEE_HAS_NO_PARAMETER),
    ]


def test_the_row_keys_on_the_site_and_the_window(tmp_path, program_of, field, index_of):
    _callee_json(tmp_path, "XPROGB", 12, field)
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


def test_a_commarea_the_caller_never_declared_is_a_named_dead_end(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, field)
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGB", "WS-ELSEWHERE"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason == CALLER_FIELD_UNKNOWN
    assert row.callee == "XPROGB"
    assert (row.caller_extent, row.callee_extent) == ("", "")


def test_a_qualified_commarea_resolves_through_its_of_chain(
    tmp_path, program_of, field, index_of
):
    _callee_json(tmp_path, "XPROGB", 12, field)
    asg = program_of(
        [_link("XPROGB", "WS-AREA OF WS-BLOCK")],
        data_fields=[
            {
                **field(1, "WS-BLOCK"),
                "children": [
                    {
                        **field(5, "WS-AREA", offset=0),
                        "children": [field(10, "WS-KEY", pic="X(12)", offset=0)],
                    }
                ],
            }
        ],
    )

    (row,) = commarea_aliases(asg, index_of(asg), tmp_path)

    assert row.reason == ""
    assert row.caller_extent == "WS-AREA@working_storage[0:12]"
    assert row.callee_extent == "DFHCOMMAREA@linkage[0:12]"


def test_a_zero_byte_window_is_a_named_dead_end_not_an_alias(
    tmp_path, program_of, field, index_of
):
    _callee_linkage(tmp_path, "XPROGB", [field(1, "DFHCOMMAREA")])
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason == EMPTY_WINDOW
    assert (row.caller_extent, row.callee_extent) == ("", "")


def test_a_callee_the_deserialiser_rejects_is_a_named_dead_end(
    tmp_path, program_of, field, index_of
):
    (tmp_path / "XPROGB.json").write_text('{"program_id": "XPROG', encoding="utf-8")
    asg = _caller(
        (field(5, "WS-KEY", pic="X(12)", offset=0),),
        _link("XPROGB", "WS-AREA"),
        program_of,
        field,
    )

    (row,) = _rows(asg, tmp_path, index_of)

    assert row.reason.startswith(UNREADABLE)
    assert row.callee == "XPROGB"
    assert (row.caller_extent, row.callee_extent) == ("", "")


def test_the_cache_keeps_a_callees_windows_and_not_its_layout(tmp_path, field):
    _callee_linkage(
        tmp_path,
        "XPROGT",
        [
            {
                **field(1, "DFHCOMMAREA"),
                "children": [
                    field(5, "LK-NAME", pic="X(8)", offset=0),
                    {**field(5, "LK-ROW", pic="X(4)", offset=8), "occurs": 1000},
                ],
            },
            field(1, "LK-PARM", pic="X(6)"),
        ],
    )

    assert aliases._callee_linkage(tmp_path, "XPROGT") == aliases._Linkage(
        commarea=aliases._Callee(
            extent=FieldExtent(
                RegionId.LINKAGE, 0, 4008, Precision.EXACT, "DFHCOMMAREA"
            )
        ),
        parameters=(),
    )
