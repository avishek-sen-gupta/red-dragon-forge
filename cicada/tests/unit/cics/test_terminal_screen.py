import pytest

from bms_copybook_gen.parser import parse_mapsets
from cics.bms.attributes import MDT
from cics.bms.catalog import catalog_from_mapsets
from cics.screen.cursor import NO_CURSOR, Cursor, SymbolicCursor
from cics.screen.payload import (
    FieldAttributes,
    SendMapPayload,
    SendMode,
    SendTextPayload,
)
from cics.screen.terminal_screen import TerminalScreen, UnsupportedMapSize, address
from tests.covers import NotLanguageFeature, covers


def _mdf(label, pos, length, **args):
    return {
        "name": "DFHMDF",
        "label": label,
        "args": {"POS": pos, "LENGTH": str(length), **args},
    }


def _signon(size="(24,80)"):
    (mapset,) = parse_mapsets(
        [
            {
                "name": "DFHMSD",
                "label": "COSGN00",
                "args": {"TYPE": "MAP", "EXTATT": "YES"},
            },
            {"name": "DFHMDI", "label": "COSGN0A", "args": {"SIZE": size}},
            _mdf(
                None,
                "(19,29)",
                13,
                ATTRB="(ASKIP,NORM)",
                COLOR="TURQUOISE",
                INITIAL="'User ID     :'",
            ),
            _mdf("USERID", "(19,43)", 8, ATTRB="(FSET,IC,NORM,UNPROT)", COLOR="GREEN"),
            _mdf(None, "(19,52)", 0, ATTRB="(ASKIP,NORM)"),
            _mdf(
                None,
                "(19,52)",
                8,
                ATTRB="(ASKIP,NORM)",
                COLOR="BLUE",
                INITIAL="'(8 Char)'",
            ),
            _mdf(
                "PASSWD", "(20,43)", 8, ATTRB="(DRK,FSET,UNPROT)", INITIAL="'________'"
            ),
            _mdf("ERRMSG", "(23,1)", 78, ATTRB="(ASKIP,BRT,FSET)", COLOR="RED"),
            {"name": "DFHMSD", "label": None, "args": {"TYPE": "FINAL"}},
        ]
    )
    return mapset.maps[0]


