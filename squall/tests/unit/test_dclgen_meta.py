"""
tests/unit/test_dclgen_meta.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``squall.dclgen_meta.derive_field_meta`` — recognising the DCLGEN VARCHAR
(level-49) shape directly in the raw ProLeap bridge JSON.

Fixtures below mirror the *actual* bridge output for CardDemo's
``COTRTUPC``/``DCLTRTYP`` (dumped via a patched
``SqlLoweringStrategy.preprocess_program_dict`` during a real
``compile_program`` run against the vendored corpus) — key names are
``name``/``level``/``pic``/``usage``/``children``, not the sketch in the task
brief (which said ``picture``).
"""

from __future__ import annotations

from squall.dclgen_meta import derive_field_meta

# Real bridge shape for `10 DCL-TR-DESCRIPTION.` in vendor/carddemo's
# DCLTRTYP.dcl -- a level-49 VARCHAR group nested under a level-10 parent
# under the 01-level DCLTRANSACTION-TYPE record.
_DCLGEN_VARCHAR = {
    "name": "DCL-TR-DESCRIPTION",
    "level": 10,
    "pic": "",
    "usage": "DISPLAY",
    "children": [
        {
            "name": "DCL-TR-DESCRIPTION-LEN",
            "level": 49,
            "pic": "S9(4)",
            "usage": "COMP",
        },
        {
            "name": "DCL-TR-DESCRIPTION-TEXT",
            "level": 49,
            "pic": "X(50)",
            "usage": "DISPLAY",
        },
    ],
}

_PLAIN_GROUP = {
    "name": "SOME-GROUP",
    "level": 10,
    "pic": "",
    "usage": "DISPLAY",
    "children": [
        {"name": "A", "level": 15, "pic": "X(4)", "usage": "DISPLAY"},
    ],
}


def test_a_level_49_group_is_recognised_as_varchar():
    meta = derive_field_meta({"data_fields": [_DCLGEN_VARCHAR]})

    assert meta["DCL-TR-DESCRIPTION"] == {
        "category": "VARCHAR",
        "length": 50,
        "len_var": "DCL-TR-DESCRIPTION-LEN",
        "text_var": "DCL-TR-DESCRIPTION-TEXT",
    }


def test_a_plain_group_is_not_varchar():
    assert "SOME-GROUP" not in derive_field_meta({"data_fields": [_PLAIN_GROUP]})


def test_a_leaf_field_is_not_varchar():
    leaf = {"name": "DCL-TR-TYPE", "level": 10, "pic": "X(2)", "usage": "DISPLAY"}
    assert derive_field_meta({"data_fields": [leaf]}) == {}


def test_a_49_group_with_only_one_child_is_not_varchar():
    """The LEN/TEXT pair must both be present -- a lone 49-level child (e.g.
    a REDEFINES artefact) must not be misread as VARCHAR."""
    lone = {
        "name": "ODD-GROUP",
        "level": 10,
        "pic": "",
        "usage": "DISPLAY",
        "children": [
            {"name": "ODD-LEN", "level": 49, "pic": "S9(4)", "usage": "COMP"},
        ],
    }
    assert derive_field_meta({"data_fields": [lone]}) == {}


def test_a_49_group_with_wrong_child_order_is_not_varchar():
    """TEXT before LEN is not the DCLGEN VARCHAR shape."""
    swapped = {
        "name": "SWAPPED-GROUP",
        "level": 10,
        "pic": "",
        "usage": "DISPLAY",
        "children": [
            {"name": "SWAPPED-TEXT", "level": 49, "pic": "X(50)", "usage": "DISPLAY"},
            {"name": "SWAPPED-LEN", "level": 49, "pic": "S9(4)", "usage": "COMP"},
        ],
    }
    assert derive_field_meta({"data_fields": [swapped]}) == {}


def test_nested_varchar_group_is_found_at_any_depth():
    """The real DCLTRTYP layout nests the VARCHAR group two levels down (01
    DCLTRANSACTION-TYPE -> 10 DCL-TR-DESCRIPTION -> 49/49); the walk must not
    be limited to top-level data_fields entries."""
    record = {
        "name": "DCLTRANSACTION-TYPE",
        "level": 1,
        "pic": "",
        "usage": "DISPLAY",
        "children": [
            {"name": "DCL-TR-TYPE", "level": 10, "pic": "X(2)", "usage": "DISPLAY"},
            _DCLGEN_VARCHAR,
        ],
    }

    meta = derive_field_meta({"data_fields": [record]})

    assert meta["DCL-TR-DESCRIPTION"]["category"] == "VARCHAR"
    assert "DCLTRANSACTION-TYPE" not in meta
    assert "DCL-TR-TYPE" not in meta


def test_missing_data_fields_yields_empty_mapping():
    assert derive_field_meta({}) == {}


def test_a_non_s9_4_comp_length_field_is_not_varchar():
    """A COMP field with a different digit count is not DB2's fixed VARCHAR
    length-prefix shape (e.g. a genuine COMP-3 or a wider binary counter)."""
    odd_len = {
        "name": "ODD-GROUP",
        "level": 10,
        "pic": "",
        "usage": "DISPLAY",
        "children": [
            {"name": "ODD-LEN", "level": 49, "pic": "S9(8)", "usage": "COMP"},
            {"name": "ODD-TEXT", "level": 49, "pic": "X(50)", "usage": "DISPLAY"},
        ],
    }
    assert derive_field_meta({"data_fields": [odd_len]}) == {}
