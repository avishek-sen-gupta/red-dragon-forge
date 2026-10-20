# Section 8 — Scale evidence (anonymised): verified facts

Refer to the corpus only as **"a production estate"**. No client, system, application,
program, dataset or member names appear here, and none should appear on slides. Machine-readable
figures are in `scale.json`. Sources:
- **[ONLINE]** `docs/analysis/2026-09-01-index-items-search-and-cics-verb-gaps.md`
- **[BATCH]** `docs/analysis/2026-09-02-jcl-utility-and-argument-frequency.md`
- Issue status: `bd show <id>` / `bd list --status=open`, run 2026-09-14.

These are the only two production-corpus analyses in the repo (`docs/analysis/`).
`jackal/docs/analysis/2026-07-09-carddemo-job-executability.md` covers CardDemo, not the
estate, and the spec flags it as stale.

## Online (CICS/COBOL)

- **2,137 online programs** in the estate. [ONLINE, Provenance]
- **Compile/run outcome, stated precisely:** "Every program in the *target flow* reached
  compiles." One of them was then **executed** end to end: a two-turn pseudo-conversational
  program with real BMS maps and real VSAM file control, terminating normally on `RETURN`.
  [ONLINE, Provenance]
  - **Not available:** an estate-wide compile rate over all 2,137 programs, and the number of
    programs in the target flow. Do not put "2,137 programs compile" on a slide.
- That single run produced a wrong answer that broke down into **six silent defects** (nothing
  raised, the run reported success). [ONLINE, table of contents]

### Defect classes and status

| # | Defect class | Severity | Status (2026-09-14) |
|---|---|---|---|
| A | `INDEXED BY` index items never allocated | wrong answer, silent | fixed [ONLINE Status] |
| B | Unknown data-name lowered as a string literal | wrong answer, silent | fixed [ONLINE Status] |
| C1–C3 | `SEARCH` ignored its table: no implicit index, fixed 256 bound, out-of-bounds walk | wrong answer, silent | fixed [ONLINE Status] |
| C4 | `SEARCH ALL` indistinguishable from `SEARCH` (linear scan) | low | open, `forge-39r` (P3) |
| D | `SET x TO <data-item>` wrote the item's name | wrong answer, silent | fixed [ONLINE Status] |
| E | Unimplemented `EXEC CICS` verbs emitted no IR, only a warning | missing behaviour, silent | START/RETRIEVE implemented [ONLINE Step 6]. Loudness policy **closed** as `forge-p9t`: unsupported verbs now record the verb and abend (`cicada/cics/strategy.py:1304`) |
| F | `HANDLE CONDITION` no-op, no condition ever raised | wrong control flow, silent | fixed [ONLINE Step 8]. `forge-43l` (subprogram copybook prepass) fixed 2026-10-20. Follow-ups open: `forge-bxh` (NOTOPEN never produced), `forge-3ie`, `forge-9eg` |

Suggested slide message: *"Running one real program found six silent-wrong-answer defects;
all six are closed except the low-severity SEARCH ALL one."*

### Blast radius figures [ONLINE]
- `INDEXED BY` declared in **122 programs and 53 copybooks** (defect A).
- **At least 620 `SEARCH` statements across at least 489 programs**; 845 `WHEN` lines
  subscripted by an index-shaped name (defect C).
- **45 `OCCURS` clauses above 256**; largest table **357** occurrences.
- **Zero `SEARCH ALL`** in the estate.
- **2,679 `HANDLE CONDITION` occurrences across 1,599 of 2,137 programs (75%)** (defect F).

### CICS verb frequency (occurrences across 2,137 programs) [ONLINE, Defect E]

Implemented when analysed: `READ` 9,534 · `RETURN` 5,607 · `LINK` 4,050 · `FORMATTIME` 2,814 ·
`HANDLE` 2,810 · `ASKTIME` 2,714 · `READNEXT` 2,434 · `STARTBR` 2,414 · `ENDBR` 2,233 ·
`REWRITE` 1,806 · `ASSIGN` 1,387 · `WRITE` 1,372 · `SEND` 1,372 · `RECEIVE` 1,046 ·
`DELETE` 605 · `READPREV` 425 · `XCTL` 5 · `INQUIRE` 4.

Missing when analysed, with status now:

| Verb | Occurrences | Status 2026-09-14 |
|---|---|---|
| `START` | 3,021 | implemented (`cicada/cics/strategy.py:933`) |
| `BIF DEEDIT` | 992 | implemented (`strategy.py` `_lower_bif_deedit`, `forge-00t` closed) |
| `RETRIEVE` | 920 | implemented (`strategy.py:955`) |
| `IGNORE CONDITION` | 820 | implemented (`strategy.py:1213`) |
| `UNLOCK` | 457 | no-op by design, single-task emulation (`strategy.py` `_SYS_VERBS`); `cicada-lkx.3` open |
| `DELETEQ TS` / `READQ TS` / `WRITEQ TS` | 144 / 98 / 88 | open `forge-o94` (P1) |
| `SPOOLOPEN/WRITE/CLOSE` | 116 | open `forge-cfb` |
| `ROUTE` / `DELAY` | 25 / 25 | open `forge-cfb` |
| `SYNCPOINT` | 20 | open `forge-urh`, `forge-s10` (ROLLBACK) |
| `RESETBR` | 8 | open `forge-t12` |
| `GETMAIN` / `ENQ` / `DEQ` | 7 / 3 / 3 | open `forge-cfb` |