def _payload(**overrides):
    base = dict(
        map="COSGN0A",
        mapset="COSGN00",
        mode=SendMode.FULL,
        erase=True,
        alarm=False,
        frset=False,
        freekb=True,
        cursor=NO_CURSOR,
        fields={},
        attrs={},
    )
    return SendMapPayload(**{**base, **overrides})


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_full_send_paints_captions_and_data_at_bms_positions():
    screen = TerminalScreen().apply(
        _payload(fields={"USERID": "\x00" * 8, "ERRMSG": "Wrong Password"}), _signon()
    )
    assert screen.row(19)[29:42] == "User ID     :"
    assert screen.row(19)[52:60] == "(8 Char)"
    assert screen.row(23)[1:15] == "Wrong Password"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_low_value_data_keeps_initial_and_dark_fields_show_blank():
    screen = TerminalScreen().apply(_payload(fields={"PASSWD": "\x00" * 8}), _signon())
    assert screen.field("PASSWD").content == "________"
    assert screen.row(20)[43:51] == " " * 8


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_cursor_defaults_to_ic_and_follows_symbolic_and_explicit_positions():
    assert TerminalScreen().apply(_payload(), _signon()).cursor == address(19, 43) + 1
    assert (
        TerminalScreen()
        .apply(_payload(cursor=SymbolicCursor("PASSWD")), _signon())
        .cursor
        == address(20, 43) + 1
    )
    assert TerminalScreen().apply(_payload(cursor=Cursor(5)), _signon()).cursor == 5


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_program_attribute_bytes_override_the_map():
    attrs = {"ERRMSG": FieldAttributes(attr=0xF8, color=0xF4)}
    errmsg = TerminalScreen().apply(_payload(attrs=attrs), _signon()).field("ERRMSG")
    assert (errmsg.attribute, errmsg.color) == (0x38, 0xF4)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unprotected_attribute_override_is_not_mistaken_for_no_override():
    errmsg = (
        TerminalScreen()
        .apply(_payload(attrs={"ERRMSG": FieldAttributes(attr=0x40)}), _signon())
        .field("ERRMSG")
    )
    assert errmsg.attribute == 0x00


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dataonly_rewrites_only_named_fields_and_keeps_the_cursor():
    first = TerminalScreen().apply(_payload(fields={"ERRMSG": "one"}), _signon())
    second = first.apply(
        _payload(mode=SendMode.DATAONLY, erase=False, fields={"ERRMSG": "two"}),
        _signon(),
    )
    assert (second.row(19)[29:42], second.row(23)[1:4], second.cursor) == (
        "User ID     :",
        "two",
        first.cursor,
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_maponly_ignores_data_and_frset_resets_mdts():
    shown = TerminalScreen().apply(
        _payload(mode=SendMode.MAPONLY, fields={"ERRMSG": "x"}), _signon()
    )
    assert shown.field("ERRMSG").content == ""
    reset = shown.apply(
        _payload(
            mode=SendMode.DATAONLY, erase=False, frset=True, fields={"USERID": "A"}
        ),
        _signon(),
    )
    assert not reset.field("PASSWD").modified


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_erase_clears_fields_from_a_previous_map():
    text = TerminalScreen().apply_text(SendTextPayload("bye"))
    assert (
        TerminalScreen().apply(_payload(), _signon()).apply_text(SendTextPayload("bye"))
        == text
    )
    assert text.row(1).startswith("bye")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_with_input_records_typed_values_and_sets_mdt():
    typed = (
        TerminalScreen()
        .apply(_payload(), _signon())
        .with_input({"USERID": "USER0001"}, Cursor(7))
    )
    assert (
        typed.field("USERID").content,
        bool(typed.field("USERID").attribute & MDT),
        typed.cursor,
    ) == ("USER0001", True, 7)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_non_24x80_maps_are_refused():
    with pytest.raises(UnsupportedMapSize):
        TerminalScreen().apply(_payload(), _signon(size="(12,40)"))


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_payload_lookup_through_the_catalog():
    catalog = catalog_from_mapsets(
        parse_mapsets(
            [
                {"name": "DFHMSD", "label": "COSGN00", "args": {"TYPE": "MAP"}},
                {"name": "DFHMDI", "label": "COSGN0A", "args": {"SIZE": "(24,80)"}},
                _mdf(None, "(1,1)", 4, INITIAL="'Tran'"),
            ]
        )
    )
    assert TerminalScreen().apply_payload(_payload(), catalog).row(1)[1:5] == "Tran"


def _account_view_header():
    """CACTVWA's row 1, as vendor/carddemo/app/bms/COACTVW.bms declares it: the
    'Tran:' caption at POS=(1,1), TRNNAME at POS=(1,7), and the unlabelled
    LENGTH=9 POS=(1,1) field the mapset declares last (COACTVW.bms:363-364),
    which lands on the caption's own attribute address."""
    (mapset,) = parse_mapsets(
        [
            {"name": "DFHMSD", "label": "COACTVW", "args": {"TYPE": "MAP"}},
            {"name": "DFHMDI", "label": "CACTVWA", "args": {"SIZE": "(24,80)"}},
            _mdf(
                None,
                "(1,1)",
                5,
                ATTRB="(ASKIP,NORM)",
                COLOR="BLUE",
                INITIAL="'Tran:'",
            ),
            _mdf("TRNNAME", "(1,7)", 4, ATTRB="(ASKIP,FSET,NORM)", COLOR="BLUE"),
            _mdf(None, "(1,1)", 9),
            {"name": "DFHMSD", "label": None, "args": {"TYPE": "FINAL"}},
        ]
    )
    return mapset.maps[0]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_dataless_field_over_a_caption_keeps_the_characters_already_there():
    """Two DFHMDFs at one POS are two SBA/SF pairs on the wire: the later one
    rewrites the attribute byte and, carrying neither INITIAL nor symbolic data,
    writes nothing after it — so the caption's characters survive."""
    screen = TerminalScreen().apply(
        _payload(map="CACTVWA", mapset="COACTVW", fields={"TRNNAME": "CAVW"}),
        _account_view_header(),
    )
    assert screen.row(1)[1:6] == "Tran:"
    assert screen.row(1)[7:11] == "CAVW"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dataonly_send_of_spaces_blanks_the_field():
    """MOVE SPACES TO ERRMSGO + SEND MAP DATAONLY. The builtin rstrips symbolic
    values, so the blanking arrives as an empty string that was still sent."""
    shown = TerminalScreen().apply(
        _payload(fields={"ERRMSG": "Wrong Password"}), _signon()
    )
    cleared = shown.apply(
        _payload(mode=SendMode.DATAONLY, erase=False, fields={"ERRMSG": ""}), _signon()
    )
    assert cleared.field("ERRMSG").content == ""
    assert cleared.row(23)[1:15] == " " * 14


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_non_erase_full_send_of_spaces_blanks_the_field():
    shown = TerminalScreen().apply(
        _payload(fields={"ERRMSG": "Wrong Password"}), _signon()
    )
    cleared = shown.apply(_payload(erase=False, fields={"ERRMSG": ""}), _signon())
    assert cleared.field("ERRMSG").content == ""
    assert cleared.row(23)[1:15] == " " * 14
