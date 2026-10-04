# jackal — JCL Execution Roadmap

**What this is:** the territory map for "what does jackal need to run useful mainframe
batch programs end-to-end." It is the durable companion to the Beads epic
**`jackal-1o2`** ("broaden JCL execution coverage"); every gap below links to its issue.

**Last updated:** 2026-10-05.

**Target shape:** [`docs/design/2026-10-05-jcl-to-be-architecture.md`](../../docs/design/2026-10-05-jcl-to-be-architecture.md)
— the to-be execution architecture these items are built into, and the four model fixes
(`red-dragon-forge-5fu`, `lrk`, `8in`, `93f`) that come before the items they block.

**Status legend:** ✅ done · 🔶 tracked (open issue) · ⬜ untracked / future.

---

## Framing: parsing is mostly solved — mostly execution now

The JCL *parser* landed (`jackal-1o2.9`): the vendored MIT **mapa** ANTLR grammar runs behind a
Java bridge and parses all 38 CardDemo jobs. CardDemo is not production JCL, though. A
feature-usage census of an external production batch corpus, plus a probe of the bridge with
one synthetic job per construct, found three parse defects that CardDemo never triggers (see
[Production-corpus 80/20 order](#production-corpus-8020-order)). Apart from those, the work is
**execution semantics over already-parsed structure**, plus the **utility** and
**dataset/runtime** layers that programs assume exist.

For a snapshot of how much of a real workload this already runs, see the companion measurement
[`docs/analysis/2026-07-09-carddemo-job-executability.md`](analysis/2026-07-09-carddemo-job-executability.md)
(what fraction of the CardDemo batch jobs run end-to-end through `JobRunner` today, and what blocks the rest).

The surface decomposes into six layers (0 = parse, 5 = far frontier). Layers 1–4 are the
realistic roadmap; Layer 5 is separate, large, mostly-independent emulation.

---

## Layer 0 — Parse the JCL  ✅ / 🔶
mapa grammar parses JOB/EXEC/DD + all parameters, PROC, COND, GDG, in-stream, INCLUDE, etc.
(`jackal-1o2.9`, done). Three open defects, all found on production-style JCL:

| Defect | Status | Issue | Reach in the census |
|---|---|---|---|
| `DCB=dsn` / `DCB=(dsn,…)` fails the whole job | 🔶 | `red-dragon-forge-2cy.2` | ≥25% of jobs |
| Concatenated DDs after the first are dropped | 🔶 | `red-dragon-forge-2cy.3` | common |
| `IF/THEN/ELSE` flattened, condition lost | 🔶 | `red-dragon-forge-2cy.7` | ~1% |

## Layer 1 — JCL execution semantics (the *control plane*)
How a job sequences and wires its steps.

| Construct | Status | Issue | Unlocks |
|---|---|---|---|
| JOB → EXEC step sequencing | ✅ | — | any multi-step job |
| DD: DSN / DISP / in-stream / SYSOUT | ✅ | — | file wiring |
| `COND=` step bypass (RC-gated) | ✅ | `1o2.1` | "stop the job if a step failed" — most chains |
| `IF/THEN/ELSE/ENDIF` + `COND=EVEN/ONLY` | 🔶 | `1o2.8` (after `2cy.7`) | modern conditional flow; abend-conditional steps |
| PROC + symbolics (`&VAR`) | 🔶 | `1o2.2` | core expansion landed (`expand_procs`, wired in `runner.py`); remaining: `SET`/instream PROC/`--proclib-dir` CLI flag |
| `INCLUDE` / `JCLLIB` | 🔶 | `1o2.15` | shared JCL fragments |
| Referbacks (`DSN=*.STEP.DD`) | ✅ | `1o2.10` | inter-step dataset passing |
| Temp datasets (`&&NAME`) | ✅ | `1o2.11` | scratch files between steps |
| DD concatenation | 🔶 | `1o2.5` | multi-file input; load-lib / proc-lib chains |
| `DCB=` (LRECL/RECFM/BLKSIZE) | 🔶 | `1o2.12` | correct record I/O (13 CardDemo jobs) |
| `PARM=` into the program | ✅ | `1o2.13` | parameterized programs |
| Unknown `PGM=` → explicit "unsupported" + stubs | 🔶 | `red-dragon-forge-xkk` | today any non-utility program is read as COBOL source and fails with a file-not-found error |
| `DUMMY` / `DSN=NULLFILE` | 🔶 | `1o2.14` | empty-input / discard DDs |
| System symbols (`&SYSUID`, `&SYSDATE`, JES) | ⬜→🔶 | `1o2.23` | date-stamped DSNs, generated names |

## Layer 2 — Dataset / access-method model (the *data plane*)
What file shapes programs open. **Holds the single biggest structural gap (PDS).**

| Type | Status | Issue | Note |
|---|---|---|---|
| PS (flat sequential / QSAM) | ✅ | — | |
| VSAM KSDS (keyed) | ✅ | — | |
| Fixed/variable records via DCB | 🔶 | `1o2.12` | RECFM=F/FB/V/VB, LRECL |
| GDG (`DSN=A.B.C(+1)`) | 🔶 | `1o2.4` | 14 CardDemo jobs |
| **PDS/PDSE + member (`DSN=LIB(MEMBER)`)** | 🔶 | `1o2.16` | **foundational** — load/copybook/proc/control libs |
| VSAM ESDS / RRDS | 🔶 | `1o2.21` | entry- / relative-record files |
| VSAM alternate index (AIX + `BLDINDEX`) | 🔶 | `1o2.22` | secondary-key access |
| Tape / SPACE / UNIT / VOL | ⬜ | — | allocation hints — safely no-op'd |

## Layer 3 — Utilities (the embedded *control-language programs*)
Each is its own SYSIN mini-language. This is where "useful program" frequently lives.

| Utility | Status | Issue | Depth |
|---|---|---|---|
| IEFBR14 | ✅ | — | allocation no-op |
| IDCAMS | ✅ core / 🔶 deeper | `red-dragon-forge-vqa` (VERIFY/VFY, comprehensive parser wiring), `1o2.6` (GDG define, AIX) | grammar/typed-AST comprehensive (LISTCAT/PRINT/ALTER/DEFINE AIX·GDG·PATH, EXPORT/IMPORT, VERIFY, BLDINDEX, modal IF/THEN/ELSE); executor coverage incremental |
| SORT (DFSORT) — subset | 🔶 | `1o2.3` | FIELDS, INCLUDE/OMIT, OUTREC FIELDS, SUM, OPTION COPY |
| IEBGENER | 🔶 | `1o2.3` | sequential copy (+ simple reformat) |
| IEBCOPY | 🔶 | `1o2.18` | PDS member copy/compress (needs `1o2.16`) |
| Deeper DFSORT (INREC/OUTREC/JOINKEYS) + ICETOOL | 🔶 | `1o2.24` | large — scope incrementally |

## Layer 4 — Runtime environment (what a program *assumes exists*)
Invisible until a program needs it.

| Facility | Status | Issue | Note |
|---|---|---|---|
| Return-code model (step RC, MAXCC) | ✅ | `1o2.1` | COBOL RC read back from the VM via `read_return_code(vm)`; feeds `COND=` |
| Abend model (Sxxx/Uxxx ≠ RC) | 🔶 | `1o2.19` | drives EVEN/ONLY + dump DDs + job flush |
| Diagnostic DDs (SYSUDUMP/CEEDUMP/SYSABEND) | 🔶 | `1o2.20` | capture; content depends on abend model |
| SYSOUT/SYSPRINT capture | 🔶 | `1o2.7` | reports + utility message decks |
| STEPLIB/JOBLIB load-lib resolution | 🔶 | `1o2.17` | needs PDS (`1o2.16`); replaces source-dir-only lookup |
| LE callable services (CEEDAYS, …) | — | red-dragon | partially stubbed in red-dragon (separate repo) |

## Layer 5 — Subsystem batch (far frontier — separate tracks, not in `jackal-1o2`)
Each is a large independent emulation, not part of the JCL surface proper:
- **DB2 batch** — `EXEC SQL` programs via `IKJEFT01` / `DSN` (`red-dragon-forge-46d`; composed in
  `red_dragon_forge/`, since jackal must not import squall).
- **IMS DLI batch** — `DFSRRC00`.
- **CICS online region** — red-dragon's CICS work.

Map these as future epics of their own when needed.

---

## Program-class view — what each "useful program" class needs

Useful programs cluster; each class needs a different minimal slice. Build classes A→D.

- **Class A — self-contained compute/report COBOL** (flat in → compute → flat/report out):
  **DCB** + **SORT-subset** + **SYSOUT capture** → `1o2.12` + `1o2.3` + `1o2.7`. *Closest to done.*
- **Class B — VSAM master/account batch** (e.g. CardDemo account programs):
  KSDS ✅ + IDCAMS DEFINE/REPRO ✅ + **GDG** + **LISTCAT/PRINT** → mostly works; add `1o2.4` + `1o2.6`.
- **Class C — multi-step pipelines** (extract → sort → report, with flow):
  **COND/IF** + **SORT** + **IEBGENER** + **temp/referbacks** → `1o2.1` `1o2.3` `1o2.10` `1o2.11`.
- **Class D — shop-standard PROC-driven jobs**:
  **PROC+symbolics** + **INCLUDE** + **PDS proc/copybook/load libs** → `1o2.2` `1o2.15` `1o2.16` `1o2.17`.

**Minimal utility floor for "broadly useful batch" (Classes A–C):**
`IEFBR14`✅ · `IDCAMS{DEFINE,DELETE,REPRO,LISTCAT,PRINT}` · `SORT{FIELDS,INCLUDE/OMIT,SUM}` ·
`IEBGENER{copy}` — plus the Layer-1 control plane (COND, GDG, DCB, temp, referbacks).

---

## Dependency ordering (build sequence)

```
COND= (1o2.1) ──► IF/THEN + EVEN/ONLY (1o2.8) ◄── Abend model (1o2.19) ──► Dump DDs (1o2.20)
DCB (1o2.12)         (RC plumbing from 1o2.1 feeds all step-flow + abend work)

PDS/PDSE (1o2.16) ──► Load-lib resolution (1o2.17)
                  └─► IEBCOPY (1o2.18)
                  └─► (library-based PROC/INCLUDE/copybook lookup for 1o2.2 / 1o2.15)

PROC+symbolics (1o2.2) ◄── System symbols (1o2.23)   (shared substitution machinery)
SORT subset (1o2.3) ──► Deeper DFSORT/ICETOOL (1o2.24)
IDCAMS depth (1o2.6) ──► VSAM AIX (1o2.22);  VSAM ESDS/RRDS (1o2.21) parallels KSDS
DD concatenation (1o2.5) supports STEPLIB chains once PDS (1o2.16) lands
```

**Superseded order (CardDemo + general leverage, 2026-07-11).** Replaced by
[Production-corpus 80/20 order](#production-corpus-8020-order); kept for the CardDemo context:
`1o2.1` (COND) → `1o2.4` (GDG) → `1o2.12` (DCB) → `1o2.3` (SORT/IEBGENER) →
`1o2.10`/`1o2.11` (referbacks/temp) → `1o2.6` (IDCAMS depth) → `1o2.16` (PDS) →
`1o2.2`/`1o2.15`/`1o2.17` (PROC + libs). Lower-frequency items (`1o2.19`–`1o2.24`) follow.

---

## Production-corpus 80/20 order

Ordered by reach in the production census. The goal is to analyse a comparable corpus's JCL as
soon as possible: static understanding first (cobble, epic `red-dragon-forge-2cy`), then
execution (jackal, epic `jackal-1o2`). Priorities live in Beads; this is the sequence.

**Static (cobble graph).**

| # | Item | Issue | P | Why |
|---|---|---|---|---|
| 0 | Run `diagnose-jcl` on the target corpus; census-construct bridge fixture | `2cy.1` | 1 | replace the estimate with a measurement |
| 1 | Parse `DCB=dsn` / `DCB=(dsn,…)` | `2cy.2` | 0 | ≥25% of jobs fail to parse at all |
| 2 | GDG relative generations as a typed DSN; graph keys the base | `2cy.4` | 1 | ≥25% of jobs; restores lineage across jobs |
| 3 | `&&temp` datasets as job-scoped graph nodes | `2cy.5` | 1 | the dominant step-to-step idiom; no data flow within a job today |
| 4 | Keep concatenated DDs | `2cy.3` | 1 | data silently dropped |
| 5 | `COND=` as edge attrs | `2cy.6` | 2 | near-universal; shows what gates each step |
| 6 | Keep `IF/THEN/ELSE` structure | `2cy.7` | 3 | ~1% |

Already right for analysis: `IKJEFT01` → DB2 `RUN PROGRAM`, cataloged procs absent from the
corpus (program nodes), `OUTPUT`, `$DJDE$` print payload in `DD *`, `AMP=`, `TYPRUN=`, `JOBLIB`,
quoted `PARM` with unbalanced parentheses, `DD DUMMY`.

**Execution (jackal), after the static track.**

| # | Item | Issue | P | Why |
|---|---|---|---|---|
| 1 | Unsupported-program result + stubs | `red-dragon-forge-xkk` | 2 | otherwise any job containing a SORT/TSO/SAS/FTP step dies on a missing `.cbl` |
| 2 | `DD DUMMY` | `1o2.14` | 2 | ≥47% of jobs |
| 3 | IDCAMS VERIFY/VFY, `IF…THEN DO…END`, comprehensive parser | `red-dragon-forge-vqa` | 2 | IDCAMS ≥64%; `VFY` gates ≥24% of jobs at step one |
| 4 | GDG + `IEFBR14` pre-create / `(MOD,DELETE)` idioms | `1o2.4` | 2 | ≥25% |
| 5 | DCB attributes, then SORT subset | `1o2.12` → `1o2.3` | 2 | SORT ≥40%; INCLUDE/OMIT ≥62% |
| 6 | IEBGENER copy | `1o2.3` | 2 | ≥37% |
| 7 | Concatenated reads | `1o2.5` | 3 | after `2cy.3` |
| 8 | `IKJEFT01` DB2 steps through squall | `red-dragon-forge-46d` | 3 | 26%; crosses runtimes |

**Demoted to P4** (zero or near-zero use in the census): PROC symbolics and `SET` (`1o2.2`,
`forge-6qr`, `forge-zmp`), `INCLUDE`/`JCLLIB` (`1o2.15`), PDS and load-library resolution
(`1o2.16`, `1o2.17`), `RESTART=` (`1o2.25`). Already P4 and staying there: deeper DFSORT and
ICETOOL (`1o2.24`), `TYPRUN=` (`1o2.26`), `OUTPUT` (`1o2.27`).

---

## The three biggest non-obvious gaps

Written from the CardDemo view. For production-style corpora, the census puts PDS and
library-based lookup at P4 (see above); the abend model still stands.

1. **PDS/PDSE + members (`1o2.16`)** — the most structurally significant missing piece;
   underpins load libs, library-based PROC/INCLUDE/copybook lookup, and IEBCOPY. Gates
   Class-D ("real shop") jobs. Treat as a small sub-epic / prerequisite.
2. **Abend model (`1o2.19`)** — failures are RC-shaped today; real programs abend, which is
   distinct from RC and drives EVEN/ONLY, dump DDs, and job-flush behavior.
3. **VSAM beyond KSDS + system symbols (`1o2.21`/`1o2.22`/`1o2.23`)** — narrower, but block
   specific real jobs.

---

## Maintaining this doc

This is a living roadmap. When an issue closes, flip its 🔶 to ✅ and note the merge.
When a new gap is discovered (typically while trying to run a new real job), add it to the
right layer, file it under `jackal-1o2`, and link it here. The source of truth for status is
Beads; this doc is the human-readable map over it.

The Beads graph itself (issues + all dependency edges) is version-controlled at the forge
root's `issues/issues.jsonl`, which covers every package — regenerate it with
`bd export -o issues/issues.jsonl` before committing issue changes. On a fresh clone,
`bd import issues/issues.jsonl` rebuilds the local DB; then `bd list --parent jackal-1o2` /
`bd dep tree` give the live view.
