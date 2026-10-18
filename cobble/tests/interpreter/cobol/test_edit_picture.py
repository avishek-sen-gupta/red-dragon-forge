from cobol_asg.edit_cell import EditCell
from cobol_asg.edit_cell_kind import EditCellKind
from cobol_asg.edit_picture import edit_plan, parse_edit_picture


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


def _suppressed(before: int) -> EditCell:
    return EditCell(EditCellKind.SUPPRESSED, "", before)


def _digit(before: int) -> EditCell:
    return EditCell(EditCellKind.DIGIT, "", before)


def test_edit_plan_suppresses_leading_digits_and_inserts_commas_once_significant() -> (
    None
):
    plan = edit_plan("ZZZ,ZZZ.99")
    assert plan.cells == (
        _suppressed(0),
        _suppressed(1),
        _suppressed(2),
        EditCell(EditCellKind.INSERTION, ",", 3),
        _suppressed(3),
        _suppressed(4),
        _suppressed(5),
        EditCell(EditCellKind.FIXED, ".", 6),
        _digit(6),
        _digit(7),
    )
    assert (
        plan.digit_count,
        plan.integer_digits,
        plan.fraction_digits,
        plan.signed,
        plan.all_suppressible,
        plan.zero_image,
    ) == (8, 6, 2, False, False, " " * 10)


def test_edit_plan_blanks_a_zero_when_every_digit_position_is_suppressible() -> None:
    plan = edit_plan("Z(9)")
    assert plan.cells == tuple(_suppressed(n) for n in range(9))
    assert (plan.all_suppressible, plan.zero_image, plan.fill) == (True, " " * 9, " ")


def test_edit_plan_fixed_leading_plus_is_a_sign_cell_showing_plus() -> None:
    plan = edit_plan("+9999")
    assert plan.cells == (
        EditCell(EditCellKind.SIGN, "+", 0),
        *(_digit(n) for n in range(4)),
    )
    assert (plan.signed, plan.digit_count, plan.trailing_sign) == (True, 4, "")
