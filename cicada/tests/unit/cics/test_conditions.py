"""The one condition-name -> DFHRESP-code table."""

from __future__ import annotations

import pytest

from cics.conditions import (
    CONDITION_CODES,
    MAX_CODE,
    RAISABLE,
    code_for,
    is_raisable_code,
)


def test_codes_match_the_values_already_used_across_the_runtime():
    """These are the codes the scattered modules already encode; the table must
    agree with them or a verb's EIBRESP would stop matching its condition."""
    assert code_for("TERMIDERR") == 11
    assert code_for("NOTFND") == 13
    assert code_for("DUPREC") == 14
    assert code_for("INVREQ") == 16
    assert code_for("IOERR") == 17
    assert code_for("ENDFILE") == 20
    assert code_for("PGMIDERR") == 27
    assert code_for("TRANSIDERR") == 28
    assert code_for("ENDDATA") == 29
    assert code_for("MAPFAIL") == 36


def test_the_raisable_set_is_the_nine_the_corpus_handles():
    assert RAISABLE == frozenset(
        {
            "NOTOPEN",
            "NOTFND",
            "INVREQ",
            "ERROR",
            "LENGERR",
            "MAPFAIL",
            "NOSPACE",
            "DUPKEY",
            "DUPREC",
        }
    )


def test_normal_is_never_raisable():
    """Slot 0 is NORMAL; a success must never reach the dispatcher."""
    assert is_raisable_code(0) is False


def test_every_raisable_condition_has_a_code_and_is_raisable_by_code():
    for name in RAISABLE:
        assert is_raisable_code(code_for(name)) is True


def test_max_code_covers_every_raisable_condition():
    """The injected table is sized MAX_CODE + 1; a raisable code beyond it would
    index past the table."""
    assert MAX_CODE >= max(code_for(name) for name in RAISABLE)


def test_an_unknown_condition_name_raises():
    with pytest.raises(KeyError):
        code_for("NOSUCHCONDITION")
