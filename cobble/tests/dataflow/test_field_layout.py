"""Byte extents for record fields.

Every case here is taken from a real corpus rather than invented, because the
point of the module is to agree with what the real compiler laid out: one
commarea record is 10000 bytes, and one VSAM record exercises OCCURS expansion
and REDEFINES together.
"""

from cobol_asg.asg_types import CobolField

from cobble.dataflow.layout import Record, record_cells, section_records


def _field(name: str, level: int, pic: str, offset: int, **kwargs) -> CobolField:
    return CobolField(
        name=name, level=level, pic=pic, usage="DISPLAY", offset=offset, **kwargs
    )


def _by_name(cells, name: str):
    return next(cell for cell in cells if cell.name == name)


def _named(cells, name: str) -> tuple:
    return tuple(cell for cell in cells if cell.name == name)


def _at(cells, name: str, *index: int):
    return next(c for c in cells if c.name == name and c.index == index)


def _record(root: CobolField) -> Record:
    cells = record_cells(root)
    return Record(name=root.name, origin="FILE", size=cells[0].length, cells=cells)


# One commarea's user-summary table: 190 rows of 52 bytes starting at offset 85.
_SUMMARY_ROW = (
    _field("WS-COMM-NUM-USER-ID", 10, "X(06)", 0),
    _field("WS-FIL05", 10, "X(01)", 6),
    _field("WS-COMM-NAME-PERSON", 10, "X(35)", 7),
    _field("WS-FIL06", 10, "X(01)", 42),
    _field("WS-COMM-NUM-ROLE", 10, "X(02)", 43),
    _field("WS-FIL07", 10, "X(01)", 45),
    _field("WS-COMM-NUM-CODE", 10, "X(05)", 46),
    _field("WS-FIL08", 10, "X(01)", 51),
)

_COMM = _field(
    "WS-COMM-COMMAREA",
    1,
    "",
    16,  # cumulative within WORKING-STORAGE, and irrelevant to the record
    children=[
        _field("WS-COMM-ERR-CDE", 5, "X(04)", 0),
        _field("WS-FIL01", 5, "X(01)", 4),
        _field("WS-COMM-ERR-MSG", 5, "X(66)", 5),
        _field("WS-FIL02", 5, "X(01)", 71),
        _field("WS-COMM-NUM-ORG-ID", 5, "X(08)", 72),
        _field("WS-FIL03", 5, "X(01)", 80),
        _field("WS-COMM-QTY-COUNT", 5, "9(03)", 81),
        _field("WS-FIL04", 5, "X(01)", 84),
        _field(
            "WS-COMM-DATA-TABLE",
            5,
            "",
            85,
            occurs=190,
            element_size=52,
            children=list(_SUMMARY_ROW),
        ),
        _field("WS-FIL09", 5, "X(01)", 9965),
        _field("FILLER_1", 5, "X(34)", 9966),
    ],
)


def test_record_starts_its_own_coordinate_space_at_zero() -> None:
    cells = record_cells(_COMM)

    assert _by_name(cells, "WS-COMM-COMMAREA").start == 0
    assert _by_name(cells, "WS-COMM-ERR-MSG").start == 5


def test_group_size_is_how_far_its_widest_child_reaches() -> None:
    # The commarea one program declares as 01 DFHCOMMAREA PIC X(10000).
    assert _by_name(record_cells(_COMM), "WS-COMM-COMMAREA").length == 10000


def test_every_row_of_a_table_becomes_a_cell_at_its_own_offset() -> None:
    rows = _named(record_cells(_COMM), "WS-COMM-DATA-TABLE")

    assert len(rows) == 190
    assert (rows[0].start, rows[0].index) == (85, (1,))
    assert (rows[189].start, rows[189].index) == (85 + 189 * 52, (190,))
    # Each cell is one row wide; the row count stays on the cell so that the field
    # after the table can be checked against all 9880 bytes.
    assert {r.length for r in rows} == {52}
    assert {r.occurs for r in rows} == {190}


def test_a_field_inside_a_table_is_placed_absolutely_in_its_own_row() -> None:
    cells = record_cells(_COMM)

    # WS-COMM-NAME-PERSON(47): row 47 begins 46 strides in, the field 7 bytes into it.
    assert _at(cells, "WS-COMM-NAME-PERSON", 47).start == 85 + 46 * 52 + 7
    assert len(_named(cells, "WS-COMM-NAME-PERSON")) == 190


def test_a_field_outside_the_table_is_placed_after_all_of_its_rows() -> None:
    tail = _by_name(record_cells(_COMM), "WS-FIL09")

    assert (tail.start, tail.index) == (9965, ())


