# What a production JCL corpus actually asks a batch engine to do

*2026-09-02*

## Provenance

The same production corpus that produced the CICS runtime gaps in
[`2026-09-01-index-items-search-and-cics-verb-gaps.md`](2026-09-01-index-items-search-and-cics-verb-gaps.md)
also carries its batch half: **860 JCL members, 12,267 live steps** (comment-only
`//*` step lines excluded — counting them inflates every figure below, and a first
pass that did so reported IDCAMS at 802 instead of 1848). Within that corpus, one
target flow is the object of the feasibility work: **two jobs, 10 and 49 live
steps**.

The question is not "what does JCL support" but "what does *this* JCL use" —
the utilities invoked, and the argument shapes those invocations actually take.
A batch engine that covers the shapes below runs the corpus; one that covers the
JCL standard is an unbounded project. Everything here is a frequency measurement
over step lines, DD statements and instream control cards, with continuation
lines folded and columns past 72 discarded.

No client identifiers, dataset names or member names appear here. Nothing below
requires the corpus to act on: each finding names the jackal module that must
change.

## Corpus-wide step mix

| Step form | Steps | Share |
|---|---|---|
| `EXEC SORT` (cataloged PROC) | 4039 | 32.9% |
| application load module | 2650 | 21.6% |
| `PGM=IDCAMS` | 1848 | 15.1% |
| `PGM=IEBGENER` (+ `ICEGENER` 71) | 885 | 7.2% |
| `PGM=IKJEFT01` | 478 | 3.9% |
| `PGM=SORT` | 177 | 1.4% |
| `PGM=IEFBR14` | 123 | 1.0% |
| `PGM=ICETOOL` | 78 | 0.6% |
| `PGM=IRXJCL` | 27 | 0.2% |
| non-COBOL cataloged PROCs | ~1850 | ~15% |

The 2650 application-load-module steps span 1373 distinct programs. The non-COBOL
PROC group (SAS 767, MQ batch 448, FTP 304, mail 219, PKZIP 114) is out of scope
for a COBOL batch engine and is listed only so the remaining share is not
mistaken for the whole.

Two structural facts shape everything else:

**The corpus contains no PROC definitions.** A single member holds anything
PROC-like; the 4039 `EXEC SORT` steps name a cataloged PROC whose body is not in
the corpus and never will be. So SORT cannot be reached by writing a PROC
expander — it has to be a built-in step form in the engine, keyed on the PROC
name. The same holds for every non-COBOL PROC above.

**Those steps supply their own DDs anyway.** Across the `EXEC SORT` steps:
`SORTIN` 4010, `SORTOUT` 3941, `SYSIN` 4035, `SORTWK01` 0. The absent PROC body
contributed nothing the engine needs, so a synthetic SORT step is fully
determined by JCL that is already parsed.

## The target flow

59 live steps across two jobs. Utility half: SORT 17, IDCAMS 7, mail 4,
`IKJEFT01` 4, IEBGENER 3. The other ~24 steps are application load modules —
the COBOL side, tracked separately.

The flow's argument surface is a strict subset of the corpus-wide one, which is
what makes the corpus figures worth acting on rather than merely interesting:
control cards `SORT FIELDS` 17, `INCLUDE COND` 14, `SUM FIELDS` 1, `OMIT COND` 1;
IDCAMS verbs `REPRO` 5, `VFY` 3, `IF MAXCC` 1, `DEL` 1, `DEF` 1. DD attributes
`DISP=SHR` 95, `DSN=&&` 44, `AMP=` 37, `DCB=` 22, `SPACE=` 22, `DISP=MOD` 17,
`OUTPUT=` 12, DD concatenation 2, GDG `(+1)` 1, `STEPLIB` 0. Nothing in the flow
needs a shape the corpus does not also demand ~100× over.

## Argument patterns

### SORT control cards are near-monomorphic

4195 `SORT FIELDS` cards:

- 3817 carry a single trailing `FORMAT=CH`. **`CH` is the only format value that
  appears there at all.** 282 cards instead give the format per key inside
  `FIELDS=`.
- 3074 sort on exactly **one** key; 423 on two, 231 on three, and a 93-card tail
  at six or more.
- 159 are `FIELDS=COPY` — a copy, not a sort.
- `EQUALS` / `NOEQUALS` never appears, so record-order stability among equal keys
  is unconstrained.

2351 `INCLUDE COND` / `OMIT COND` cards:

- Relational operators: `EQ` 5573, `NE` 1017, `GE` 193, `GT` 157, `LT` 92,
  `LE` 22.
- Field formats in comparisons: `CH` 6989, `ZD` 47, `BI` 18.
- Right-hand sides: character literal `C'…'` in 2338 of 2351 cards, `X'…'` in 47,
  bare numeric in 3. **Field-to-field comparison occurs once in the whole
  corpus.**
- Connectors: `OR` 3089, `AND` 1541.

