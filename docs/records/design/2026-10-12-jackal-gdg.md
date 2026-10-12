# jackal: Generation Data Groups — Decision Record

**Date:** 2026-10-12
**Status:** accepted (jackal-1o2.4)
**Issues:** jackal-1o2.4; red-dragon-forge-vqa (IDCAMS grammar); red-dragon-forge-2cy.4 (the parser
types a relative generation)

How jackal defines a GDG, resolves a relative generation, and rolls generations in and off. Each
rule is quoted from IBM's documentation.

## Sources

| Key | Document |
|---|---|
| AMS | [z/OS 3.1 DFSMS Access Method Services Commands](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idai200_v3r1.pdf) — ch. 2 "Condition Codes", p. 22; ch. 15 "DEFINE GENERATIONDATAGROUP", pp. 177–181; LISTCAT GDG example, p. 432 |
| UDS | [z/OS 3.1 DFSMS Using Data Sets](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/idad400_v3r1.pdf) — ch. 29 "Processing generation data groups", pp. 478, 483–484 |
| Ref | [z/OS 3.1 MVS JCL Reference, SA23-1385-60](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieab600_v3r1.pdf) — "GDGBIAS parameter", p. 403; DD VOLUME GDG considerations, pp. 286–287 |
| MSG | [z/OS 3.1 MVS System Messages Vol 6](https://www.ibm.com/docs/en/SSLTBW_3.1.0/pdf/ieam600_v3r1.pdf) — IDC3003I, IDC3013I |

## Decisions

**G1. IDCAMS grows its typed grammar; the comprehensive parser stays unwired.** DEFINE
GENERATIONDATAGROUP, VERIFY and IF-THEN-DO-END are added to the grammar the executor already
uses (`jackal/idcams/grammar.lark`), as grammar productions. Moving IDCAMS to the comprehensive
parser is a separate, later issue (user decision, 2026-10-12: that file carries 342 pyright
errors and about 450 lint violations, and the census items should not wait for it).

**G2. DEFINE GENERATIONDATAGROUP takes NAME, LIMIT, EMPTY|NOEMPTY and SCRATCH|NOSCRATCH.** AMS
p. 177 gives the syntax and the abbreviations DEF, GDG, LIM, EMP, NEMP, SCR and NSCR. LIMIT is
"from 1 to 255 … If EXTENDED is specified, 1 to 999". OWNER, FIFO|LIFO, PURGE|NOPURGE and
CATALOG are accepted and not modelled: jackal has one catalog, no owners, no expiration dates,
and no reference to a bare GDG base yet. A LIMIT out of range ends the command with condition
code 12, which AMS p. 22 gives for "inconsistent parameters".

Defaults. NOSCRATCH is stated (AMS p. 179: "The default can be changed from NOSCRATCH to
SCRATCH"). For NOEMPTY the text states no default. AMS p. 432 lists a GDG base with
`NOSCRATCH NOEMPTY LIFO NOPURGE NOEXTENDED`, which is the set of documented defaults for the
other four. jackal therefore takes **NOEMPTY**. If that is wrong, a GDG at its limit would keep
too many generations.

**G3. Defining a name already in the catalog ends the command with condition code 12.** IDC3013I
"DUPLICATE DATA SET NAME": "The system ends processing of the command"; IDC3003I "FUNCTION
TERMINATED. CONDITION CODE IS cde" reports the code (MSG). AMS p. 22's table describes code 8
with "a duplicate name was found while an entry was being defined and the define action ended".
jackal keeps 12. That matches DEFINE CLUSTER, which already returns 12. It also matches corpus
practice, where every define-if-absent idiom tests `IF LASTCC=12 THEN SET MAXCC=0`. If 8 is
right, those idioms would leave MAXCC at 8.

**G4. The GDG base is a catalog entry that holds its generations in order.** AMS p. 432 shows
a base's ASSOCIATIONS as its active generations, oldest first. jackal records the base (name,
limit, roll-off, scratch) and its active absolute generation numbers in the persistent system
catalog. It never works them out from dataset names.

**G5. A relative generation resolves once per job (GDGBIAS=JOB).** Ref p. 403: "The system
establishes the relationship between the relative generation number and the absolute generation
number when the generation data set is first referenced in the job. This relationship is
consistent throughout the job." "For job classes that do not specify a default for the GDGBIAS
parameter, GDGBIAS=JOB is used." Ref p. 286 gives the worked case. The latest generation at the
start of the job is G0007V00, and steps 1 and 2 each create a generation. Then in step 3,
`(0)` is still G0007V00 and `(+3)` is G0010V00. So `(+n)` is the newest generation at the first
reference plus *n*, `(0)` is that newest generation, and `(-n)` counts back through the active
list. GDGBIAS=STEP is not modelled.

**G6. Absolute names are GxxxxV00.** UDS p. 478: "GxxxxVyy, where xxxx is an unsigned 4-digit
decimal generation number (0001 through 9999)". The first generation of a GDG is G0001V00.
jackal creates only version 00 and does not model the wrap after G9999.

**G7. A new generation is cataloged at allocation and rolled in at the end of the step.** UDS
p. 483: "The new generation data set is cataloged at allocation time, and rolled into the GDG at
the end-of-job step." UDS p. 484: "Generation data sets can be in a deferred roll-in state if
the job never reached the end-of-job step or if they are allocated with a DISP=(NEW,KEEP)." In
jackal, a generation whose disposition at the end of the step is CATLG is rolled in. One with
KEEP stays cataloged under its absolute name, out of the GDG. PASS defers the decision to the
step that receives it. DELETE removes it.

**G8. Rolling in past LIMIT rolls off the oldest generation, or every generation under EMPTY.**
UDS p. 484: "the oldest generation data set is rolled off and is no longer active. If a GDG is
defined using DEFINE GENERATIONDATAGROUP EMPTY, and is at its limit, then, when a new generation
data set is rolled in, all the currently active generation data sets are rolled off." "If you
specify the SCRATCH parameter, the generation data set is scratched when it is rolled off. If
you specify the NOSCRATCH parameter, the rolled off generation data set is recataloged as rolled
off and is disassociated with its GDG." jackal follows the SMS-managed reading of NOSCRATCH (AMS
p. 179). The generation leaves the GDG but stays cataloged under its absolute name.

**G9. A relative generation of an undefined GDG fails allocation.** A relative reference names
a generation of a base, so a missing base leaves nothing to resolve against. The DD fails with
`GDG_BASE_NOT_FOUND`. A `(0)` or `(-n)` that names no active generation fails with
`DATASET_NOT_FOUND`, like any missing dataset. IBM's message for the missing base is not quoted
here. The outcome is **jackal's own**, chosen to match how a missing dataset fails.
