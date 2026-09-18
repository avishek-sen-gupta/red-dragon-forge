from bms_copybook_gen.parser import parse_mapsets
from tests.covers import covers, NotLanguageFeature

SIMPLE_INVOCATIONS = [
    {
        "name": "DFHMSD",
        "label": "ORDERSET",
        "args": {"TYPE": "MAP", "LANG": "COBOL", "MODE": "INOUT", "TIOAPFX": "YES"},
        "range": {"start": {"line": 0, "column": 0}, "end": {"line": 0, "column": 10}},
    },
    {
        "name": "DFHMDI",
        "label": "ORDERMAP",
        "args": {"SIZE": "(24,80)", "LINE": "1", "COLUMN": "1"},
        "range": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 10}},
    },
    {
        "name": "DFHMDF",
        "label": "ORDNO",
        "args": {
            "LENGTH": "8",
            "POS": "(4,12)",
            "ATTRB": "(UNPROT,IC)",
            "PICOUT": "'99999999'",
        },
        "range": {"start": {"line": 2, "column": 0}, "end": {"line": 2, "column": 10}},
    },
    {
        "name": "DFHMDF",
        "label": "CUSTNAM",
        "args": {"LENGTH": "30", "POS": "(6,14)", "ATTRB": "UNPROT"},
        "range": {"start": {"line": 3, "column": 0}, "end": {"line": 3, "column": 10}},
    },
    {
        "name": "DFHMSD",
        "args": {"TYPE": "FINAL"},
        "range": {"start": {"line": 4, "column": 0}, "end": {"line": 4, "column": 10}},
    },
]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_parse_returns_one_mapset():
    mapsets = parse_mapsets(SIMPLE_INVOCATIONS)
    assert len(mapsets) == 1


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mapset_label_and_lang():
    mapset = parse_mapsets(SIMPLE_INVOCATIONS)[0]
    assert mapset.label == "ORDERSET"
    assert mapset.lang == "COBOL"
    assert mapset.mode == "INOUT"
    assert mapset.tioapfx is True


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_mapset_contains_one_map():
    mapset = parse_mapsets(SIMPLE_INVOCATIONS)[0]
    assert len(mapset.maps) == 1
    assert mapset.maps[0].label == "ORDERMAP"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_map_contains_two_fields():
    bmsmap = parse_mapsets(SIMPLE_INVOCATIONS)[0].maps[0]
    assert len(bmsmap.fields) == 2


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_attributes():
    f = parse_mapsets(SIMPLE_INVOCATIONS)[0].maps[0].fields[0]
    assert f.label == "ORDNO"
    assert f.length == 8
    assert f.picout == "99999999"
    assert "UNPROT" in f.attrb
    assert "IC" in f.attrb


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_field_attrb_single_value():
    f = parse_mapsets(SIMPLE_INVOCATIONS)[0].maps[0].fields[1]
    assert f.attrb == ("UNPROT",)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dfhmdf_without_label_is_skipped():
    invocations = [
        {
            "name": "DFHMSD",
            "label": "SET1",
            "args": {"TYPE": "MAP", "LANG": "COBOL", "MODE": "INOUT", "TIOAPFX": "NO"},
            "range": {},
        },
        {"name": "DFHMDI", "label": "MAP1", "args": {"SIZE": "(24,80)"}, "range": {}},
        {
            "name": "DFHMDF",
            "args": {"LENGTH": "1", "POS": "(1,1)", "ATTRB": "ASKIP"},
            "range": {},
        },
        {
            "name": "DFHMDF",
            "label": "MYFIELD",
            "args": {"LENGTH": "5", "POS": "(2,1)", "ATTRB": "UNPROT"},
            "range": {},
        },
        {"name": "DFHMSD", "args": {"TYPE": "FINAL"}, "range": {}},
    ]
    fields = parse_mapsets(invocations)[0].maps[0].fields
    assert len(fields) == 1
    assert fields[0].label == "MYFIELD"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_tioapfx_no():
    invocations = [
        {
            "name": "DFHMSD",
            "label": "SET1",
            "args": {"TYPE": "MAP", "LANG": "COBOL", "MODE": "OUT", "TIOAPFX": "NO"},
            "range": {},
        },
        {"name": "DFHMDI", "label": "MAP1", "args": {"SIZE": "(24,80)"}, "range": {}},
        {"name": "DFHMSD", "args": {"TYPE": "FINAL"}, "range": {}},
    ]
    assert parse_mapsets(invocations)[0].tioapfx is False


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_occurs_and_grpname():
    invocations = [
        {
            "name": "DFHMSD",
            "label": "SET1",
            "args": {"TYPE": "MAP", "LANG": "COBOL", "MODE": "INOUT", "TIOAPFX": "YES"},
            "range": {},
        },
        {"name": "DFHMDI", "label": "MAP1", "args": {"SIZE": "(24,80)"}, "range": {}},
        {
            "name": "DFHMDF",
            "label": "ITEMCD",
            "args": {
                "LENGTH": "10",
                "POS": "(8,2)",
                "ATTRB": "UNPROT",
                "GRPNAME": "LINEITEM",
                "OCCURS": "10",
            },
            "range": {},
        },
        {"name": "DFHMSD", "args": {"TYPE": "FINAL"}, "range": {}},
    ]
    f = parse_mapsets(invocations)[0].maps[0].fields[0]
    assert f.grpname == "LINEITEM"
    assert f.occurs == 10


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_multiple_maps_in_mapset():
    invocations = [
        {
            "name": "DFHMSD",
            "label": "SET1",
            "args": {"TYPE": "MAP", "LANG": "COBOL", "MODE": "INOUT", "TIOAPFX": "YES"},
            "range": {},
        },
        {"name": "DFHMDI", "label": "MAP1", "args": {"SIZE": "(24,80)"}, "range": {}},
        {
            "name": "DFHMDF",
            "label": "F1",
            "args": {"LENGTH": "5", "POS": "(1,1)", "ATTRB": "UNPROT"},
            "range": {},
        },
        {"name": "DFHMDI", "label": "MAP2", "args": {"SIZE": "(24,80)"}, "range": {}},
        {
            "name": "DFHMDF",
            "label": "F2",
            "args": {"LENGTH": "10", "POS": "(1,1)", "ATTRB": "PROT"},
            "range": {},
        },
        {"name": "DFHMSD", "args": {"TYPE": "FINAL"}, "range": {}},
    ]
    maps = parse_mapsets(invocations)[0].maps
    assert len(maps) == 2
    assert maps[0].label == "MAP1"
    assert maps[0].fields[0].label == "F1"
    assert maps[1].label == "MAP2"
    assert maps[1].fields[0].label == "F2"
