"""The one condition-name -> DFHRESP-code table."""

from __future__ import annotations

import pytest

from cics.conditions import (
    CONDITION_CODES,
    RAISABLE,
    code_for,
    is_raisable_code,
)
from cics.preprocessor import CONDITION_TABLE_SLOTS
from cics.vsam.eibresp import RESP_DISABLED


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


def test_the_raisable_set_is_the_corpus_nine_plus_the_fct_miss_and_pgmiderr():
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
            "DISABLED",
            "PGMIDERR",
        }
    )


def test_normal_is_never_raisable():
    """Slot 0 is NORMAL; a success must never reach the dispatcher."""
    assert is_raisable_code(0) is False


def test_the_raisable_codes_are_the_eleven_written_down_here():
    """Written out independently of CONDITION_CODES: is_raisable_code is defined
    as membership in the codes of RAISABLE, so checking it against code_for()
    would restate the same dict rather than test it. A code that changed on one
    side only fails here."""
    assert {
        code for code in range(CONDITION_TABLE_SLOTS) if is_raisable_code(code)
    } == {
        1,
        13,
        14,
        15,
        16,
        18,
        19,
        22,
        27,
        36,
        84,
    }


def test_the_table_covers_the_file_control_disabled_code():
    """RESP_DISABLED is the code VsamEngine returns for a file with no FCT entry;
    the raise tail subscripts DFH-RAISABLE by EIBRESP + 1, so its slot must exist
    and must be raisable, or the failed READ falls through in silence."""
    assert RESP_DISABLED == 84
    assert CONDITION_TABLE_SLOTS > RESP_DISABLED + 1
    assert is_raisable_code(RESP_DISABLED) is True


def test_an_unknown_condition_name_raises():
    with pytest.raises(KeyError):
        code_for("NOSUCHCONDITION")
