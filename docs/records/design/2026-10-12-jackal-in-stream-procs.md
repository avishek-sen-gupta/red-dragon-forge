# jackal: In-Stream Procedures — Decision Record

**Date:** 2026-10-12
**Status:** accepted (jackal-1o2.2)
**Issues:** jackal-1o2.2; forge-6qr (SET inside a PROC, closed as already working)

How jackal reads and calls a procedure defined inside the job, between PROC and PEND. Each rule
is quoted from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| Ref | [z/OS 3.1 MVS JCL Reference, SA23-1385-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — "In-stream procedures" and "Using a procedure", pp. 25–26; "Using symbols in nested procedures", pp. 47–48 |

## Decisions

**N1. PROC … PEND in a job defines a procedure; its statements are not job steps.** Ref p. 25:
"When you place a procedure in the job input stream, it is called an in-stream procedure. An
in-stream procedure must begin with a PROC statement, end with a PEND statement". The parser
grammar keeps PROC and PEND as flat statements of the job. The bridge used to drop both and
emit the body as job steps, so a defined procedure ran in place and also ran when called. The
bridge now groups the statements between them into a procedure definition. "Do not define one
in-stream procedure within another": a PROC inside an open one, or a PEND without one, is a
syntax error.

**N2. A call finds an in-stream procedure first, then the library.** Ref p. 26: "When you call a
procedure, the system retrieves it using the following search order: 1. From the input stream …
2. From a private library … 3. From the system library". jackal's directory library stands for
2 and 3.

**N3. An in-stream procedure is visible only to calls after its definition.** Ref p. 26: "You
must place the in-stream procedure before the EXEC statement that calls it." A definition takes
effect at its place in the job. An EXEC before it searches the library. A procedure called from
inside another in-stream procedure is looked up when the outer one is expanded, at its calling
EXEC. Ref p. 48's example defines PROC1, which calls PROC2, and then PROC2, both before the job
step that calls PROC1, and that example runs.

**N4. Symbols resolve as in a cataloged procedure.** In-stream procedures take defaults on their
PROC statement and overrides on the calling EXEC, and SET inside them ranks below both (Ref
p. 48, Table 13). Nothing about symbols depends on where the procedure came from.