def test_every_occurrence_of_one_declaration_shares_its_decl() -> None:
    cells = record_cells(_COMM)
    staff = _named(cells, "WS-COMM-NAME-PERSON")

    # What a variable subscript resolves to: WS-COMM-NAME-PERSON(WS-IDX) is every
    # cell with this decl, because nothing here can know WS-IDX.
    assert len({c.decl for c in staff}) == 1
    assert _by_name(cells, "WS-COMM-NUM-ROLE").decl != staff[0].decl


# One record: a table inside a table. RECA-MTH-AMT both has OCCURS and sits
# under one, so it takes two subscripts, not one.
_RECA = _field(
    "REC2-REC",
    1,
    "",
    0,
    children=[
        _field(
            "RECA-ID-AMT",
            5,
            "",
            0,
            occurs=12,
            children=[
                _field("RECA-NUM-ID", 10, "X(09)", 0),
                _field("RECA-FIL101", 10, "X(01)", 9),
                _field(
                    "RECA-MTH-AMT",
                    10,
                    "",
                    10,
                    occurs=12,
                    children=[
                        _field("RECA-NUM-MONTH", 20, "X(06)", 0),
                        _field("RECA-FIL201", 20, "X(01)", 6),
                        _field("RECA-NUM-AMT", 20, "9(05)", 7),
                        _field("RECA-FIL202", 20, "X(01)", 12),
                    ],
                ),
                _field(
                    "RECA-STATUS",
                    10,
                    "",
                    166,
                    children=[
                        _field("RECA-DATE-STATUS", 20, "X(08)", 0),
                        _field("RECA-FIL203", 20, "X(01)", 8),
                    ],
                ),
            ],
        )
    ],
)


def test_a_table_inside_a_table_multiplies_out_to_one_cell_per_pair() -> None:
    cells = record_cells(_RECA)

    assert len(_named(cells, "RECA-ID-AMT")) == 12
    assert len(_named(cells, "RECA-MTH-AMT")) == 12 * 12
    assert len(_named(cells, "RECA-NUM-AMT")) == 12 * 12


def test_two_subscripts_are_needed_inside_a_nested_table() -> None:
    cells = record_cells(_RECA)

    # RECA-NUM-AMT(3, 7): outer row 3 at 2*175, inner row 7 at 10 + 6*13 into it.
    income = _at(cells, "RECA-NUM-AMT", 3, 7)
    assert income.start == 2 * 175 + 10 + 6 * 13 + 7
    assert len(income.index) == 2
    # A field outside the inner table still takes one subscript, not two.
    assert _at(cells, "RECA-NUM-ID", 3).start == 2 * 175


def test_the_field_after_a_nested_table_follows_all_of_its_rows() -> None:
    cells = record_cells(_RECA)

    # The inner table covers 10..166 of its row, so its sibling starts at 166 even
    # though each inner cell measures 13 bytes.
    assert _at(cells, "RECA-STATUS", 1).start == 10 + 12 * 13
    assert _at(cells, "RECA-STATUS", 12).start == 11 * 175 + 166


def test_path_qualifies_a_field_by_its_enclosing_groups() -> None:
    assert _by_name(record_cells(_COMM), "WS-COMM-NAME-PERSON").path == (
        "WS-COMM-COMMAREA",
        "WS-COMM-DATA-TABLE",
        "WS-COMM-NAME-PERSON",
    )


# One record's 30-byte security area, aliased by a 30x1 table of the same length.
_RECD = _field(
    "LAYOUT1-REC",
    1,
    "",
    0,
    children=[
        _field("RECD-NUM-ORG-ID", 5, "X(8)", 0),
        _field("RECD-NUM-ROLE", 5, "X(2)", 8),
        _field("FILLER", 5, "X(1)", 10),
        _field("RECD-NUM-USER-ID", 5, "X(6)", 11),
        _field("FILLER_1", 5, "X(1)", 17),
        _field("RECD-DATA", 5, "X(30)", 18),
        _field(
            "RECD-DATA-TAG",
            5,
            "X(1)",
            18,
            occurs=30,
            element_size=1,
            redefines="RECD-DATA",
        ),
        _field("RECD-NAME-PERSON", 5, "X(66)", 48),
        _field("RECD-NUM-PERSON-CODE", 5, "X(5)", 114),
        _field("RECD-CDE-OT-CODE", 5, "X(1)", 119),
    ],
)


