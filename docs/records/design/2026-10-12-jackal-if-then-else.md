# jackal: IF/THEN/ELSE/ENDIF Execution — Decision Record

**Date:** 2026-10-12
**Status:** implemented (jackal-1o2.8)
**Issues:** jackal-1o2.8; red-dragon-forge-2cy.7 (the parser keeps the IF structure)

How the runner decides a step inside an `IF/THEN/ELSE/ENDIF` construct. Each rule is quoted
from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| Ref | [z/OS 3.1 MVS JCL Reference, SA23-1385-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — ch. 18, pp. 361–369 |
| UG | [z/OS 2.5 MVS JCL User's Guide, SA23-1386-50](https://www.ibm.com/docs/en/SSLTBW_2.5.0/pdf/ieab500_v2r5.pdf) — ch. 10, pp. 73–75 |

## Decisions

**I1. RC is the highest return code of the steps that ran to completion, starting at 0.**
Ref p. 364: "If you omit stepname, RC refers to the highest job step return code that occurred
during job processing prior to the time of evaluation. This applies only to steps that
execute. Any step that did not start execution, is cancelled, or abnormally ends is not
evaluated. Note: At the start of execution, RC is initially set to zero." The comparison reads
as written: `RC GT 4` is true when RC is greater than 4.

**I2. A test of a named step that did not start is false, and stays false under ¬.** Ref
p. 366: "If the step did not start executing, the system evaluates that part of the expression
as false." `¬stepname.ABEND` and `stepname.ABEND=FALSE` are written as one keyword and parse to
one negated test, so "that part" is the whole negated test: jackal carries a third value, *not
started*, through ¬ and counts it as false in `&`, `|` and the final answer. `stepname.RUN` is
the exception by its definition: it tests whether the step started, so `¬stepname.RUN` is true
for a step that did not (Ref p. 366). A step that started is one that completed or abended;
with names repeated, the first occurrence is used (Ref p. 366: "references to non-unique
stepnames will resolve to the first occurrence").

**I3. `stepname.RC` of a step that abended is false** **(jackal's own)**. The step started, so
Ref p. 366 says the test is performed, but an abended step has no return code to compare.

**I4. `ABENDCC` without a step name tests the most recent abend.** Ref p. 365: "If stepname is
omitted, ABEND=Sxxx and ABENDCC=Uxxxx refer to the most recent abend code that occurred during
the execution of the job prior to the time of evaluation."

**I5. After an abend, a step in an IF construct runs only when the construct tests an abend.**
Ref p. 367, Defaults: "job steps within the IF/THEN/ELSE/ENDIF statement construct do not
execute when • An abend occurred, and • the IF/THEN/ELSE/ENDIF structure containing the job
steps does not specify the ABEND, ABENDCC, or ¬ABEND keyword. If any of these keywords is
specified (with or without stepname or procstepname), the job steps do execute despite the
abend. • The step's COND parameter, if any, does not specify an abend condition (COND=EVEN or
COND=ONLY)." A step's guard holds every enclosing IF's condition, so a keyword anywhere in it
counts. Being eligible is not running: the guard is then evaluated (I6).

**I6. The IF and the step's COND must both allow the step.** Ref p. 367: "the system executes
the job step represented by the EXEC statement only when both the IF/THEN/ELSE/ENDIF statement
construct and the COND parameter evaluate to execute." A false guard is
`Bypassed(IF_CONDITION_FALSE)`, checked before the step's own COND tests; a later step is
unaffected (UG p. 74: "the system bypasses STEP3 and continues processing with step
NEXTSTEP").

**I7. A failed allocation and a met JOB COND still end the job, whatever an IF tests.** Ref
p. 368: "If a step abnormally terminates during scheduling, (due to failures such as JCL errors
or the inability to allocate space), the system bypasses the remaining steps. The steps
specified by the IF/THEN/ELSE/ENDIF statement construct do not execute." jackal's `S322` (its
per-program step budget) is an ordinary abend that an IF can test **(jackal's own)**: Ref
p. 368 exempts only an expired *job* time limit, which jackal does not model.
