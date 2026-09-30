"""What a program's WORKING-STORAGE holds before any statement runs."""

from __future__ import annotations

from cobble.dataflow.fields.extent import cell_index
from cobble.dataflow.fields.image import initial_image
from cobble.dataflow.fields.values import of_value
from cobble.dataflow.layout import program_records


def test_every_occurrence_of_a_table_entry_carries_its_declaration_value(
    program_of, field
):
    asg = program_of(
        [],
        paragraphs=[],
        data_fields=[
            field(
                1,
                "TAB-REC",
                children=[
                    field(
                        5,
                        "TAB-ENTRY",
                        offset=0,
                        occurs=3,
                        children=[
                            field(10, "TAB-PGM", "X(8)", offset=0, value="COPGM01")
                        ],
                    )
                ],
            )
        ],
    )
    records = program_records(asg)
    index = cell_index(records)
    image = initial_image(records, index)

    named = {
        index.extent_of(cell).start: image[index.extent_of(cell)]
        for record in records
        for cell in record.cells
        if cell.name == "TAB-PGM"
    }

    assert named == {
        0: of_value(b"COPGM01 "),
        8: of_value(b"COPGM01 "),
        16: of_value(b"COPGM01 "),
    }


def test_the_image_holds_elementary_working_storage_values_only(program_of, field):
    asg = program_of(
        [],
        paragraphs=[],
        data_fields=[
            field(
                1,
                "WS-REC",
                value="GROUPVAL",
                children=[
                    field(5, "WS-PGM", "X(8)", offset=0, value="COSGN00C"),
                    field(5, "WS-NARROW", "X(4)", offset=8, value="ABCDEFGH"),
                    field(
                        5,
                        "WS-BLANK",
                        "X(8)",
                        offset=12,
                        value="SPACES",
                        value_is_figurative=True,
                    ),
                    field(5, "WS-PLAIN", "X(8)", offset=20),
                ],
            )
        ],
        linkage_fields=[
            field(
                1,
                "LK-REC",
                children=[field(5, "LK-PGM", "X(8)", offset=0, value="IGNORED ")],
            )
        ],
    )
    records = program_records(asg)
    index = cell_index(records)
    image = initial_image(records, index)

    by_name = {
        cell.name: image.get(index.extent_of(cell))
        for record in records
        for cell in record.cells
    }

    assert by_name["WS-PGM"] == of_value(b"COSGN00C")
    assert by_name["WS-NARROW"] == of_value(b"ABCD")
    assert by_name["WS-BLANK"] == of_value(b"        ")
    assert by_name["WS-PLAIN"] is None
    assert by_name["WS-REC"] is None
    assert by_name["LK-PGM"] is None


def test_a_program_with_no_working_storage_has_an_empty_image(program_of, field):
    asg = program_of([], paragraphs=[], data_fields=[])
    records = program_records(asg)

    assert initial_image(records, cell_index(records)) == {}
