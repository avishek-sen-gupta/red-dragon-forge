# jackal — JCL Execution Roadmap

**What this is:** the territory map for "what does jackal need to run useful mainframe
batch programs end-to-end." It is the durable companion to the Beads epic
**`jackal-1o2`** ("broaden JCL execution coverage"); every gap below links to its issue.

**Last updated:** 2026-07-11.

**Status legend:** ✅ done · 🔶 tracked (open issue) · ⬜ untracked / future.

---

## Framing: parsing is solved — it's all execution now

The JCL *parser* is done (`jackal-1o2.9`, merged): the vendored MIT **mapa** ANTLR grammar
runs behind a Java bridge and parses ~all real JCL structurally (38/38 CardDemo jobs clean).
So every item in this roadmap is **execution semantics over already-parsed structure**, plus
the **utility** and **dataset/runtime** layers that programs assume exist. The work is
interpretation, not grammar.

For a snapshot of how much of a real workload this already runs, see the companion measurement
[`docs/analysis/2026-07-09-carddemo-job-executability.md`](analysis/2026-07-09-carddemo-job-executability.md)
(what fraction of the CardDemo batch jobs run end-to-end through `JobRunner` today, and what blocks the rest).

The surface decomposes into six layers (0 = parse, 5 = far frontier). Layers 1–4 are the
realistic roadmap; Layer 5 is separate, large, mostly-independent emulation.

---

## Layer 0 — Parse the JCL  ✅
mapa grammar parses JOB/EXEC/DD + all parameters, PROC, COND/IF, GDG, concatenation,
in-stream, INCLUDE, etc. Nothing further needed. (`jackal-1o2.9`, done.)

## Layer 1 — JCL execution semantics (the *control plane*)
How a job sequences and wires its steps.

| Construct | Status | Issue | Unlocks |
|---|---|---|---|
| JOB → EXEC step sequencing | ✅ | — | any multi-step job |
| DD: DSN / DISP / in-stream / SYSOUT | ✅ | — | file wiring |
| `COND=` step bypass (RC-gated) | ✅ | `1o2.1` | "stop the job if a step failed" — most chains |
| `IF/THEN/ELSE/ENDIF` + `COND=EVEN/ONLY` | 🔶 | `1o2.8` | modern conditional flow; abend-conditional steps |
| PROC + symbolics (`&VAR`) | 🔶 | `1o2.2` | core expansion landed (`expand_procs`, wired in `runner.py`); remaining: `SET`/instream PROC/`--proclib-dir` CLI flag |
| `INCLUDE` / `JCLLIB` | 🔶 | `1o2.15` | shared JCL fragments |
| Referbacks (`DSN=*.STEP.DD`) | ✅ | `1o2.10` | inter-step dataset passing |
| Temp datasets (`&&NAME`) | ✅ | `1o2.11` | scratch files between steps |
| DD concatenation | 🔶 | `1o2.5` | multi-file input; load-lib / proc-lib chains |
| `DCB=` (LRECL/RECFM/BLKSIZE) | 🔶 | `1o2.12` | correct record I/O (13 CardDemo jobs) |
| `PARM=` into the program | ✅ | `1o2.13` | parameterized programs |
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
| IDCAMS | ✅ core / 🔶 deeper | `1o2.6` | grammar/typed-AST comprehensive (LISTCAT/PRINT/ALTER/DEFINE AIX·GDG·PATH, EXPORT/IMPORT, VERIFY, BLDINDEX, modal IF/THEN/ELSE); executor coverage incremental |
| SORT (DFSORT) — subset | 🔶 | `1o2.3` | FIELDS, INCLUDE/OMIT, SUM |
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
- **DB2 batch** — `EXEC SQL` programs via `IKJEFT01` / `DSN`.
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

**Recommended near-term order (by CardDemo + general leverage):**
`1o2.1` (COND) → `1o2.4` (GDG) → `1o2.12` (DCB) → `1o2.3` (SORT/IEBGENER) →
`1o2.10`/`1o2.11` (referbacks/temp) → `1o2.6` (IDCAMS depth) → `1o2.16` (PDS) →
`1o2.2`/`1o2.15`/`1o2.17` (PROC + libs). Lower-frequency items (`1o2.19`–`1o2.24`) follow.

---

## The three biggest non-obvious gaps

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
