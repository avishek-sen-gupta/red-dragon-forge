from cics.bms.attributes import attribute_byte
from tests.covers import NotLanguageFeature, covers


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_omitted_attrb_is_askip_norm():
    assert attribute_byte(()) == 0x30


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_unprotected_fset_sets_only_mdt():
    assert attribute_byte(("FSET", "IC", "NORM", "UNPROT")) == 0x01


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dark_unprotected():
    assert attribute_byte(("DRK", "FSET", "UNPROT")) == 0x0D


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_bright_askip():
    assert attribute_byte(("ASKIP", "BRT", "FSET")) == 0x39


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_numeric_unprotected():
    assert attribute_byte(("UNPROT", "NUM")) == 0x10
