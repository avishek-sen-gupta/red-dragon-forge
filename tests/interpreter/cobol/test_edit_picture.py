import pytest

from cobble.interpreter.cobol.edit_picture import (
    format_edited,
    parse_edit_picture,
)


def test_parse_edit_picture_expands_repeat_counts() -> None:
    ep = parse_edit_picture("Z(9).99")
    assert ep.width == 12
    assert ep.int_digits == 9
    assert ep.frac_digits == 2
    assert not ep.signed
    # Not all_suppressible: the fraction's "99" positions are '9', not 'Z'.
    assert not ep.all_suppressible


def test_parse_edit_picture_all_suppressible_when_every_digit_position_is_z() -> None:
    ep = parse_edit_picture("Z(9)")
    assert ep.all_suppressible


def test_parse_edit_picture_detects_leading_sign() -> None:
    ep = parse_edit_picture("+ZZZ,ZZZ,ZZZ.99")
    assert ep.signed
    assert ep.sign_symbol == "+"
    assert ep.sign_leading


def test_parse_edit_picture_detects_trailing_sign() -> None:
    ep = parse_edit_picture("Z(9).99-")
    assert ep.signed
    assert ep.sign_symbol == "-"
    assert not ep.sign_leading


def test_format_edited_suppresses_leading_zeros_and_inserts_commas() -> None:
    assert format_edited("1234.5", "ZZZ,ZZZ.99") == "  1,234.50"


def test_format_edited_all_suppressible_zero_is_blank() -> None:
    assert format_edited("0", "Z(9)") == " " * 9


def test_format_edited_fixed_sign_plus_shows_minus_for_negative() -> None:
    assert format_edited("-42", "+9999") == "-0042"


def test_format_edited_fixed_sign_plus_shows_plus_for_positive() -> None:
    assert format_edited("42", "+9999") == "+0042"


def test_format_edited_truncates_extra_fraction_digits() -> None:
    assert format_edited("1.999", "9.99") == "1.99"


@pytest.mark.parametrize("bad_value", ["", "not-a-number"])
def test_format_edited_defaults_bad_input_to_zero(bad_value: str) -> None:
    assert format_edited(bad_value, "9999") == "0000"
