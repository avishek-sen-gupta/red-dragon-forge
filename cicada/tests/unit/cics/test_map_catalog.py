import pytest

from bms_copybook_gen.models import BmsMap, BmsMapSet
from cics.bms.catalog import MapNotFound, catalog_from_mapsets
from tests.covers import NotLanguageFeature, covers


def _catalog():
    return catalog_from_mapsets(
        (
            BmsMapSet(
                "SETA", "COBOL", "INOUT", True, maps=(BmsMap("MAP1"), BmsMap("SHARED"))
            ),
            BmsMapSet("SETB", "COBOL", "INOUT", True, maps=(BmsMap("SHARED"),)),
        )
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_lookup_by_mapset_and_map():
    assert _catalog().lookup("SETB", "SHARED") == BmsMap("SHARED")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_lookup_without_mapset_needs_a_unique_name():
    assert _catalog().lookup("", "MAP1 ") == BmsMap("MAP1")
    with pytest.raises(MapNotFound, match="2 BMS maps"):
        _catalog().lookup("", "SHARED")


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unknown_map_is_loud():
    with pytest.raises(MapNotFound):
        _catalog().lookup("SETA", "NOPE")
