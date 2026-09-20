"""Minimal COBOL stand-ins for Db2-supplied callable programs.

A Db2 application CALLs utilities that ship with Db2 itself rather than with
the application, so there is no source for them in any corpus. Squall supplies
small COBOL stand-ins as real ``.cbl`` files under ``squall/stubs/`` and
contributes them through ``CoprocessorSpec.linked_subprogram_sources``, which
links them into every run unit the SQL spec compiles.

Linked outright rather than contributed as a ``source_search_dirs`` entry --
the way cicada offers its LE stubs -- because that search path is only ever
walked from CALL edges a text scan discovered, and ``cobol_asg.cobol_imports``
recognises ``CALL 'LITERAL'`` alone. CardDemo reaches DSNTIAC by data-name, so
no scan can find it and no search path can resolve it (red-dragon-t3kl).

Currently provided
------------------
``DSNTIAC`` (stubs/DSNTIAC.cbl) -- format the SQLCA into an operator-readable
    message. CardDemo's ``9999-FORMAT-DB2-MESSAGE`` (CSDB2RPY.cpy) calls it as::

        CALL LIT-DSNTIAC USING DFHEIBLK, DFHCOMMAREA, SQLCA,
                               WS-DSNTIAC-FORMATTED, WS-DSNTIAC-LRECL

    The 4th argument is the output buffer -- a halfword length followed by the
    text area (CSDB2RWY.cpy lays it out as ten ``PIC X(72)`` lines) -- and the
    5th is the width of one line in it. That halfword is the buffer's capacity
    on the way in, but CardDemo does not supply one: COTRTLIC INITIALIZEs the
    group holding it, storing ZERO over the copybook's ``VALUE +720``. The stub
    takes the text area's declared 720 as the capacity and trusts ``LRECL``,
    the one field 9999-FORMAT-DB2-MESSAGE sets before the CALL, writing the
    formatted length back into the halfword on the way out.

    The stub writes ``DSNTIAC: SQLCODE=<signed code> <SQLERRM text>``, the
    SQLERRM half omitted when ``SQLERRML`` is zero (squall's ``write_sqlcode``
    blanks SQLERRM on every statement, so an ordinary ``+100`` carries no
    prose). It is NOT a reimplementation of IBM's DSNTIAC: no DSNT-prefixed
    message numbers, no substitution-token expansion, and no message catalogue.

Scope / deferrals
-----------------
  * Lines are cut at the byte boundary, not on word boundaries as the real
    utility does. ``LRECL`` still decides how many whole lines the text
    occupies, and that span is validated against the buffer before anything is
    written; the two differ only for a message longer than one line, which
    CardDemo concatenates back into a single string anyway.
  * ``DFHEIBLK`` and ``DFHCOMMAREA`` are accepted and ignored. The real utility
    uses them to issue its own EXEC CICS calls; this stub only formats.
  * **The stub's LINKAGE sizes are the caller's argument sizes.** red-dragon
    packs ``CALL USING`` arguments into one buffer at cumulative offsets and
    the callee reads that buffer through its own LINKAGE offsets, so a stub
    that under-declares an argument it does not even use still misreads every
    later one. DSNTIAC.cbl therefore declares the two arguments it ignores at
    CardDemo's exact widths -- ``DFHEIBLK`` 87 (cicada's copybook) and
    ``DFHCOMMAREA`` 32767 (the ``OCCURS 1 TO 32767 DEPENDING ON EIBCALEN``
    maximum). A caller shaped differently does not silently misformat: its
    ``LRECL`` and ``SQLERRML`` land on other bytes and fail the checks below.
  * An SQLCA or buffer the stub cannot read (line width out of range,
    ``SQLERRML`` outside the VARCHAR) is refused loudly -- it DISPLAYs, sets
    ``RETURN-CODE`` to 12 and leaves a self-identifying failure string in the
    buffer, never a silently empty one.

    The buffer string is what a caller actually sees, and is not belt-and-
    braces: red-dragon gives each program its own SPECIAL_REGISTERS region, so
    a callee's ``RETURN-CODE`` never reaches its caller (red-dragon-ltq6).
    CardDemo's ``COMPUTE WS-DSNTIAC-ERR-CD = RETURN-CODE`` therefore reads its
    own untouched zero and takes the success branch either way. The stub sets
    ``RETURN-CODE`` regardless, so it is already correct once ltq6 lands.
"""

from __future__ import annotations

from pathlib import Path

DB2_STUBS_DIR = Path(__file__).parent / "stubs"


def read_db2_stub_sources() -> dict[str, bytes]:
    """Every Db2 stub as ``{program_name: source_bytes}``, read from disk.

    Reading happens here rather than in ``compile_program``, which threads
    arguments and does no filesystem work: which ``.cbl`` members are squall's
    stubs is squall's knowledge, not the composition layer's.
    """
    return {
        path.stem: path.read_bytes() for path in sorted(DB2_STUBS_DIR.glob("*.cbl"))
    }