"`START` alone outranks every implemented verb except the top three." [ONLINE]

## Batch (JCL)

- **860 JCL members, 12,267 live steps** (comment-only step lines excluded). **67,354 DD
  statements.** [BATCH, Provenance / DD attributes]
- **The estate contains no PROC definitions.** The 4,039 `EXEC SORT` steps name a cataloged
  PROC whose body is absent, so SORT must be a built-in step form. [BATCH]
- Application load-module steps: **2,650 (21.6%)**, spanning **1,373 distinct programs**. [BATCH]

### Top 10 utilities / step forms by step count [BATCH, "Corpus-wide step mix"]

Share is of 12,267 live steps. Rows marked * are PROC groups the doc lists under "non-COBOL
cataloged PROCs" (~1,850, ~15%, out of scope for a COBOL batch engine). Their percentages are
derived here as steps/12,267 because the doc gives only step counts for them.

| # | Utility / step form | Steps | Share |
|---|---|---|---|
| 1 | SORT (cataloged PROC, `EXEC SORT`) | 4,039 | 32.9% |
| 2 | `PGM=IDCAMS` | 1,848 | 15.1% |
| 3 | `PGM=IEBGENER` | 885 | 7.2% |
| 4 | SAS PROC * | 767 | 6.3% |
| 5 | `PGM=IKJEFT01` | 478 | 3.9% |
| 6 | MQ batch PROC * | 448 | 3.7% |
| 7 | FTP PROC * | 304 | 2.5% |
| 8 | mail PROC * | 219 | 1.8% |
| 9 | `PGM=SORT` | 177 | 1.4% |
| 10 | `PGM=IEFBR14` | 123 | 1.0% |

Tail: PKZIP PROC * 114 (0.9%), `ICETOOL` 78 (0.6%), `ICEGENER` 71 (0.6%, derived),
`IRXJCL` 27 (0.2%).
If the slide should show only COBOL-relevant utilities, drop the * rows. The top 7 are then
SORT-PROC, IDCAMS, IEBGENER, IKJEFT01, PGM=SORT, IEFBR14, ICETOOL.

### Argument-shape findings [BATCH]
- SORT, all forms: **4,216 steps**. **67% of SORT steps need only `SORT FIELDS` +
  `INCLUDE`/`OMIT COND`.** Of 4,195 `SORT FIELDS` cards, 3,817 carry `FORMAT=CH` and 3,074 sort
  on a single field. Of 2,351 INCLUDE/OMIT cards, 2,338 compare against a character literal;
  field-to-field comparison occurs once.
- **IEBGENER + ICEGENER: 956 steps, all 956 with `SYSIN DD DUMMY`**, meaning a plain copy with
  no control cards (7.8% of steps).
- IDCAMS SYSIN verbs: `REPRO` 2,147 · `DELETE` 822 · `VERIFY` 759 · `DEFINE` 609 ·
  `IF MAXCC` 576 · `SET MAXCC` 122 · `PRINT` 75.
- IKJEFT01: **446 of 478** steps are `DSN SYSTEM(…)` + `RUN PROGRAM(x) PLAN(y)`, which is
  COBOL + EXEC SQL under TSO.
- Step control flow is `COND=`: `COND=(0,NE)` **9,767** uses; `PARM=` on only 49 steps and
  `IF/ELSE/ENDIF` on 48.
- GDG relative generations `(+1)` 964 · `(0)` 172 · `(-1)` 9; **1,209** DD concatenation
  continuations.
- Target flow: **2 jobs, 10 and 49 live steps.**
- Suggested top-3 work items (synthetic SORT, IEBGENER copy, wire TSO→SQL) unlock
  **5,650 steps**. [BATCH, Suggested order]

### What jackal executes today against that mix (code-verified 2026-09-14)
- `jackal/jackal/utilities.py` `UTILITIES` = **`IEFBR14`, `IDCAMS` only**. SORT, IEBGENER,
  ICETOOL and IKJEFT01 have no executor.
- IDCAMS executor arms: Delete, DefineCluster, Repro, IfMaxcc, SetMaxcc
  (`jackal/jackal/idcams/executor.py:110-122`). **No VERIFY arm**, which the doc's 759 uses
  would need.
- `jackal/jackal/tso.py` is still imported by no jackal module (grep).
- Do **not** turn these counts into an "estate runs X%" claim; nothing measured that.

## Anonymisation notes
- Both source docs already redact identifiers. The only literal strings in them are
  illustrative (e.g. generic error-code shapes); none are reproduced here.
- Product names (SAS, MQ, FTP, PKZIP, IBM utilities) are generic, not client identifiers.
