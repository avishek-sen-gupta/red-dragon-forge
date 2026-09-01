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


def test_parse_pic_too_many_digit_positions_raises_value_error() -> None:
    # "the number of digit positions represented in the character-string must be
    # in the range 1 through 18, inclusive" under ARITH(COMPAT) -- p. 217.
    with pytest.raises(ValueError, match="19 digit positions, must be 1 to 18"):
        parse_pic("9(19)")


def test_parse_pic_two_editing_sign_symbols_raises_value_error() -> None:
    # "Only one of the following symbols can be written in a given PICTURE
    # character-string: + - CR DB" -- p. 218.
    with pytest.raises(ValueError, match=r"more than one of \+ - CR DB"):
        parse_pic("+999+")


def test_parse_pic_floating_currency_and_zero_suppression_are_exclusive() -> None:
    # "The following symbols are mutually exclusive as floating replacement
    # symbols in one PICTURE character-string: Z * + - cs" -- p. 224.
    with pytest.raises(ValueError, match="mutually exclusive"):
        parse_pic("$$$ZZ9")


def test_parse_pic_fixed_currency_before_zero_suppression_is_legal() -> None:
    # The p. 224 exclusion is between FLOATING symbols; a single fixed currency
    # symbol ahead of a suppression run is fine.
    desc = parse_pic("$ZZ,ZZ9")
    assert desc.category == CobolDataCategory.NUMERIC_EDITED
    assert desc.char_positions == 7


def test_parse_pic_alphanumeric_edited_counts_insertion_positions() -> None:
    # "The PICTURE character-string ... must contain at least one A or X, and at
    # least one B or 0 (zero) or /" -- IBM Enterprise COBOL LR p. 207.
    desc = parse_pic("X(8)B(3)")
    assert desc.category == CobolDataCategory.ALPHANUMERIC_EDITED
    assert desc.char_positions == 11
    assert desc.byte_length == 11


def test_parse_pic_alphabetic() -> None:
    desc = parse_pic("A(5)")
    assert desc.category == CobolDataCategory.ALPHABETIC
    assert desc.char_positions == 5
    assert desc.byte_length == 5


def test_parse_pic_external_floating_point() -> None:
    # "Pic +999.99E+99" -- p. 215. The exponent's two 9s are part of the format,
    # not the value's precision.
    desc = parse_pic("+999.99E+99")
    assert desc.category == CobolDataCategory.EXTERNAL_FLOAT
    assert desc.char_positions == 11
    assert desc.total_digits == 5
    assert desc.decimal_digits == 2
    assert desc.byte_length == 11


def test_parse_pic_floating_currency_run_is_one_fewer_digit_than_its_length() -> None:
    # "The second leftmost floating insertion symbol ... represents the leftmost
    # limit at which numeric data can appear" -- p. 223.
    desc = parse_pic("$,$$$,999.99")
    assert desc.category == CobolDataCategory.NUMERIC_EDITED
    assert desc.char_positions == 12
    assert desc.total_digits == 12
    assert desc.decimal_digits == 2


def test_parse_pic_scaling_positions_are_digits_but_not_stored() -> None:
    # "P ... Not counted in the size of the data item. Scaling position
    # characters are counted in determining the maximum number of digit
    # positions" -- Table 12, p. 209.
    desc = parse_pic("PPP999")
    assert desc.category == CobolDataCategory.ZONED_DECIMAL
    assert desc.total_digits == 6
    assert desc.decimal_digits == 6
    assert desc.char_positions == 3
    assert desc.byte_length == 3


def test_parse_pic_alphanumeric_mixing_a_and_9() -> None:
    # "combinations of the symbols A, X, and 9. (A character-string containing
    # all As or all 9s does not define an alphanumeric item.)" -- p. 213.
    desc = parse_pic("AAA9")
    assert desc.category == CobolDataCategory.ALPHANUMERIC
    assert desc.char_positions == 4
    assert desc.byte_length == 4


def test_parse_pic_zero_suppression_counts_every_symbol_as_a_digit() -> None:
    # "Each Z ... a leading numeric character position" -- Table 12, p. 210.
    desc = parse_pic("ZZZZ.ZZ")
    assert desc.category == CobolDataCategory.NUMERIC_EDITED
    assert desc.char_positions == 7
    assert desc.decimal_digits == 2


def test_parse_pic_sign_separate_adds_a_character_position() -> None:
    # "S ... Not counted in the size of the elementary item unless an associated
    # SIGN clause specifies the SEPARATE CHARACTER phrase" -- Table 12, p. 210.
    desc = parse_pic("S9(5)", sign_separate=True)
    assert desc.total_digits == 5
    assert desc.char_positions == 6
    assert desc.byte_length == 6


def test_parse_pic_blank_when_zero_makes_a_numeric_picture_numeric_edited() -> None:
    # "Either the BLANK WHEN ZERO clause must be specified for the item, or the
    # string must contain at least one of the following symbols ..." -- p. 218.
    desc = parse_pic("9(5)", blank_when_zero=True)
    assert desc.category == CobolDataCategory.NUMERIC_EDITED
    assert desc.char_positions == 5
    assert desc.blank_when_zero