def test_a_table_that_redefines_a_field_lands_inside_the_bytes_it_aliases() -> None:
    record = _record(_RECD)
    security = _by_name(record.cells, "RECD-DATA")
    tags = _named(record.cells, "RECD-DATA-TAG")

    assert (security.start, security.length) == (18, 30)
    # A write through RECD-DATA-TAG(7) has to be visible to a read of
    # RECD-DATA, which needs no reconciling now that both are ranges in one
    # space: byte 24 is simply in both.
    assert (tags[6].start, tags[6].length) == (24, 1)
    assert (tags[0].start, tags[29].start) == (18, 47)
    assert record.size == 120


def test_a_redefinition_does_not_extend_the_group_it_aliases() -> None:
    # 30 rows of 1 byte over an existing 30, so RECD-NAME-PERSON still starts at 48.
    assert _by_name(record_cells(_RECD), "RECD-NAME-PERSON").start == 48


# One reply buffer, cut down. Three alternative output layouts over one
# piece of storage, one per calling transaction, each with a table of its own -- so
# the table is not the redefining item, its grandparent is. That ancestry form is
# the common one: 330 of the 391 such tables in a 300-program sample.
_RECB_ALT = _field(
    "RECB-NUM-DATA",
    5,
    "",
    0,
    children=[
        _field(
            "RECB-NUM-INPUT",
            10,
            "",
            0,
            children=[_field("RECB-NUM-BLK", 15, "X(05)", 0)],
        ),
        _field(
            "RECB-NUM-OUTPUT",
            10,
            "",
            5,
            redefines="RECB-NUM-INPUT",
            children=[
                _field("RECB-NUM-ERROR", 15, "X(04)", 0),
                _field(
                    "RECB-NUM-TRANS-A",
                    15,
                    "",
                    4,
                    children=[
                        _field(
                            "RECB-NUM-REL-CNTRCT",
                            20,
                            "",
                            0,
                            occurs=400,
                            children=[
                                _field("RECB-NUM-REL-ID", 25, "X(08)", 0),
                                _field("RECB-NUM-AVAIL-FLAG", 25, "X(01)", 8),
                            ],
                        )
                    ],
                ),
            ],
        ),
    ],
)


def test_a_table_under_a_redefinition_is_placed_from_the_bytes_it_aliases() -> None:
    cells = record_cells(_RECB_ALT)
    rows = _named(cells, "RECB-NUM-REL-CNTRCT")

    # RECB-NUM-INPUT addresses these bytes flat, two levels above the table, so the
    # table is anchored at 4 -- inside the input view -- and not at 5+4.
    assert len(rows) == 400
    assert (rows[0].start, rows[0].length) == (4, 9)
    assert _at(cells, "RECB-NUM-REL-ID", 7).start == 4 + 6 * 9
    assert _at(cells, "RECB-NUM-AVAIL-FLAG", 1).start == 4 + 8


def test_alternative_layouts_over_one_buffer_overlap_by_construction() -> None:
    cells = record_cells(_RECB_ALT)
    blk = _by_name(cells, "RECB-NUM-BLK")

    # The 5 bytes one program fills as RECB-NUM-BLK are the same 5 a reply reads back
    # as RECB-NUM-ERROR plus the first byte of row 1 -- one space, so plainly so.
    assert (blk.start, blk.end) == (0, 5)
    assert _by_name(cells, "RECB-NUM-ERROR").start < blk.end
    assert _at(cells, "RECB-NUM-REL-ID", 1).start < blk.end


# One program's buffer: a redefinition OF a redefinition, which the bridge
# places sequentially -- it reports RECF-ALT-LAYOUT2 at 3800 (= 300 + 3500)
# instead of at 300, where the compiler puts it.
_RECF_CHAIN = _field(
    "RECF-NUM-CONTENT",
    5,
    "",
    0,
    children=[
        _field("RECF-FIXED", 10, "X(300)", 0),
        _field("RECF-ALT-LAYOUT1", 10, "X(3500)", 300),
        _field(
            "RECF-ALT-LAYOUT2",
            10,
            "X(3500)",
            3800,
            redefines="RECF-ALT-LAYOUT1",
        ),
        _field(
            "RECF-ALT-LAYOUT3",
            10,
            "X(4000)",
            7300,
            redefines="RECF-ALT-LAYOUT2",
        ),
    ],
)


def test_a_redefinition_of_a_redefinition_resolves_to_the_original_offset() -> None:
    cells = record_cells(_RECF_CHAIN)

    assert _by_name(cells, "RECF-ALT-LAYOUT2").start == 300
    assert _by_name(cells, "RECF-ALT-LAYOUT3").start == 300


def test_group_is_wide_enough_for_the_longest_redefinition() -> None:
    # 300 + 4000, from the longest view, not 300 + 3500 from the declared one.
    assert _by_name(record_cells(_RECF_CHAIN), "RECF-NUM-CONTENT").length == 4300


