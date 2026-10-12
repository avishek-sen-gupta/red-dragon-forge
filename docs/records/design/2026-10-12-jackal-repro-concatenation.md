# jackal: IDCAMS REPRO Reads a Concatenated Input — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-2dz)
**Issues:** red-dragon-forge-2dz; follows the 2026-10-12 concatenation record

How IDCAMS `REPRO INFILE(dd)` reads a DD that is a concatenation. Each rule is quoted from IBM's
documentation.

## Sources

| Key | Document |
|---|---|
| AMS | [z/OS 3.1 DFSMS Access Method Services Commands](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idai200_v3r1.pdf) — "REPRO", p. 314 |

## Decisions

**R1. A concatenated INFILE is read member after member, each at its own label.** AMS p. 314:
"The output sequential data set cannot be any of the input data sets in a sequential
concatenation." So REPRO's input may be a sequential concatenation. jackal reads each member in
order at its own label, the way REPRO already reads a single input, and writes every record to
the output. A DUMMY member contributes no records.

**R2. A member whose label is still pending ends the command with condition code 12.** This is
the existing rule for a single input whose label is pending, applied to each member before any
record is copied.

**R3. An output that is one of the input datasets ends the command with condition code 12.** AMS
p. 314 forbids it for a concatenation, and the sentence before forbids it for a single input:
"The same sequential data set cannot be used as both the input and output data set." Using 12
for it is **jackal's own** choice, as for an OPEN that could not be done (record V6). Without the
check, REPRO opens the output over the input and then reads back the records it has just written,
without end.
