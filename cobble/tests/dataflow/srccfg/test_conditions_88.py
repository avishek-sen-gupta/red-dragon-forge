"""An 88 name is a predicate on its parent field, and the parent is the
dependency. Resolving it is what stops a guard from reporting a name nothing else
in the corpus mentions."""

from __future__ import annotations

from cobble.dataflow.srccfg.cfg import UNRESOLVED, Atom
from cobble.dataflow.srccfg.conditions import (
    EIGHTY_EIGHT,
    IN,
    RANGE,
    EightyEight,
    condition_index,
    resolve_atom,
)

_WITH_88 = {
    "program_id": "PROGA",
    "data_fields": [
        {
            "name": "WS-GROUP",
            "level": 1,
            "children": [
                {
                    "name": "WS-STATUS",
                    "level": 5,
                    "pic": "X(1)",
                    "conditions": [
                        {"name": "STATUS-ACTIVE", "values": [{"from": "'A'"}]},
                        {
                            "name": "STATUS-VALID",
                            "values": [{"from": "'A'"}, {"from": "'B'"}],
                        },
                        {
                            "name": "STATUS-ALPHA",
                            "values": [{"from": "'A'", "to": "'Z'"}],
                        },
                    ],
                }
            ],
        }
    ],
    "paragraphs": [{"name": "MAIN", "statements": []}],
}


def test_the_index_finds_an_88_nested_under_a_group(asg_of) -> None:
    """Level 88s hang off elementary items that are usually children of an 01
    group, so a scan of the top level alone finds none of them."""
    index = condition_index(asg_of(_WITH_88))

    assert index["STATUS-ACTIVE"] == EightyEight(
        name="STATUS-ACTIVE", parent="WS-STATUS", values=("'A'",), ranges=()
    )


def test_an_88_with_several_discrete_values_keeps_them_all(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))

    assert index["STATUS-VALID"].values == ("'A'", "'B'")


def test_a_thru_range_is_kept_as_a_range_not_flattened(asg_of) -> None:
    """VALUE 'A' THRU 'Z' is not the two values 'A' and 'B'; reporting it as a
    value list would make the guard read as a false equality."""
    index = condition_index(asg_of(_WITH_88))

    assert index["STATUS-ALPHA"] == EightyEight(
        name="STATUS-ALPHA", parent="WS-STATUS", values=(), ranges=(("'A'", "'Z'"),)
    )


