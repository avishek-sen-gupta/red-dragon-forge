"""CICS text pre-pass — runs before ProLeap parses COBOL source."""

from __future__ import annotations

import logging

from cics.conditions import RAISABLE, code_for

logger = logging.getLogger(__name__)

# Canonical CICS DFHRESP / EIBRESP code set. The contiguous 0-44 block is the
# standard IBM-documented EIBRESP value set; every code is unique so that two
# distinct conditions can never compare-equal after substitution. Higher codes
# below are additional names the translator output references.
_DFHRESP_TABLE: dict[str, int] = {
    # --- Standard contiguous EIBRESP set (0-44) ---
    "NORMAL": 0,
    "ERROR": 1,
    "RDATT": 2,
    "WRBRK": 3,
    "EOF": 4,
    "EODS": 5,
    "EOC": 6,
    "INBFMH": 7,
    "ENDINPT": 8,
    "NONVAL": 9,
    "NOSTART": 10,
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
    "QZERO": 23,
    "SIGNAL": 24,
    "QBUSY": 25,
    "ITEMERR": 26,
    "PGMIDERR": 27,
    "TRANSIDERR": 28,
    "ENDDATA": 29,
    "INVTSREQ": 30,
    "EXPIRED": 31,
    "RETPAGE": 32,
    "RTEFAIL": 33,
    "RTESOME": 34,
    "TSIOERR": 35,
    "MAPFAIL": 36,
    "INVERRTERM": 37,
    "INVMPSZ": 38,
    "IGREQID": 39,
    "OVERFLOW": 40,
    "INVLDC": 41,
    "NOSTG": 42,
    "JIDERR": 43,
    "QIDERR": 44,
    # --- Additional names referenced by translator output (higher codes) ---
    "SYSIDERR": 53,
    "ISCINVREQ": 54,
    "SYSBUSY": 79,
    "TERMERR": 81,
    "SESSIONERR": 82,
    "DISABLED": 84,
    # --- De-collided non-standard names (kept for compatibility, unused) ---
    "LENOVF": 522,  # was 27, which collides with PGMIDERR
    "UNEXPIN": 523,  # non-standard; canonical 35 collides with TSIOERR, kept distinct
}

# EIBRESP can legitimately hold any code in the table above — DISABLED (84) is
# returned by VsamEngine for a file with no FCT entry, and the raise tail
# subscripts DFH-RAISABLE by EIBRESP + 1 — so the injected tables are sized from
# that ceiling, not from the handful of conditions cics.conditions names. An
# OCCURS sized any smaller is subscripted out of bounds by a legal EIBRESP, and
# emit_context.resolve_field_ref does not bounds-check.
CONDITION_TABLE_SLOTS: int = max(_DFHRESP_TABLE.values()) + 1

# Sentinel for unknown/typo'd conditions. Chosen so it can never equal a real
# EIBRESP value a program checks — substituting 0 (=NORMAL) would let a bogus
# condition silently masquerade as the normal path.
_DFHRESP_UNKNOWN = 9999

# 7 spaces = Area A (column 8); valid for COPY, matches IBM CICS translator output
_DFHEIBLK_COPY = "       COPY DFHEIBLK."
_DFHHANDLE_COPY = "       COPY DFHHANDLE."


def _code_area(line: str) -> str:
    """Return the line's code area — columns 8-72 (``line[7:72]``), always.

    The ProLeap bridge is hard-wired to FIXED format, so this positional slice
    is correct for every real program; a line has no sequence number, no
    indicator, and no code area it did not already have, and Python slicing
    on a short string never raises — a line shorter than 8 characters simply
    yields an empty (or partial) code area.

    Re-derives the same fixed-format zone model squall.fixed_format.py:33-36
    names in one place; the import-linter contract forbids cicada importing
    squall, so this constant cannot be shared, only kept in step by hand.
    """
    return line[7:72]


def _is_comment_line(line: str) -> bool:
    """True when col 7 (``line[6]``) is a comment indicator (``*`` or
    ``/``).

    Same fixed-format indicator column squall.fixed_format.py:33-36 names as
    ``_INDICATOR_END``; see ``_code_area`` above for why it is re-derived
    rather than imported.
    """
    return len(line) >= 7 and line[6] in ("*", "/")


def _is_ws_section(line: str) -> bool:
    if _is_comment_line(line):
        return False
    tokens = _code_area(line).strip().upper().split()
    return (
        len(tokens) >= 2 and tokens[0] == "WORKING-STORAGE" and tokens[1] == "SECTION."
    )


def _inject_after_ws_section(source: str, copy_line: str) -> str:
    lines = source.splitlines(keepends=True)
    section = next(
        (index for index, line in enumerate(lines) if _is_ws_section(line)), len(lines)
    )
    found = section < len(lines)
    logger.debug(
        (
            "%s injected after WORKING-STORAGE SECTION"
            if found
            else "no WORKING-STORAGE SECTION found; %s not injected"
        ),
        copy_line.strip(),
    )
    inserted = (
        [copy_line + ("\r\n" if lines[section].endswith("\r\n") else "\n")]
        if found
        else []
    )
    return "".join(lines[: section + 1] + inserted + lines[section + 1 :])


def inject_dfheiblk(source: str) -> str:
    """Insert COPY DFHEIBLK. on the line immediately after WORKING-STORAGE SECTION."""
    return _inject_after_ws_section(source, _DFHEIBLK_COPY)


def raisable_literal() -> str:
    """The DFH-RAISABLE VALUE literal, generated from the condition table so the
    copybook cannot drift from it."""
    codes = {code_for(name) for name in RAISABLE}
    return "".join(
        "Y" if code in codes else "N" for code in range(CONDITION_TABLE_SLOTS)
    )


def inject_dfhhandle(source: str) -> str:
    """Insert COPY DFHHANDLE. on the line immediately after WORKING-STORAGE SECTION."""
    return _inject_after_ws_section(source, _DFHHANDLE_COPY)


def apply_cics_prepass(source: str) -> str:
    """Apply all CICS pre-pass transformations to COBOL source.

    DFHRESP(condition) literals are now lowered structurally by the ProLeap
    bridge (red-dragon-kieo) — no text substitution needed here.
    """
    logger.debug("CICS pre-pass: %d bytes", len(source))
    return inject_dfhhandle(inject_dfheiblk(source))
