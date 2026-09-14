"""Rendering BMS maps as 24x80 screens.

A DFHMDF's POS is where its 3270 attribute byte sits; the field's characters
start one column to the right. Named fields take a runtime value when one is
supplied (cicada's SEND MAP payload keys fields by base name) and fall back to
their INITIAL otherwise.
"""

from pathlib import Path

import pytest

from cobble.bms_render import (
    ScreenField,
    ScreenMap,
    map_layouts,
    render_html,
    render_text,
)


def _mdf(label: str | None, pos: str, length: int, **args: str) -> dict:
    return {
        "name": "DFHMDF",
        "label": label,
        "args": {"POS": pos, "LENGTH": str(length), **args},
    }


def _invocations(*fields: dict, size: str = "(24,80)") -> list[dict]:
    return [
        {"name": "DFHMSD", "label": "SET01", "args": {"TYPE": "&&SYSPARM"}},
        {"name": "DFHMDI", "label": "MAP01", "args": {"SIZE": size}},
        *fields,
        {"name": "DFHMSD", "label": None, "args": {"TYPE": "FINAL"}},
    ]


def _single_map(*fields: dict, size: str = "(24,80)") -> ScreenMap:
    (screen_map,) = map_layouts(_invocations(*fields, size=size))
    return screen_map


def test_layout_keeps_unlabelled_static_text_with_its_position() -> None:
    screen_map = _single_map(_mdf(None, "(1,1)", 6, INITIAL="'Tran :'"))

    assert screen_map == ScreenMap(
        name="MAP01",
        rows=24,
        cols=80,
        fields=(
            ScreenField(
                name="",
                row=1,
                col=1,
                length=6,
                initial="Tran :",
                attrb=(),
                color="",
            ),
        ),
    )


def test_layout_reads_attributes_and_colour() -> None:
    screen_map = _single_map(
        _mdf("USERID", "(19,43)", 8, ATTRB="(FSET,IC,NORM,UNPROT)", COLOR="GREEN")
    )

    (field,) = screen_map.fields
    assert field.attrb == ("FSET", "IC", "NORM", "UNPROT")
    assert field.color == "GREEN"


def test_layout_converts_a_linear_offset_position_to_row_and_column() -> None:
    (field,) = _single_map(_mdf("X", "81", 3)).fields

    assert (field.row, field.col) == (2, 2)


def test_layout_separates_maps_in_one_mapset() -> None:
    invocations = [
        {"name": "DFHMDI", "label": "MAPA", "args": {"SIZE": "(24,80)"}},
        _mdf("A", "(1,1)", 1),
        {"name": "DFHMDI", "label": "MAPB", "args": {"SIZE": "(24,80)"}},
        _mdf("B", "(2,1)", 1),
    ]

    layouts = map_layouts(invocations)

    assert [(m.name, [f.name for f in m.fields]) for m in layouts] == [
        ("MAPA", ["A"]),
        ("MAPB", ["B"]),
    ]


def test_text_places_initial_one_column_right_of_the_attribute_byte() -> None:
    screen_map = _single_map(_mdf(None, "(2,3)", 6, INITIAL="'Tran :'"))

    lines = render_text(screen_map, {}).splitlines()

    assert len(lines) == 24
    assert all(len(line) == 80 for line in lines)
    assert lines[1][3:9] == "Tran :"


def test_text_overlays_runtime_value_on_named_field() -> None:
    screen_map = _single_map(_mdf("CURDATE", "(1,71)", 8, INITIAL="'mm/dd/yy'"))

    line = render_text(screen_map, {"CURDATE": "09/14/26"}).splitlines()[0]

    assert line[71:79] == "09/14/26"


def test_text_truncates_value_to_field_length() -> None:
    screen_map = _single_map(_mdf("NAME", "(1,1)", 4))

    line = render_text(screen_map, {"NAME": "ABCDEFGH"}).splitlines()[0]

    assert line[:6] == " ABCD "


def test_text_a_later_field_without_data_leaves_earlier_text_visible() -> None:
    # COACTVW.bms ends with an unlabelled LENGTH=9,POS=(1,1) field: BMS sends
    # only its attribute byte, so the 'Tran:' written earlier stays on screen.
    screen_map = _single_map(
        _mdf(None, "(1,1)", 5, INITIAL="'Tran:'"),
        _mdf("TRNNAME", "(1,7)", 4),
        _mdf(None, "(1,1)", 9),
    )

    line = render_text(screen_map, {"TRNNAME": "CAVW"}).splitlines()[0]

    assert line[:12] == " Tran: CAVW "


def test_text_hides_dark_fields() -> None:
    screen_map = _single_map(_mdf("PINNUM", "(1,1)", 8, ATTRB="(DRK,UNPROT)"))

    line = render_text(screen_map, {"PINNUM": "HIDDEN42"}).splitlines()[0]

    assert "HIDDEN42" not in line


def test_text_clips_a_field_running_past_the_right_margin() -> None:
    screen_map = _single_map(_mdf("X", "(1,78)", 5, INITIAL="'ABCDE'"))

    lines = render_text(screen_map, {}).splitlines()

    assert lines[0][78:] == "AB"
    assert len(lines) == 24


def test_html_styles_fields_by_colour_brightness_and_protection() -> None:
    screen_map = _single_map(
        _mdf(None, "(1,1)", 5, INITIAL="'Title'", COLOR="YELLOW", ATTRB="(BRT)"),
        _mdf("USERID", "(2,1)", 8, ATTRB="(UNPROT)", COLOR="GREEN"),
    )

    html = render_html(screen_map, {"USERID": "OPER4242"})

    assert '<span class="c-yellow brt">Title</span>' in html
    assert '<span class="c-green unprot">OPER4242</span>' in html


def test_html_escapes_markup_in_values() -> None:
    screen_map = _single_map(_mdf("MSG", "(1,1)", 10))

    html = render_html(screen_map, {"MSG": "<b>&x"})

    assert "&lt;b&gt;&amp;x" in html
    assert "<b>" not in html


HLASM = (
    Path(__file__).resolve().parents[3]
    / "cicada/third-party/che-che4z-lsp-for-hlasm-fork/build/bin/hlasm_export"
)
CARDDEMO_BMS = Path(__file__).resolve().parents[3] / "vendor/carddemo/app/bms"


@pytest.mark.skipif(
    not (HLASM.exists() and CARDDEMO_BMS.exists()),
    reason="needs the hlasm_export binary and the CardDemo corpus",
)
def test_carddemo_signon_screen_renders_labels_in_place() -> None:
    from cobble.bms_render import layouts_from_bms

    macros = Path(__file__).resolve().parents[2] / "bms-macros"
    (signon,) = layouts_from_bms(CARDDEMO_BMS / "COSGN00.bms", macros)

    lines = render_text(signon, {"TRNNAME": "CC00"}).splitlines()

    assert signon.name == "COSGN0A"
    assert lines[0][1:7] == "Tran :"
    assert lines[0][8:12] == "CC00"
