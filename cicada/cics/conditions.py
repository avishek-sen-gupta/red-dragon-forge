"""CICS condition names and their DFHRESP codes.

The single source of truth these codes are converging on. They are still also
spelled as module constants in cics/vsam/eibresp.py, cics/builtins/system.py,
cics/builtins/interval.py and cics/builtins/screen.py, and as a fifth table in
cics/preprocessor.py; the injected handler table, the raise tail and the
unhandled abend all index by code, so they need one table to agree on, and
those spellings are meant to fold into this one.
"""

from __future__ import annotations

CONDITION_CODES: dict[str, int] = {
    "NORMAL": 0,
    "ERROR": 1,
    "EOF": 4,
    "TERMIDERR": 11,
    "FILENOTFOUND": 12,
    "NOTFND": 13,
    "DUPREC": 14,
    "DUPKEY": 15,
    "INVREQ": 16,
    "IOERR": 17,
    "NOSPACE": 18,
    "NOTOPEN": 19,
    "ENDFILE": 20,
    "ILLOGIC": 21,
    "LENGERR": 22,
    "ITEMERR": 26,
    "PGMIDERR": 27,
    "TRANSIDERR": 28,
    "ENDDATA": 29,
    "MAPFAIL": 36,
    "DISABLED": 84,
}

# The conditions this runtime raises: the ones the production corpus codes
# HANDLE CONDITION for, plus DISABLED. Everything else keeps writing EIBRESP and
# nothing more, which is exactly as truthful as it is today.
#
# DISABLED is not a corpus-handled condition; it is what VsamEngine returns for a
# file with no FCT entry. Left unraisable, such a READ falls through to code that
# then uses an untouched record area as though the read had succeeded — the exact
# silent wrong answer this machinery exists to stop.
RAISABLE: frozenset[str] = frozenset(
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
    }
)

# IBM assigns a distinct AEIx code per unhandled condition. That mapping is not
# reproduced here because it has not been sourced from documentation; one code
# naming the condition in its message beats inventing letters that read as
# authoritative. See the design doc's "__cics_abend_unhandled" section.
UNHANDLED_ABCODE = "AEIZ"

_RAISABLE_CODES: frozenset[int] = frozenset(CONDITION_CODES[name] for name in RAISABLE)


def code_for(name: str) -> int:
    """The DFHRESP code for a condition name. Raises KeyError on an unknown name
    — the table is exhaustive for what this runtime produces, and a new condition
    must be added deliberately."""
    return CONDITION_CODES[name]


def is_raisable_code(code: int) -> bool:
    return code in _RAISABLE_CODES
