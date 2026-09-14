# Section 9 — Honest gaps and roadmap: verified facts

Verified 2026-09-14. Issue status comes from `bd show` / `bd list --status=open` at the repo
root (131 open issues on that date). Status for `red-dragon-*` IDs comes from
`vendor/red-dragon/issues/*.jsonl`.

## RedDragon COBOL engine

| Gap | Evidence | Issue |
|---|---|---|
| **SORT / MERGE / RELEASE / RETURN not lowered at all** | `docs/frontend-design/cobol.md` "Known Gaps" | `red-dragon-429q` open |
| **Arithmetic routes through Python float**, not true fixed-point (the doc calls it "the largest remaining gap") | `cobol.md` Known Gaps | `red-dragon-4q25.1` open (P0 in its tracker) |
| **SEARCH ALL is a linear scan** | `interpreter/cobol/lower_search.py`; `SearchStatement` has no ALL flag | `forge-39r`, `red-dragon-c32s` open |
| CANCEL does not reset the subprogram's WORKING-STORAGE | `cobol.md` Known Gaps | `red-dragon-8dpn` open |
| BY REFERENCE copy-back lost if the callee ends with STOP RUN | `cobol.md` Known Gaps | `red-dragon-zerg` open |
| An unhandled statement type is a **warning**, not a failure | `interpreter/cobol/statement_dispatch.py:171` | `forge-r5r` open |
| Unknown expression node silently lowers to constant 0 | `cobble/docs/outstanding-issues.md` §2 | `forge-ozw` open |
| A write to a name with no memory definition is silently dropped | bd | `red-dragon-forge-ubd` (P1) open |
| XML GENERATE parses but has no lowering | bd | `forge-73x` open |
| Alternate-key file driver is read-only; every write verb raises | `interpreter/cobol/file_drivers.py`; gap doc "Also known" | `forge-fh5` open |
| INTO buffers truncate silently instead of LENGERR | bd | `forge-thb` open |
| Cross-program CALL not linked in one CardDemo path (goes symbolic) | bd | `red-dragon-1bp2` open |
| MOVE CORRESPONDING across two sections | bd | `forge-ysa` open |
| EVALUATE … ALSO: the ASG drops every subject after the first | bd | `red-dragon-forge-5qb` (P1) open |
| Bridge/parse/lower coverage kept in step (epic) | bd | `forge-9e0` open |

Stale doc note: `cobol.md` still lists "most intrinsic FUNCTIONs fall back to first
argument" (`red-dragon-clpn`), but that issue is **closed**. The "29 of 51 ProLeap statement
types" figure is also old. Quote neither.

## cicada (CICS)

Unsupported verbs now **abend loudly** and are recorded
(`cicada/cics/strategy.py:1303-1319`, `forge-p9t` closed). Open verb and option gaps:

| Gap | Estate occurrences [ONLINE doc] | Issue |
|---|---|---|
| `BIF DEEDIT` | 992 | `forge-00t` P1 |
| Temporary storage `READQ/WRITEQ/DELETEQ TS` | 98 / 88 / 144 | `forge-o94` P1 |
| `SEND MAP`/`RECEIVE MAP` drop MAPSET, CURSOR, ERASE, FREEKB | — | `forge-qh5` P1 |
| `ASKTIME`/`FORMATTIME` ABSTIME operand ignored, date formats missing | — | `forge-4of` P1 |
| CALLed subprograms using HANDLE CONDITION cannot compile (copybook prepass reaches main source only) | — | `forge-43l` P1 |
| `SYNCPOINT` / `SYNCPOINT ROLLBACK` | 20 | `forge-urh`, `forge-s10` |
| `RESETBR` | 8 | `forge-t12` |
| `SEND` (terminal control, no map) | — | `forge-34j`, `cicada-0du` |
| `HANDLE AID` is a registered no-op | 10 | `forge-xcs` |
| `PUSH HANDLE` / `POP HANDLE` | — | `forge-sk5` |
| SPOOL, ROUTE, DELAY, GETMAIN, ENQ/DEQ tail | 116 / 25 / 25 / 7 / 3+3 | `forge-cfb` |
| `NOTOPEN` raisable but never produced | — | `forge-bxh` |
| `UNLOCK` is a no-op (single-task emulation); true lock across RECEIVE | 457 | `cicada-lkx.3` |
| Conversational LINK stacking | — | `cicada-lkx.5` |
| No CSD: transid→program map must be synthesised | — | `forge-jqx`; `cobble/docs/corpus-onboarding-blockers.md` #7 "ACCEPTED" |

