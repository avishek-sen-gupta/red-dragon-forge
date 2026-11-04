"""Reading the ASG's condition dicts into a tree of atoms.

Nothing here lowers anything: the point is that every shape the cache holds
becomes either an atom with its parts filled in or, when it cannot be read, an
UNRESOLVED atom that still occupies a leaf.
"""

from __future__ import annotations

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.conditions import (
    ALWAYS,
    EIGHTY_EIGHT,
    And,
    Not,
    Or,
    negate_atom,
    read_condition,
    read_when_object,
)
from cobol_asg.any_object import AnyObject
from cobol_asg.selection_condition import SelectionCondition
from cobol_asg.truth_value import TruthValue


def _rel(left: str, op: str, right: str, negated: bool = False) -> dict:
    return {
        "not": negated,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": op,
            "right": {"kind": "lit", "value": right},
        },
    }


def test_a_relational_condition_becomes_one_atom_with_its_parts() -> None:
    assert read_condition(_rel("WS-FLAG-A", "==", "'Y'")) == Atom(
        text="WS-FLAG-A == 'Y'",
        left="WS-FLAG-A",
        op="==",
        right="'Y'",
        plain=True,
    )


def test_a_field_on_both_sides_keeps_both_names() -> None:
    """A guard comparing two fields is a dependency on both of them, so neither
    side may be flattened into text."""
    raw = {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": "WS-FLAG-A"},
            "op": "==",
            "right": {"kind": "ref", "name": "WS-FLAG-B"},
        },
    }

    assert read_condition(raw) == Atom(
        text="WS-FLAG-A == WS-FLAG-B",
        left="WS-FLAG-A",
        op="==",
        right="WS-FLAG-B",
        plain=True,
    )


def test_a_negated_relation_becomes_a_not_around_the_atom() -> None:
    """NOT stays a node rather than flipping the operator: the lowering pass
    implements it by swapping edges, and an operator flip would be wrong for a
    class test or an 88 name where there is no operator to flip."""
    assert read_condition(_rel("WS-FLAG-A", "==", "'Y'", negated=True)) == Not(
        inner=Atom(
            text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'", plain=True
        )
    )


def test_and_and_or_nest_left_and_right() -> None:
    raw = {
        "op": "OR",
        "left": _rel("WS-FLAG-A", "==", "'Y'"),
        "right": {
            "op": "AND",
            "left": _rel("WS-FLAG-B", "==", "'N'"),
            "right": _rel("WS-TYPE-C", "==", "'G'"),
        },
    }

    assert read_condition(raw) == Or(
        left=Atom(
            text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'", plain=True
        ),
        right=And(
            left=Atom(
                text="WS-FLAG-B == 'N'",
                left="WS-FLAG-B",
                op="==",
                right="'N'",
                plain=True,
            ),
            right=Atom(
                text="WS-TYPE-C == 'G'",
                left="WS-TYPE-C",
                op="==",
                right="'G'",
                plain=True,
            ),
        ),
    )


def test_a_parenthesised_subcondition_is_read_through() -> None:
    raw = {"not": False, "condition": _rel("WS-FLAG-A", "==", "'Y'")}

    assert read_condition(raw) == Atom(
        text="WS-FLAG-A == 'Y'",
        left="WS-FLAG-A",
        op="==",
        right="'Y'",
        plain=True,
    )


def test_a_negated_parenthesised_subcondition_negates_the_whole_group() -> None:
    """NOT (A AND B) is not NOT A AND NOT B, and the group is the only place the
    ASG records that the negation is outside the combination."""
    raw = {
        "not": True,
        "condition": {
            "op": "AND",
            "left": _rel("WS-FLAG-A", "==", "'Y'"),
            "right": _rel("WS-FLAG-B", "==", "'N'"),
        },
    }

    result = read_condition(raw)
    assert isinstance(result, Not)
    assert isinstance(result.inner, And)