One comparison engine — character field at (position, length) against a character
literal, six relops, `AND`/`OR` chains — plus ascending/descending on one or two
`CH` keys covers essentially every SORT step. The verb-set shapes agree: 1599
steps use `INCLUDE` + `SORT` and 1248 use `SORT` alone, so **67% of SORT steps
need nothing beyond `SORT FIELDS` and `INCLUDE`/`OMIT COND`**. The tail is
`OUTREC` 603 (572 with `FIELDS=`), `SUM` 372, `OUTFIL` 304, `JOINKEYS` 304,
`REFORMAT` 151.

### IEBGENER needs no control-card parser at all

956 IEBGENER + ICEGENER steps. **All 956 have `SYSIN DD DUMMY`.** Not one
control card — no `GENERATE`, no `RECORD FIELD`, no `MEMBER`. Every use is a
plain `SYSUT1` → `SYSUT2` copy. This is the cheapest coverage-per-line item in
the corpus: 7.8% of all steps for a byte copy between two resolved DDs.

### IDCAMS: one missing verb is worth 759 steps

Instream SYSIN verb frequency: `REPRO` 2147, `DEL` 822, `VFY` 759, `DEF` 609,
`IF MAXCC` 576, `SET MAXCC` 122, `PRINT` 75.

`jackal/jackal/idcams/executor.py` dispatches Delete, DefineCluster, Repro,
IfMaxcc and SetMaxcc — the top four and the modal construct. `VERIFY` is the
gap, and in an emulated catalog it is legitimately a no-op returning 0: it exists
to close a VSAM cluster left open by an abend, and nothing in the engine can
leave one open. The parser AST already covers the long tail (`ALTER`, `BLDINDEX`,
`LISTCAT`, `PRINT`, `EXPORT`/`IMPORT`, `DEFINE GDG`/`NONVSAM`/`PATH`/`ALTERNATEINDEX`)
with no executor arm; those are worth doing by measured frequency, not by
completeness.

### IKJEFT01 is already parsed and wired to nothing

478 steps. 446 of them are exactly the same two control cards: `DSN SYSTEM(…)`
followed by `RUN PROGRAM(x) PLAN(y)`. That is a COBOL program with EXEC SQL run
under the TSO monitor — squall's territory reached through a batch step, not a
new runtime.

`jackal/jackal/tso.py` already models this (`TSO_MONITORS`, `TsoRun`,
`is_tso_monitor`) and **is imported by no module in jackal**. It was extracted
without being connected. The work is a branch in `jackal/jackal/runner.py`
alongside the existing `UTILITIES` lookup, routing the named `RUN PROGRAM` to the
same path a COBOL step takes with the SQL coprocessor attached.

### DD attributes: what must be modelled, what may be dropped

67,354 DD statements.

Already covered by `jackal/jackal/model.py` and `dsn.py`: `SYSOUT=` 20947,
`DISP=SHR` 18238, `DSN=&&` temporaries 11083, instream `DD *` 8172, `DD DUMMY`
1101, and the `DISP` dispositions (`(NEW,…` 4619, `(NEW,PASS` 3621,
`(OLD,PASS` 3544, `(,PASS` 1523, `MOD` 1142, `(NEW,CATLG` 968).

Must be added, because each changes *which* dataset a step reads:

- **GDG relative generations** — `(+1)` 964, `(0)` 172, `(-1)` 9. A generation
  group has no representation in the DSN model at all, so `(+1)` currently reads
  as part of a name.
- **DD concatenation** — 1209 continuation DDs with no ddname, each extending the
  preceding one. Ignoring them silently truncates the input a step sees.

May be parsed and discarded: `DCB=` 6329, `SPACE=` 6305, `UNIT=` 5360, `AMP=`
4633. Device geometry, buffer counts and VSAM buffer hints with no semantics in
an emulator — but they must not be *parse errors*.

Two things that look like work and are not: `PARM=` appears on only 49 `EXEC PGM`
steps, and structured `IF`/`ELSE`/`ENDIF` on 48. Step-level control flow in this
corpus is `COND=`, overwhelmingly `COND=(0,NE)` at 9767 uses (against `(4,LT)`
340 and `(8,LT)` 282) — the bypass-unless-previous-step-was-clean idiom, which
`jackal/jackal/cond.py` already handles.

## Suggested order of work

Ranked by steps unlocked per unit of work, with the target flow's own count in
parentheses:

1. **Synthetic SORT built-in** — `SORT FIELDS` plus `INCLUDE`/`OMIT COND`, `CH`
   against character literals only. 4216 steps (17).
2. **IEBGENER / ICEGENER as a plain copy** — no SYSIN parsing. 956 steps (3).
3. **Wire `tso.py` into the runner**, route `RUN PROGRAM` through the SQL
   coprocessor. 478 steps (4).
4. **IDCAMS `VERIFY` as a return-0 no-op.** 759 SYSIN uses (3).
5. **GDG relative generations, then DD concatenation**; accept and drop
   `DCB`/`AMP`/`SPACE`/`UNIT`.
6. Mail-notification stub for the flow's 4 steps. SAS / MQ / FTP / PKZIP PROCs
   stay out of scope.

Items 1–3 are 5650 corpus steps, item 4 covers 759 SYSIN verb uses inside the
1848 IDCAMS steps, and together they are 27 of the flow's 35 utility steps. None
of them requires a PROC expander, a control-card language, or a new runtime.
