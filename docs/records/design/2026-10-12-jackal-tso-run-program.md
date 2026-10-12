# jackal: TSO Monitor Steps that Run a Db2 Program — Decision Record

**Date:** 2026-10-12
**Status:** accepted (red-dragon-forge-46d)
**Issues:** red-dragon-forge-46d; jackal-1o2.19 (the abend model, whose open decisions D1 and D4
this does not settle)

How jackal runs a step whose `EXEC PGM=` is the TSO terminal monitor (TMP), and whose SYSTSIN
holds `DSN` with `RUN PROGRAM`. Each rule is quoted from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| TSO | [z/OS 3.1 TSO/E Customization](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ikjb400_v3r1.pdf) — Appendix A, "Writing JCL for Command Execution", pp. 688–689 |
| DB2 | [Db2 13 for z/OS Command Reference](https://www.ibm.com/docs/en/SSEPEK_13.0.0/pdf/db2z_13_comrefbook.pdf) — "DSN (TSO)", p. 428 |

## Decisions

**T1. Each `RUN PROGRAM(p)` runs `p` as the step's program, with the step's DDs, in order.** The
TMP takes "The command that is executed … from the first line of input indicated by the
SYSTSIN DD statement" (TSO p. 688). Under DSN, RUN gives control to the named program. jackal
compiles and runs it the way it runs any COBOL step. Its EXEC SQL is served by whatever
coprocessors the runner was given, so the composition stays in `red_dragon_forge`, and jackal
imports no squall. `PLAN` is read and not used: the injected SQL coprocessor already chooses
the database.

**T2. The step's return code is the highest of the programs' return codes.** DB2 p. 428: "At
the end of a DSN session, register 15 contains the highest value used by any DSN subcommand in
the session or by any program run using the RUN subcommand." For IKJEFT01, TSO p. 688: "The
return code returned by the batch IKJEFT01 job … is basically the return code of the last
command that has been executed", and the DSN session is that command. jackal treats all of
SYSTSIN's RUN subcommands as one DSN session, which is the form the census uses.

**T3. A program that abends ends the session: IKJEFT01 returns 12, and IKJEFT1A and IKJEFT1B end
the step with S04C.** TSO p. 688: "If a command or program ABENDs, the TMP will place a return
code of 12 (X'C') in register 15 and terminate the job step normally. No further commands or
subcommands will be executed". TSO p. 689: "If a command or program being processed by
IKJEFT1B ends with a system or user abend, IKJEFT1B causes the job step to terminate with a
X'04C' system completion code." IKJEFT1A does the same for a system abend, and every abend
jackal produces today is a system abend (S806, S322). Under DSN the program is given control by
DSN, not by the TMP itself. Applying the TMP's abend rule to it is **jackal's own** reading.
It matches the reason a Db2 batch step names IKJEFT1B. If the reading is wrong, an IKJEFT1A or
IKJEFT1B step would show S04C where z/OS gives a return code.

**T4. A monitor step with no RUN subcommand runs as before.** jackal models no other TSO
command. Such a step keeps the existing path for a program named IKJEFT01: the missing-program
strategy.