def test_a_condition_name_becomes_an_atom_naming_the_88() -> None:
    """An 88 level is a named predicate on its parent field. Until the data
    division is consulted the name is all there is, and it is a real dependency."""
    raw = {"not": False, "condition_name": "WS-FLAG-A-SET"}

    assert read_condition(raw) == Atom(
        text="WS-FLAG-A-SET",
        left="WS-FLAG-A-SET",
        op=EIGHTY_EIGHT,
        right="",
        plain=True,
    )


def test_a_class_test_keeps_the_operand_and_the_class() -> None:
    raw = {
        "not": False,
        "class": "NUMERIC",
        "operand": {"kind": "ref", "name": "WS-AMOUNT"},
    }

    assert read_condition(raw) == Atom(
        text="WS-AMOUNT IS NUMERIC", left="WS-AMOUNT", op="CLASS", right="NUMERIC"
    )


def test_a_dfhresp_operand_reads_as_the_condition_it_names() -> None:
    """EXEC CICS response tests are guards like any other, and the field they read
    is the response code the preceding command set."""
    raw = {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": "WS-RESP"},
            "op": "==",
            "right": {"kind": "dfhresp", "condition": "NORMAL"},
        },
    }

    assert read_condition(raw) == Atom(
        text="WS-RESP == DFHRESP(NORMAL)",
        left="WS-RESP",
        op="==",
        right="DFHRESP(NORMAL)",
        plain=True,
    )


def test_a_bare_string_condition_is_an_atom_of_that_text() -> None:
    """EVALUATE WHEN gives its subject as plain text when it is an 88 name or a
    literal, and SEARCH WHEN gives the whole predicate that way."""
    assert read_condition("WS-FLAG-A-SET") == Atom(
        text="WS-FLAG-A-SET",
        left="WS-FLAG-A-SET",
        op=EIGHTY_EIGHT,
        right="",
        plain=True,
    )


def test_a_shape_this_pass_does_not_know_is_unresolved_not_an_error() -> None:
    """One unreadable predicate must cost that predicate's parts, not the member.
    The leaf still exists, so the path through it still exists."""
    assert read_condition({"something": "new"}) == UNRESOLVED


def test_an_empty_condition_is_unresolved() -> None:
    assert read_condition(None) == UNRESOLVED


