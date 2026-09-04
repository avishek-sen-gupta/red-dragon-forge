"""Cross-checks between the bridge's offsets and this package's widths.

``record_gaps`` is only useful if the pairs it compares really are storage
neighbours, so the cases here are about which fields count as siblings.
"""

from cobol_asg.asg_types import CobolField

from cobble.dataflow.layout import Record, record_cells
from cobble.dataflow.layout_check import record_gaps


def _field(name: str, level: int, pic: str, offset: int, **kwargs) -> CobolField:
    return CobolField(
        name=name, level=level, pic=pic, usage="DISPLAY", offset=offset, **kwargs
    )


def _group(name: str, offset: int, child: CobolField) -> CobolField:
    return _field(name, 5, "", offset, children=[child])


def _record(root: CobolField) -> Record:
    cells = record_cells(root)
    return Record(name=root.name, origin="FILE", size=cells[0].length, cells=cells)


# One program's shape: RECE-NUM-DATA-FLAT is declared twice, with other groups in
# between, so the last child of the first one ends 6 bytes before the first child
# of the second begins. Grouping children by qualified name puts those two in one
# pseudo-group and reports the intervening bytes as a hole.
_DUPLICATE_NAMES = _field(
    "LAYOUT1-REC",
    1,
    "",
    0,
    children=[
        _group(
            "RECE-NUM-DATA-FLAT", 0, _field("RECE-NUM-APP-UNIT", 10, "X(4)", 0)
        ),
        _group("RECE-NUM-DATA-BLK", 4, _field("RECE-NUM-DATA-MAIN", 10, "X(6)", 0)),
        _group("RECE-NUM-DATA-FLAT", 10, _field("RECE-NUM-DATA-LEVEL", 10, "X(2)", 0)),
    ],
)


def test_reused_group_name_does_not_make_two_groups_look_like_one() -> None:
    assert record_gaps(_record(_DUPLICATE_NAMES)) == ()


# What the check is actually for: the bridge advanced past a COMP field by its
# digit count, so the field after it is 2 bytes further on than its width allows.
_MISPLACED = _field(
    "RECC-ROW",
    1,
    "",
    0,
    children=[
        CobolField(name="RECC-QTY", level=5, pic="S9(4)", usage="COMP", offset=0),
        _field("RECC-CDE", 5, "X(3)", 4),
    ],
)


def test_a_field_the_bridge_placed_past_its_predecessors_width_is_reported() -> None:
    (gap,) = record_gaps(_record(_MISPLACED))

    assert (gap.left, gap.right) == ("RECC-QTY", "RECC-CDE")
    assert (gap.left_end, gap.right_start) == (2, 4)


# A table and the field after it. The bridge places the sibling past all 190 rows,
# so measuring it against one row would report a 9828-byte hole in every record
# that has a table in it.
_TABLE = _field(
    "RECC-BLK",
    1,
    "",
    0,
    children=[
        _field(
            "RECC-ROW",
            5,
            "",
            0,
            occurs=190,
            children=[_field("RECC-NUM", 10, "X(52)", 0)],
        ),
        _field("RECC-END", 5, "X(1)", 9880),
    ],
)


def test_a_field_after_a_table_is_measured_against_all_of_its_rows() -> None:
    assert record_gaps(_record(_TABLE)) == ()


def test_a_hole_inside_a_table_row_is_reported_once_not_once_per_row() -> None:
    row = _field(
        "RECC-ROW",
        5,
        "",
        0,
        occurs=190,
        children=[
            _field("RECC-NUM", 10, "X(6)", 0),
            _field("RECC-CDE", 10, "X(2)", 8),  # 6 wide, so 2 bytes unaccounted for
        ],
    )
    (gap,) = record_gaps(_record(_field("RECC-BLK", 1, "", 0, children=[row])))

    assert (gap.left, gap.right) == ("RECC-NUM", "RECC-CDE")
    assert (gap.left_end, gap.right_start) == (6, 8)
