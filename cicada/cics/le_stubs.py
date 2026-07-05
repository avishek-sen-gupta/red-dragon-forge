"""Minimal COBOL stubs for IBM Language Environment (LE) callable services.

Some CardDemo programs CALL LE services that have no COBOL source in the
application (they are supplied by the z/OS LE runtime). To let those programs
run end to end under RedDragon, we ship small COBOL stand-ins as real .cbl
files under cics/stubs/, resolved exactly like any other CALLed subprogram —
compile_cics_program always includes LE_STUBS_DIR in its on-disk CALL
resolution search path (see cics.bootstrap), so no caller-supplied dict of
in-memory sources is needed.

Currently provided
-------------------
``CEEDAYS`` (cics/stubs/CEEDAYS.cbl) — convert a date string to Lilian days
    and set a feedback code.
    CSUTLDTC.cbl calls it as::

        CALL "CEEDAYS" USING WS-DATE-TO-TEST   (Vstring: S9(4) BINARY len + text)
                             WS-DATE-FORMAT     (Vstring: S9(4) BINARY len + text)
                             OUTPUT-LILLIAN     (S9(9) BINARY)
                             FEEDBACK-CODE      (12-byte LE feedback token)

    CSUTLDTC only cares about the feedback *severity*: it moves
    ``SEVERITY OF FEEDBACK-CODE`` (the first ``S9(4) BINARY`` halfword of the
    token) into a ``PIC 9(4)`` and the caller (COTRN02C) tests
    ``CSUTLDTC-RESULT-SEV-CD = '0000'``. The LE convention is that an all-zero
    feedback token means success (severity 0); CSUTLDTC's ``FC-INVALID-DATE``
    88-level (``VALUE X'00...00'``) maps to the "Date is valid" branch.

    This stub validates the date assuming the standard CardDemo picture string
    ``YYYY-MM-DD`` (the only format COTRN02C passes, via WS-DATE-FORMAT). On a
    valid Gregorian date it sets the whole feedback token to zero (severity 0)
    and the Lilian-days output; on an invalid date it sets severity 12 (a
    nonzero LE-style severity) so the caller's ``SEV-CD = '0000'`` test fails and
    the date-validation error path runs.

Scope / deferrals
-----------------
  * Only the ``YYYY-MM-DD`` picture string is honoured; other LE picture strings
    (e.g. ``MM/DD/YYYY``, Julian, era forms) are not parsed — any non-numeric or
    out-of-range component yields severity 12. CardDemo's transaction-add flow
    always passes ``YYYY-MM-DD``.
  * The Lilian-days output is computed as days since 1600-12-31 (reusing the
    existing ``INTEGER-OF-DATE`` semantics) rather than the true LE Lilian epoch
    of 1582-10-14. CSUTLDTC discards the Lilian value for its valid/invalid
    decision (only the severity gates the flow), so the absolute epoch is
    immaterial to the programs that consume it here.
  * The specific message-number tokens CSUTLDTC distinguishes (insufficient
    data, bad era, etc.) are not reproduced; valid → severity 0, invalid →
    severity 12. COTRN02C's secondary ``MSG-NUM = '2513'`` check is only
    consulted when severity is nonzero, and treats any non-2513 as a hard error
    — which is the correct outcome for a genuinely invalid date.
"""

from __future__ import annotations

from pathlib import Path

LE_STUBS_DIR = Path(__file__).parent / "stubs"