# One program declares RECE-NUM-DATA-FLAT twice, with a different subtree under
# each. COBOL allows it as long as references qualify, so a field's identity
# cannot be its qualified name.
_RECE_DUP = _field(
    "LAYOUT2-REC",
    1,
    "",
    0,
    children=[
        _field(
            "RECE-NUM-DATA-FLAT",
            5,
            "",
            0,
            children=[_field("RECE-NUM-APP-UNIT", 10, "X(1)", 0)],
        ),
        _field(
            "RECE-NUM-DATA-FLAT",
            5,
            "",
            1,
            children=[_field("RECE-NUM-DATA-LEVEL", 10, "X(2)", 0)],
        ),
    ],
)


def test_two_groups_of_the_same_name_stay_distinct() -> None:
    cells = record_cells(_RECE_DUP)
    first, second = (c for c in cells if c.name == "RECE-NUM-DATA-FLAT")

    assert first.path == second.path
    assert (first.ordinal, first.decl) != (second.ordinal, second.decl)
    assert _by_name(cells, "RECE-NUM-APP-UNIT").parent == first.ordinal
    assert _by_name(cells, "RECE-NUM-DATA-LEVEL").parent == second.ordinal


def test_the_record_itself_has_no_enclosing_group() -> None:
    assert record_cells(_COMM)[0].parent == -1


# ERRMSG7's message table, shortened to three entries. The literals have to be
# spelled on one 01 and read through the OCCURS on the other, because an OCCURS item
# cannot carry VALUE -- so the pair is a single piece of storage under two names.
_MESSAGES = (
    _field(
        "WS-MESSAGE",
        1,
        "",
        0,
        children=[
            _field("FILLER", 2, "X(78)", 0),
            _field("FILLER_1", 2, "X(78)", 78),
            _field("FILLER_2", 2, "X(78)", 156),
        ],
    ),
    _field(
        "WS-MSG-TAB",
        1,
        "",
        234,
        redefines="WS-MESSAGE",
        children=[
            _field(
                "WS-MSG-DETAIL",
                5,
                "",
                0,
                occurs=3,
                element_size=78,
                children=[
                    _field("WS-ERR-CODE", 10, "X(4)", 0),
                    _field("WS-ERR-MSG", 10, "X(74)", 4),
                ],
            ),
        ],
    ),
)


def test_an_01_that_redefines_another_is_not_a_record_of_its_own() -> None:
    (record,) = section_records("WORKING-STORAGE", _MESSAGES)

    assert (record.name, record.size) == ("WS-MESSAGE", 234)
    # Both label sets are present, and both are top-level within the one record.
    tab = _by_name(record.cells, "WS-MSG-TAB")
    assert (tab.parent, tab.redefines) == (-1, "WS-MESSAGE")
    assert tab.start == 0


def test_a_table_over_another_01s_literals_lines_up_row_for_row() -> None:
    (record,) = section_records("WORKING-STORAGE", _MESSAGES)

    # Row 2 of the table is the second FILLER's 78 bytes, and the message text is
    # the last 74 of them. A read of WS-ERR-MSG(2) is a read of that literal.
    assert _at(record.cells, "WS-MSG-DETAIL", 2).start == 78
    assert _at(record.cells, "WS-ERR-MSG", 2).start == 78 + 4
    assert _by_name(record.cells, "FILLER_1").start == 78


def test_folding_two_01s_renumbers_rather_than_colliding() -> None:
    (record,) = section_records("WORKING-STORAGE", _MESSAGES)

    # 4 declarations on each 01; 4 cells from the first and 1 + 3*3 from the second.
    assert len(record.cells) == 14
    assert len({c.decl for c in record.cells}) == 8
    assert tuple(c.ordinal for c in record.cells) == tuple(range(14))
    assert len({(c.decl, c.index) for c in record.cells}) == 14


def test_unrelated_01_items_stay_separate_records() -> None:
    records = section_records("LINKAGE", (_COMM, _RECD))

    assert tuple(r.name for r in records) == ("WS-COMM-COMMAREA", "LAYOUT1-REC")


def test_comp3_packs_two_digits_per_byte_plus_a_sign_nibble() -> None:
    packed = CobolField(name="AMT", level=5, pic="S9(7)V99", usage="COMP-3", offset=0)

    assert record_cells(packed)[0].length == 5


def test_comp_is_sized_by_digit_count_not_by_digits() -> None:
    halfword = CobolField(name="N", level=5, pic="S9(4)", usage="COMP", offset=0)
    fullword = CobolField(name="N", level=5, pic="S9(9)", usage="COMP", offset=0)

    assert record_cells(halfword)[0].length == 2
    assert record_cells(fullword)[0].length == 4