## squall (EXEC SQL): parsed vs executed

The parser classifies 37 statement kinds (`squall/squall/parser/sql_model.py:28` `Kind`).
Runtime dispatch is in `squall/squall/builtins/exec_sql.py:272` `_HANDLERS`:
- **Dedicated handlers:** CONNECT, SET CONNECTION, DISCONNECT, DECLARE CURSOR, OPEN, FETCH,
  CLOSE, COMMIT, ROLLBACK. No-ops: BEGIN/END DECLARE SECTION (`_NO_OP_KINDS`, line 65).
- **Handled at lowering time, not at run time:** WHENEVER (a compile-time directive that
  generates SQLCODE checks, `squall/squall/strategy.py:136-179`); INCLUDE → COPY and DCLGEN
  typed host variables through the prepass.
- **Everything else falls to the generic `_h_query`**, which sends the statement text to the
  backend: SELECT INTO, INSERT, UPDATE, DELETE, and also kinds with no dedicated semantics
  (MERGE, VALUES INTO, SAVEPOINT, RELEASE, LOCK, SET, SIGNAL, GET DIAGNOSTICS, ALLOCATE
  CURSOR, ASSOCIATE, locators, DECLARE TABLE/STATEMENT/VARIABLE).
- **Explicitly deferred** (`squall/docs/design/2026-06-13-exec-sql-support-design.md` §13):
  dynamic SQL (`PREPARE`/`EXECUTE`/`DESCRIBE`) and `CALL`. "The grammar parses them;
  lowering is deferred." Also Db2→SQLite dialect translation beyond what the
  CBSA banking sample needs (the design doc's name for it), and CICS–Db2 SYNCPOINT coordination.
- Design doc also defers VARCHAR + indicator variables (§ status table line 259).
- Open: `squall-ipq` (session end: close cursors + SYNCPOINT), `squall-ud0` (tolerant type
  coercion + SQLWARN/indicators), `cicada-6hv` (implicit SYNCPOINT at pseudo-conversational
  RETURN), `forge-zka` (P1, Db2 container instance dies repeatedly: test-harness stability).

## jackal (JCL): roadmap layer status table

Reproduced from `jackal/docs/jcl-execution-roadmap.md` ("Last updated: 2026-07-11").
Legend: ✅ done · 🔶 tracked (open issue) · ⬜ untracked / future. Issue IDs are
`jackal-1o2.N`.

**Layer 0 — Parse the JCL** ✅ (mapa ANTLR grammar; 38/38 CardDemo jobs parse clean)

**Layer 1 — JCL execution semantics (control plane)**

| Construct | Status | Issue | Unlocks |
|---|---|---|---|
| JOB → EXEC step sequencing | ✅ | — | any multi-step job |
| DD: DSN / DISP / in-stream / SYSOUT | ✅ | — | file wiring |
| `COND=` step bypass (RC-gated) | ✅ | `1o2.1` | "stop the job if a step failed" |
| `IF/THEN/ELSE/ENDIF` + `COND=EVEN/ONLY` | 🔶 | `1o2.8` | modern conditional flow |
| PROC + symbolics (`&VAR`) | 🔶 | `1o2.2` | core expansion landed; remaining `SET`/instream PROC/`--proclib-dir` |
| `INCLUDE` / `JCLLIB` | 🔶 | `1o2.15` | shared JCL fragments |
| Referbacks (`DSN=*.STEP.DD`) | ✅ | `1o2.10` | inter-step dataset passing |
| Temp datasets (`&&NAME`) | ✅ | `1o2.11` | scratch files between steps |
| DD concatenation | 🔶 | `1o2.5` | multi-file input |
| `DCB=` (LRECL/RECFM/BLKSIZE) | 🔶 | `1o2.12` | correct record I/O |
| `PARM=` into the program | ✅ | `1o2.13` | parameterized programs |
| `DUMMY` / `DSN=NULLFILE` | 🔶 | `1o2.14` | empty-input / discard DDs |
| System symbols (`&SYSUID`, `&SYSDATE`, JES) | ⬜→🔶 | `1o2.23` | date-stamped DSNs |

**Layer 2 — Dataset / access-method model (data plane)**

| Type | Status | Issue | Note |
|---|---|---|---|
| PS (flat sequential / QSAM) | ✅ | — | |
| VSAM KSDS (keyed) | ✅ | — | |
| Fixed/variable records via DCB | 🔶 | `1o2.12` | RECFM=F/FB/V/VB, LRECL |
| GDG (`DSN=A.B.C(+1)`) | 🔶 | `1o2.4` | |
| PDS/PDSE + member (`DSN=LIB(MEMBER)`) | 🔶 | `1o2.16` | foundational |
| VSAM ESDS / RRDS | 🔶 | `1o2.21` | |
| VSAM alternate index (AIX + `BLDINDEX`) | 🔶 | `1o2.22` | |
| Tape / SPACE / UNIT / VOL | ⬜ | — | safely no-op'd |

**Layer 3 — Utilities**

| Utility | Status | Issue | Depth |
|---|---|---|---|
| IEFBR14 | ✅ | — | allocation no-op |
| IDCAMS | ✅ core / 🔶 deeper | `1o2.6` | full grammar/typed AST; executor coverage incremental |
| SORT (DFSORT) — subset | 🔶 | `1o2.3` | FIELDS, INCLUDE/OMIT, SUM |
| IEBGENER | 🔶 | `1o2.3` | sequential copy |
| IEBCOPY | 🔶 | `1o2.18` | PDS member copy (needs `1o2.16`) |
| Deeper DFSORT (INREC/OUTREC/JOINKEYS) + ICETOOL | 🔶 | `1o2.24` | large |

**Layer 4 — Runtime environment**

| Facility | Status | Issue | Note |
|---|---|---|---|
| Return-code model (step RC, MAXCC) | ✅ | `1o2.1` | feeds `COND=` |
| Abend model (Sxxx/Uxxx ≠ RC) | 🔶 | `1o2.19` | drives EVEN/ONLY, dump DDs |
| Diagnostic DDs (SYSUDUMP/CEEDUMP/SYSABEND) | 🔶 | `1o2.20` | |
| SYSOUT/SYSPRINT capture | 🔶 | `1o2.7` | |
| STEPLIB/JOBLIB load-lib resolution | 🔶 | `1o2.17` | needs PDS |
| LE callable services (CEEDAYS, …) | — | red-dragon | partially stubbed |

**Layer 5 — Subsystem batch (far frontier):** Db2 batch via IKJEFT01/DSN, IMS DLI batch,
CICS online region.

### Re-check of that table against code and bd (2026-09-14)
- Every 🔶 issue sampled (`1o2.2/.3/.4/.5/.6/.7/.8/.12/.14/.15/.16/.18/.19/.24`) is **still
  open** in bd. None has flipped since the doc date.
- New items not in the table: `1o2.25` RESTART=, `1o2.26` TYPRUN=, `1o2.27` OUTPUT statement
  (all open).
- Code confirms: `UTILITIES` = IEFBR14 + IDCAMS only (`jackal/jackal/utilities.py`). The IDCAMS
  executor has Delete, DefineCluster, Repro, IfMaxcc, SetMaxcc and **no VERIFY / LISTCAT /
  PRINT / DEFINE GDG arm** (`jackal/jackal/idcams/executor.py:110-122`). PROC expansion is
  wired (`jackal/jackal/runner.py:12,43`). `tso.py` is unwired.
- Spec gap list, confirmed: SORT/MERGE (COBOL verbs and the SORT utility), IEBGENER / IEBCOPY /
  ICETOOL, GDG execution, IDCAMS verbs parsed but not executed.
- `jackal/docs/analysis/2026-07-09-carddemo-job-executability.md` (1/33 jobs run with zero
  setup, 17/33 capability-clean, 16/33 gapped) predates later work. The spec says to re-check
  it before use. Not re-checked here, so **do not quote**.

## cobble (static analysis)

From `cobble/docs/outstanding-issues.md` (section headings, status as written) and bd:
- §1 cobble drops `INDEXED BY` names on ingest (OPEN)
- §8 SPECIAL-NAMES never reaches the picture parser (OPEN); §9 PIC P scaling not on the type
  descriptor (OPEN); §7 bridge source charset untested (OPEN)
- §3/§4 forge's older `knowledge_graph` package slated for deletion; two modules have no cobble
  equivalent (BLOCKED / OPEN)
- `red-dragon-forge-9dr` (P1) BMS screen text the symbolic copybooks cannot carry
- `red-dragon-forge-9fa` (P1) field-dataflow fixpoint that hits its dequeue cap reports
  coverage as if it converged; `red-dragon-forge-1f5` (P1) fixpoint height
- `red-dragon-forge-z8r` srccfg reaching_conditions does not finish in 10 min on the largest
  estate members; `red-dragon-forge-3sv` dataflow latency superlinear in write count
- `red-dragon-forge-7ow` no source line positions on dataflow answers
- `forge-0sp` (P1) one unresolved JCL symbol in a DSN loses the whole job's graph;
  `forge-ptc` (P1) `expr_from_dict` rejects three expression kinds, losing a whole program's ASG
- `forge-5zm` KG FILE-CONTROL stage builds ASGs without dialect parsers; `forge-86b` file_path
  not populated uniformly
- No CSD in an estate: ACCEPTED, partly recoverable (`corpus-onboarding-blockers.md` #7)

## Roadmap (short list, grouped from open beads)

1. **Batch breadth (`jackal-1o2` epic):** GDG (`1o2.4`, P1) → SORT + IEBGENER (`1o2.3`) →
   DD concatenation (`1o2.5`) → IDCAMS breadth incl. VERIFY/GDG define (`1o2.6`) → DCB
   (`1o2.12`) → PDS/PDSE (`1o2.16`) → abend model (`1o2.19`) → deeper DFSORT/ICETOOL
   (`1o2.24`). CardDemo batch tier: `cicada-ncx`.
2. **CICS verb surface:** BIF DEEDIT (`forge-00t`), TS queues (`forge-o94`), BMS map options
   (`forge-qh5`), time formatting (`forge-4of`), SYNCPOINT (`forge-urh`/`forge-s10`), RESETBR
   (`forge-t12`), HANDLE AID (`forge-xcs`), PUSH/POP HANDLE (`forge-sk5`), low-volume tail
   (`forge-cfb`); conversational epic `cicada-lkx`; CardDemo online epic `red-dragon-pz9g`.
3. **COBOL engine correctness:** fixed-point decimal arithmetic (`red-dragon-4q25.1`),
   SORT/MERGE verbs (`red-dragon-429q`), fail loud on unhandled statements and expressions
   (`forge-r5r`, `forge-ozw`, `red-dragon-forge-ubd`), bridge-to-lowering coverage epic
   (`forge-9e0`), SEARCH ALL (`forge-39r`).
4. **SQL:** session end + SYNCPOINT (`squall-ipq`, `cicada-6hv`), tolerant coercion +
   indicators (`squall-ud0`), dynamic SQL/CALL (deferred in design §13, no bead found),
   Db2 harness stability (`forge-zka`).
5. **Estate onboarding / cobble:** robust ingest (`forge-0sp`, `forge-ptc`,
   `red-dragon-forge-5qb`), dataflow scale and honesty (`red-dragon-forge-9fa`, `-1f5`,
   `-z8r`, `-3sv`), source positions (`-7ow`), BMS screen text (`-9dr`), no-CSD synthesis
   (`forge-jqx`).
