# jackal: IDCAMS REPRO and Dataset Labels — Decision Record

**Date:** 2026-10-12
**Status:** implemented (red-dragon-forge-8in, step 2b)
**Issues:** red-dragon-forge-8in; retires jackal-ifq
**Follows:** [A COBOL OPEN and the Dataset's Label](2026-10-11-jackal-cobol-open-record-format.md)

How REPRO reads and writes now that every dataset carries a label. Each rule is quoted from
IBM's z/OS 3.1 documentation.

## Sources

| Key | Document |
|---|---|
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — ch. 7, "Using REPRO to copy a VSAM data set", p. 121 |
| AMS | [z/OS 3.1 DFSMS Access Method Services Commands, SC23-6846-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idai200_v3r1.pdf) — "Condition Codes", p. 22 |
| MSG6 | [z/OS 3.1 MVS System Messages Vol 6 (GOS-IEA), SA38-0673-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieam600_v3r1.pdf) — IDC3003I p. 685, IDC3300I p. 785, IDC3309I p. 790, IDC3321I p. 796 |

## Decisions

**R1. Each side of a REPRO is opened at its own label.** UDS p. 121: a non-VSAM dataset's DCB
parameters are supplied "using the DSCB … or by the DD statement", that is, from its own label
or its own DD. Neither comes from the other dataset in the copy. jackal reads the input at the input's LRECL and writes the output at the
output's. Before this, both sides used the output's length (jackal-ifq).

**R2. An input whose label is pending ends the REPRO with condition code 12, and IDCAMS goes
on to the next command.** With no record format, the input's OPEN fails. IDCAMS intercepts it.
MSG6 IDC3321I: "The OPEN/CLOSE/EOV SVC routines detected an error … System action: The system
ends the command." IDC3300I, "ERROR OPENING", has the same action. MSG6 IDC3003I: "The system
continues processing with the next command. The system sets LASTCC to the condition code", and
MAXCC if greater. The step is not abended.

The code 12 is **inferred**: IBM names no code for this case. AMS p. 22 defines 12 as "The
program could not perform requested function … a logical error … when inconsistent parameters
are given, when required parameters are missing, or when a value for key length, record size, or
buffer space is too small or too large."

**R3. Per-record length checks are not modelled yet.** MSG6 IDC3309I, "RECORD xxx NOT WRITTEN.
LENGTH INVALID", is issued when a record is longer than the output's LRECL, or shorter than it
into a fixed-format output or an RRDS; REPRO "continues processing until four such errors
occur" (UDS p. 121 also ends it on four errors). jackal writes every record; the check is a
follow-up issue.