def test_negating_an_atom_for_a_report_flips_the_operator() -> None:
    """The graph negates by taking the FALSE edge. A report that prints one path
    still needs prose for that edge, and for a relation the readable form is the
    flipped operator."""
    atom = Atom(text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'")

    assert negate_atom(atom) == Atom(
        text="WS-FLAG-A != 'Y'", left="WS-FLAG-A", op="!=", right="'Y'"
    )


def test_negating_a_predicate_with_no_opposite_operator_says_not() -> None:
    """An 88 name and a class test have no flipped operator, so the readable form
    is a NOT prefix -- and the parts stay as they were, because the field being
    depended on has not changed."""
    atom = Atom(text="WS-FLAG-A-SET", left="WS-FLAG-A-SET", op=EIGHTY_EIGHT)

    assert negate_atom(atom).text == "NOT WS-FLAG-A-SET"
    assert negate_atom(atom).left == "WS-FLAG-A-SET"


def test_negating_the_unresolved_atom_stays_unresolved() -> None:
    assert negate_atom(UNRESOLVED).resolved is False


def _fig(left: str, op: str, constant: str) -> dict:
    """`IF IRRA-ERR-CDE = SPACES` -- the shape the cache actually holds."""
    return {
        "not": False,
        "relation": {
            "left": {"kind": "ref", "name": left},
            "op": op,
            "right": {"kind": "figurative", "value": constant},
        },
    }


def test_a_figurative_constant_is_kept_as_the_right_operand() -> None:
    """SPACES and LOW-VALUES arrive with kind "figurative", not "lit". Dropping them
    printed the guard as "IRRA-ERR-CDE == " with nothing on the right, which names no
    condition a reader can check against the listing."""
    assert read_condition(_fig("IRRA-ERR-CDE", "==", "SPACES")) == Atom(
        text="IRRA-ERR-CDE == SPACES",
        left="IRRA-ERR-CDE",
        op="==",
        right="SPACES",
        plain=True,
    )


def test_two_figurative_constants_in_one_condition_stay_distinct() -> None:
    """`IF X = SPACES OR LOW-VALUES` lowers to two tests. With both right operands
    empty the two atoms were byte-identical, so a guard listing could not say which
    branch tested which -- the halves became indistinguishable rather than merely
    unlabelled."""
    both = read_condition(
        {
            "op": "OR",
            "left": _fig("IRRA-ERR-CDE", "==", "SPACES"),
            "right": _fig("IRRA-ERR-CDE", "==", "LOW-VALUES"),
        }
    )

    assert both == Or(
        left=Atom(
            text="IRRA-ERR-CDE == SPACES",
            left="IRRA-ERR-CDE",
            op="==",
            right="SPACES",
            plain=True,
        ),
        right=Atom(
            text="IRRA-ERR-CDE == LOW-VALUES",
            left="IRRA-ERR-CDE",
            op="==",
            right="LOW-VALUES",
            plain=True,
        ),
    )


def test_a_figurative_constant_is_not_reported_as_a_field_dependency() -> None:
    """It goes into `right`, and is_literal already covers the figurative names, so
    filling it in must not turn SPACES into a field written nowhere."""
    from cobble.dataflow.srccfg.literals import is_literal

    atom = read_condition(_fig("IRRA-ERR-CDE", "==", "SPACES"))

    assert isinstance(atom, Atom)
    assert is_literal(atom.right)


def test_under_evaluate_false_a_when_is_reached_when_its_condition_fails() -> None:
    """EVALUATE FALSE selects the first WHEN whose condition is false, so the
    branch guard is the negation of what EVALUATE TRUE would test."""
    named = SelectionCondition(
        condition={"not": False, "condition_name": "INPUT-ERROR"}
    )
    tested = Atom(text="INPUT-ERROR", left="INPUT-ERROR", op=EIGHTY_EIGHT, plain=True)

    assert (
        read_when_object(named, TruthValue(value=True)),
        read_when_object(named, TruthValue(value=False)),
    ) == (tested, Not(inner=tested))


def test_under_evaluate_false_when_any_still_always_matches() -> None:
    assert read_when_object(AnyObject(), TruthValue(value=False)) == ALWAYS


def test_an_atom_is_plain_only_when_neither_operand_selects_part_of_a_field() -> None:
    """A test on F(1:1) or T(I) reads bytes the field's name does not say, so the
    atom is marked not plain; an analysis that follows bytes must not read it as a
    comparison of the whole field. A condition name with a subscript likewise."""

    def relation(left: dict) -> dict:
        return {
            "not": False,
            "relation": {
                "left": left,
                "op": "==",
                "right": {"kind": "lit", "value": "'Y'"},
            },
        }

    whole = relation({"kind": "ref", "name": "F"})
    part = relation(
        {
            "kind": "ref",
            "name": "F",
            "ref_mod_start": {"kind": "lit", "value": "1"},
            "ref_mod_length": {"kind": "lit", "value": "1"},
        }
    )
    row = relation(
        {"kind": "ref", "name": "T", "subscripts": [{"kind": "ref", "name": "I"}]}
    )
    flag = {"condition_name": "F-ON"}
    flag_row = {
        "condition_name": "T-ON",
        "condition_subscripts": [{"kind": "ref", "name": "I"}],
    }

    whole_atom = Atom(text="F == 'Y'", left="F", op="==", right="'Y'", plain=True)
    part_atom = Atom(text="F == 'Y'", left="F", op="==", right="'Y'", plain=False)

    assert [read_condition(raw) for raw in (whole, part, row, flag, flag_row)] == [
        whole_atom,
        part_atom,
        Atom(text="T == 'Y'", left="T", op="==", right="'Y'", plain=False),
        Atom(text="F-ON", left="F-ON", op=EIGHTY_EIGHT, plain=True),
        Atom(text="T-ON", left="T-ON", op=EIGHTY_EIGHT, plain=False),
    ]
    assert (negate_atom(whole_atom).plain, negate_atom(part_atom).plain) == (
        True,
        False,
    )
