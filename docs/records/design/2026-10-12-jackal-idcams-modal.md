# jackal: IDCAMS Modal Commands and VERIFY — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-vqa)
**Issues:** red-dragon-forge-vqa; red-dragon-forge-tsw (the comprehensive parser)

How jackal's IDCAMS runs IF-THEN-ELSE, DO-END, SET and CANCEL, and what VERIFY does. These are
grammar productions in the typed IDCAMS grammar (2026-10-12 GDG record, G1). Each rule is quoted
from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| AMS | [z/OS 3.1 DFSMS Access Method Services Commands](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idai200_v3r1.pdf) — ch. 2 "Modal Commands", pp. 15–22; ch. 34 "VERIFY", pp. 357–358 |

## Decisions

**V1. The end of a record ends a THEN or ELSE.** AMS p. 17: "The null command is a THEN or ELSE
command that is not followed by a command continuation character. If THEN or ELSE is not followed
by either a continuation character or by a command in the same record, the THEN or ELSE results
in no action." "A command following a DO must begin on a new line." "END must be on a line by
itself." Line ends are therefore part of jackal's IDCAMS grammar. A `-` at the end of a line
continues the command onto the next one, as before.

**V2. Each ELSE belongs to the nearest unmatched THEN.** AMS p. 16: "The innermost ELSE clause is
associated with the innermost THEN clause … (Each ELSE is matched with the nearest preceding
unmatched THEN.)" A null ELSE balances an inner IF that has none.

**V3. IF tests LASTCC or MAXCC with `=`/EQ, `¬=`/NE, `>`/GT, `<`/LT, `>=`/GE or `<=`/LE.** AMS
p. 16. A branch that is not taken changes nothing. AMS p. 18: "A SET command that follows a THEN
or ELSE that is not run does not alter LASTCC or MAXCC." This replaces an earlier executor bug.
When its test failed, `IF LASTCC … THEN SET MAXCC` set MAXCC to LASTCC.

**V4. SET caps at 16; setting LASTCC can raise MAXCC; 16 ends the stream.** AMS p. 18: "The
maximum value is 16; a greater value is reduced to 16. If the value of LASTCC is greater than
MAXCC, MAXCC is set equal to the larger value." "Setting MAXCC does not affect LASTCC." "You can
end all processing by setting MAXCC or LASTCC to 16." A functional command ending with code 16
also ends the stream. AMS p. 22 lists 16 as "A severe error occurred that erased the remainder
of the command stream".

**V5. CANCEL ends the step with MAXCC.** AMS p. 18: "the remainder of the command stream is not
processed, including any part of an unprocessed IF-THEN-ELSE statement or DO-END pair. The step
ends with a return code in register 15 equal to the highest condition code encountered before the
CANCEL command was run."

**V6. VERIFY (VFY) of a VSAM object succeeds; anything else ends it with condition code 12.**
AMS p. 357: VERIFY "causes a catalog to correctly reflect the end of a VSAM data set after an
error occurs while closing a VSAM data set", for `FILE(ddname)` or `DATASET(entryname)` (`DS`),
with optional RECOVER. jackal never leaves a dataset improperly closed, so there is nothing to
correct. A KSDS reached through the DD, or cataloged under the name, verifies with code 0.
Several cases end the command with code 12, as an OPEN that could not be done (AMS p. 22: "The
program could not perform requested function"):
- a missing DD, or one allocated to anything but a dataset;
- a name that is not cataloged;
- a non-VSAM dataset.

Using 12 for these cases is **jackal's own** choice. It is the code the census retry idiom,
`IF LASTCC=12 THEN DO … VFY … END`, tests for.