def test_the_index_covers_linkage_and_file_and_local_storage(asg_of) -> None:
    """A commarea 88 and an FD-record 88 are as common as a working-storage one,
    and the sections are separate lists on the ASG."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "linkage_fields": [
                {
                    "name": "LK-FLAG",
                    "level": 1,
                    "pic": "X(1)",
                    "conditions": [{"name": "LK-FLAG-ON", "values": [{"from": "'Y'"}]}],
                }
            ],
            "file_fields": [
                {
                    "name": "REC1-CDE",
                    "level": 1,
                    "pic": "X(1)",
                    "conditions": [{"name": "REC1-OK", "values": [{"from": "'0'"}]}],
                }
            ],
            "local_storage_fields": [
                {
                    "name": "LS-MODE",
                    "level": 1,
                    "pic": "X(1)",
                    "conditions": [{"name": "LS-BATCH", "values": [{"from": "'B'"}]}],
                }
            ],
            "paragraphs": [{"name": "MAIN", "statements": []}],
        }
    )

    index = condition_index(asg)

    assert [index[name].parent for name in ("LK-FLAG-ON", "REC1-OK", "LS-BATCH")] == [
        "LK-FLAG",
        "REC1-CDE",
        "LS-MODE",
    ]


def test_resolving_a_single_valued_88_gives_an_equality_on_the_parent(asg_of) -> None:
    """This is the shape a report should show: the name is what the code says, the
    equality is what it means, and the parent is what the query filters on."""
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="STATUS-ACTIVE", left="STATUS-ACTIVE", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == Atom(
        text="STATUS-ACTIVE (WS-STATUS == 'A')",
        left="WS-STATUS",
        op="==",
        right="'A'",
    )


def test_resolving_a_multi_valued_88_gives_a_membership_test(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="STATUS-VALID", left="STATUS-VALID", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == Atom(
        text="STATUS-VALID (WS-STATUS IN 'A' 'B')",
        left="WS-STATUS",
        op=IN,
        right="'A' 'B'",
    )


def test_resolving_a_range_88_says_it_is_a_range(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="STATUS-ALPHA", left="STATUS-ALPHA", op=EIGHTY_EIGHT)

    resolved = resolve_atom(atom, index)

    assert (resolved.left, resolved.op, resolved.right) == (
        "WS-STATUS",
        RANGE,
        "'A' THRU 'Z'",
    )


def test_an_88_the_data_division_does_not_declare_stays_as_it_was(asg_of) -> None:
    """The name is in a copybook the parse could not resolve, or is a paragraph
    name the ASG typed as a condition. Either way the atom is still the guard that
    was written, so it is kept rather than dropped or turned into UNRESOLVED."""
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="NOT-DECLARED", left="NOT-DECLARED", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == atom


def test_an_atom_that_is_not_an_88_is_returned_untouched(asg_of) -> None:
    index = condition_index(asg_of(_WITH_88))
    atom = Atom(text="WS-FLAG-A == 'Y'", left="WS-FLAG-A", op="==", right="'Y'")

    assert resolve_atom(atom, index) == atom
    assert resolve_atom(UNRESOLVED, index) == UNRESOLVED


def test_a_program_with_no_data_division_has_an_empty_index(asg_of) -> None:
    index = condition_index(asg_of({"program_id": "PROGA"}))

    assert dict(index) == {}


def test_a_mixed_88_with_both_discrete_values_and_ranges_keeps_all(asg_of) -> None:
    """VALUE 'A' 'B' 'X' THRU 'Z' lists every alternative the field might hold, so
    the resolution must list every alternative too."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "data_fields": [
                {
                    "name": "WS-CODE",
                    "level": 5,
                    "pic": "X(1)",
                    "conditions": [
                        {
                            "name": "CODE-VALID",
                            "values": [
                                {"from": "'A'"},
                                {"from": "'B'"},
                                {"from": "'X'", "to": "'Z'"},
                            ],
                        }
                    ],
                }
            ],
            "paragraphs": [{"name": "MAIN", "statements": []}],
        }
    )
    index = condition_index(asg)
    atom = Atom(text="CODE-VALID", left="CODE-VALID", op=EIGHTY_EIGHT)

    resolved = resolve_atom(atom, index)

    assert resolved == Atom(
        text="CODE-VALID (WS-CODE IN 'A' 'B' 'X' THRU 'Z')",
        left="WS-CODE",
        op=IN,
        right="'A' 'B' 'X' THRU 'Z'",
    )


def test_the_same_88_name_under_different_parents_stays_unresolved(asg_of) -> None:
    """Two fields each declare an 88 named FLAG-ON, and resolving to either one is
    a guess. The atom is kept rather than bound to an arbitrary parent."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "data_fields": [
                {
                    "name": "WS-FLAG-A",
                    "level": 5,
                    "pic": "X(1)",
                    "conditions": [{"name": "FLAG-ON", "values": [{"from": "'Y'"}]}],
                },
                {
                    "name": "WS-FLAG-B",
                    "level": 5,
                    "pic": "X(1)",
                    "conditions": [{"name": "FLAG-ON", "values": [{"from": "'Y'"}]}],
                },
            ],
            "paragraphs": [{"name": "MAIN", "statements": []}],
        }
    )
    index = condition_index(asg)
    atom = Atom(text="FLAG-ON", left="FLAG-ON", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == atom


def test_the_same_88_name_with_identical_meaning_still_resolves(asg_of) -> None:
    """A field and its REDEFINES both declare STATUS-OK with the same parent and
    value, so the resolution is unambiguous."""
    asg = asg_of(
        {
            "program_id": "PROGA",
            "data_fields": [
                {
                    "name": "WS-REC",
                    "level": 1,
                    "children": [
                        {
                            "name": "WS-STATUS",
                            "level": 5,
                            "pic": "X(1)",
                            "conditions": [
                                {"name": "STATUS-OK", "values": [{"from": "'0'"}]}
                            ],
                        }
                    ],
                },
                {
                    "name": "WS-REC-ALT",
                    "level": 1,
                    "redefines": "WS-REC",
                    "children": [
                        {
                            "name": "WS-STATUS",
                            "level": 5,
                            "pic": "X(1)",
                            "conditions": [
                                {"name": "STATUS-OK", "values": [{"from": "'0'"}]}
                            ],
                        }
                    ],
                },
            ],
            "paragraphs": [{"name": "MAIN", "statements": []}],
        }
    )
    index = condition_index(asg)
    atom = Atom(text="STATUS-OK", left="STATUS-OK", op=EIGHTY_EIGHT)

    assert resolve_atom(atom, index) == Atom(
        text="STATUS-OK (WS-STATUS == '0')",
        left="WS-STATUS",
        op="==",
        right="'0'",
    )
