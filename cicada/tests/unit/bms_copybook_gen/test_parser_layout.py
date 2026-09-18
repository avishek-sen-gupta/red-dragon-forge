from bms_copybook_gen.parser import parse_attrb, parse_mapsets
from tests.covers import NotLanguageFeature, covers


def _mdf(label, pos, length, **args):
    return {
        "name": "DFHMDF",
        "label": label,
        "args": {"POS": pos, "LENGTH": str(length), **args},
    }


SIGNON = [
    {
        "name": "DFHMSD",
        "label": "COSGN00",
        "args": {"TYPE": "&&SYSPARM", "CTRL": "(ALARM,FREEKB)", "EXTATT": "YES"},
    },
    {"name": "DFHMDI", "label": "COSGN0A", "args": {"SIZE": "(24,80)"}},
    _mdf(
        None,
        "(19,29)",
        13,
        ATTRB="(ASKIP,NORM)",
        COLOR="TURQUOISE",
        INITIAL="'User ID     :'",
    ),
    _mdf(
        "USERID",
        "(19,43)",
        8,
        ATTRB="(FSET,IC,NORM,UNPROT)",
        COLOR="GREEN",
        HILIGHT="OFF",
    ),
    _mdf("PASSWD", "(20,43)", 8, ATTRB="(DRK,FSET,UNPROT)", INITIAL="'________'"),
    _mdf(None, "1840", 22, INITIAL="'It''s F3=Exit'"),
    {"name": "DFHMSD", "label": None, "args": {"TYPE": "FINAL"}},
]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_elements_keep_captions_in_order_and_fields_keep_only_labels():
    (bms_map,) = parse_mapsets(SIGNON)[0].maps
    assert [e.label for e in bms_map.elements] == ["", "USERID", "PASSWD", ""]
    assert [f.label for f in bms_map.fields] == ["USERID", "PASSWD"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_layout_attributes():
    caption, userid, _passwd, footer = parse_mapsets(SIGNON)[0].maps[0].elements
    assert (caption.row, caption.col, caption.initial, caption.color) == (
        19,
        29,
        "User ID     :",
        "TURQUOISE",
    )
    assert (userid.attrb, userid.hilight) == (("FSET", "IC", "NORM", "UNPROT"), "OFF")
    assert (footer.row, footer.col, footer.initial) == (24, 1, "It's F3=Exit")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_map_inherits_mapset_ctrl_and_extatt():
    bms_map = parse_mapsets(SIGNON)[0].maps[0]
    assert (bms_map.ctrl, bms_map.extatt, bms_map.size) == (
        ("ALARM", "FREEKB"),
        True,
        (24, 80),
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_attrb_empty():
    assert parse_attrb("") == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_mapsets_empty_invocations():
    assert parse_mapsets([]) == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_mapsets_no_dfhmsd():
    assert parse_mapsets([_mdf("USERID", "(1,1)", 8, ATTRB="UNPROT")]) == ()


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mapset_with_no_dfhmdi_has_no_maps():
    invocations = [
        {"name": "DFHMSD", "label": "SET1", "args": {"TYPE": "MAP"}},
        {"name": "DFHMSD", "label": None, "args": {"TYPE": "FINAL"}},
    ]
    (mapset,) = parse_mapsets(invocations)
    assert mapset.maps == ()
