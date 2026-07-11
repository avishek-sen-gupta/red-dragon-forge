import pytest

from cobble.interpreter.cobol.cobol_types import CobolDataCategory
from cobble.interpreter.cobol.pic_parser import parse_pic


def test_parse_pic_plain_numeric() -> None:
    desc = parse_pic("9(5)")
    assert desc.category == CobolDataCategory.ZONED_DECIMAL
    assert desc.total_digits == 5
    assert desc.decimal_digits == 0
    assert not desc.signed


def test_parse_pic_signed_with_implied_decimal() -> None:
    desc = parse_pic("S9(5)V99")
    assert desc.total_digits == 7
    assert desc.decimal_digits == 2
    assert desc.signed


def test_parse_pic_alphanumeric() -> None:
    desc = parse_pic("X(8)")
    assert desc.category == CobolDataCategory.ALPHANUMERIC
    assert desc.total_digits == 8
    assert desc.decimal_digits == 0
    assert not desc.signed


def test_parse_pic_comp3_usage() -> None:
    desc = parse_pic("9(5)", usage="COMP-3")
    assert desc.category == CobolDataCategory.COMP3
    assert desc.total_digits == 5


def test_parse_pic_comp1_ignores_pic() -> None:
    desc = parse_pic("", usage="COMP-1")
    assert desc.category == CobolDataCategory.COMP1
    assert desc.total_digits == 0


def test_parse_pic_numeric_edited_sizes_by_character_width() -> None:
    desc = parse_pic("+ZZZ,ZZZ,ZZZ.99")
    assert desc.category == CobolDataCategory.NUMERIC_EDITED
    assert desc.total_digits == 15
    assert desc.decimal_digits == 2
    assert desc.signed
    assert desc.pic_string == "+ZZZ,ZZZ,ZZZ.99"


def test_parse_pic_empty_pic_defaults_to_zero_size() -> None:
    desc = parse_pic("")
    assert desc.total_digits == 0
    assert desc.decimal_digits == 0


def test_parse_pic_invalid_pic_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Cannot parse PIC clause"):
        parse_pic("!!!")
