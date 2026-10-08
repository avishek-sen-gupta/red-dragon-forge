# CardDemo Whole-Job Executability Analysis (jackal)

**Date:** 2026-07-09
**Question answered:** What fraction of the 33 real CardDemo batch JCL jobs can jackal
run end-to-end through `JobRunner` today, and what blocks the rest?

**How it was measured:** each `vendor/carddemo/app/jcl/*.jcl` was parsed via the real
jcl-bridge (`parse_jcl`), and every step's `PGM=` classified against what jackal's engine
can actually execute (IDCAMS via `jackal/jackal/idcams/executor.py`, COBOL via
`run_cobol_step`, `IEFBR14` no-op). IDCAMS SYSIN blocks were run through
`parse_idcams`/`run_idcams` with the step's real DDs to distinguish verb-support gaps from
data-availability gaps. This is a **capability** analysis, deliberately separating:

- **Capability gap** — jackal's engine fundamentally cannot execute a step (unsupported
  utility, or an IDCAMS verb the grammar/executor doesn't handle). Needs *new engine work*.
- **Data / setup gap** — the step is fully executable, it just needs its input datasets
  seeded first, or a PROC expanded. A *fixture* problem, not an engine gap. (cicada's
  approach — see below — shows direct seeding is the pragmatic solution.)

## Headline numbers

| Tier | Definition | Count | % |
|---|---|---|---|
| **1. Runs now, zero setup** | every step executes with no seeding | **1/33** | ~3% |
| **2. Capability-clean** | no engine gap; needs only data seeding (+ PROC expand, + SDSF-noop) | **17/33** | **51%** |
| **3. Capability-gapped** | needs new engine work before it can run at all | **16/33** | ~48% |

- **Tier 1** is just `DEFCUST.jcl` (pure `DELETE` + `DEFINE CLUSTER`, reads nothing).
- **Tier 2 = the ceiling reachable without new engine work.** 51% is *capability-clean*, NOT
  *demonstrably green*: 12 of the 17 need data seeding, and only `READACCT.jcl` (`CBACT01C`)
  is actually *proven* to compile-and-run through jackal (the existing
  `ACCTFILE→READACCT` e2e). The other tier-2 COBOL jobs are "clean in principle" but a COBOL
  construct could still trip jackal's compile path — unverified.

## Tier 2 — capability-clean (17 jobs)

Runnable given data seeding + PROC expansion + treating `PGM=SDSF` as a no-op:

- **Pure-IDCAMS load jobs** (`DELETE`/`DEFINE CLUSTER`/`REPRO`, blocked only on flat `.PS`
  input being seeded): `ACCTFILE`, `DISCGRP`, `TCATBALF`, `TRANCATG`, `TRANTYPE`, plus
  `DEFCUST` (tier 1).
- **COBOL batch jobs** (no `EXEC SQL`/`EXEC CICS`, in jackal's wheelhouse; need input VSAM
  seeded): `READACCT` (proven), `READCARD`, `READCUST`, `READXREF`, `POSTTRAN`, `INTCALC`,
  `CBEXPORT`, `CBIMPORT`.
- **Pure-SDSF coordination jobs** (become runnable outright once SDSF is a no-op):
  `CLOSEFIL`, `OPENFIL`.
- **Mixed, SDSF as their only would-be blocker besides data**: `CUSTFILE`.

## Tier 3 — capability-gapped (16 jobs), by blocker

| Blocker | Jobs blocked *only* by this | Count |
|---|---|---|
| **IDCAMS verb gaps** (`jackal-1o2.6` items b + e) | `CARDFILE`, `DALYREJS`, `DEFGDGB`, `REPTFILE`, `TRANBKP`, `TRANFILE`, `TRANIDX`, `XREFFILE` | **8** |
| **SORT** | `COMBTRAN`, `PRTCATBL`, `TRANREPT` | 3 |
| both IDCAMS verb gap *and* a utility | `DEFGDGD` (IEBGENER), `DUSRSECJ` (IEBGENER), `ESDSRRDS` (IEBGENER) | 3 |
| `DFHCSDUP` (CICS CSD utility) | `CBADMCDJ` | 1 |
| `COBSWAIT` | `WAITSTEP` | 1 |

The IDCAMS verb gaps are exactly the two open items on `jackal-1o2.6`:
- **item b — `DEFINE GENERATIONDATAGROUP`**: `DALYREJS`, `DEFGDGB`, `DEFGDGD`, `REPTFILE`, `TRANIDX`.
- **item e — the alternate-index toolchain** (`DELETE...ALTERNATEINDEX` / `DEFINE ALTERNATEINDEX` / `DEFINE PATH` / `BLDINDEX`): `CARDFILE`, `TRANBKP`, `TRANFILE`, `XREFFILE`, `TRANIDX`.
- Plus a smaller executor gap: **`NONINDEXED` clusters without `KEYS`** (`DUSRSECJ`, `ESDSRRDS`) —
  the current `DEFINE CLUSTER` executor assumes a keyed KSDS.

## Reprioritized levers (biggest first)

1. **SDSF no-op** — trivial lift. `PGM=SDSF` steps in CardDemo are batch-mode operator-console
   glue (`ISFIN` DD issuing `/F CICSAWSA,'CEMT SET FIL(...) CLO/OPE'`) to close/reopen files in
   a *live CICS region* so a batch VSAM rebuild doesn't collide. In a batch simulator there is
   no live region to coordinate with, so these steps have no data work to do — teach `JobRunner`
   to treat them as skipped no-ops (like `IEFBR14`). Banks `CLOSEFIL`/`OPENFIL` outright and
   removes SDSF as a partial blocker on `CUSTFILE`/`CARDFILE`/`TRANFILE`. → 51% capability-clean.
2. **IDCAMS items b + e** — now the single biggest engine lever: fully unblocks 8 jobs (11
   touched). (This *reverses* an earlier off-the-cuff claim that utilities were the biggest
   lever — that was before separating SDSF out.)
3. **SORT** — distant second: 3 jobs (`COMBTRAN`, `PRTCATBL`, `TRANREPT`).
4. `DFHCSDUP` / `COBSWAIT` — 1 job each, low priority. `DFHCSDUP` (like SDSF) is a CICS
   utility arguably out of scope for a batch simulator.

## How cicada solves data seeding (precedent for the "needs-data" tier-2 jobs)

cicada does **not** run IDCAMS `DEFINE`/`REPRO` to seed VSAM for its transaction-flow e2e
tests. Its `cics/vsam/seed.py` (`seed_vsam`/`seed_records`) writes fixed-length flat `.dat`
files directly (key-sorted for the `IndexedDriver`), from records **generated in-test** in
Python and encoded via `.encode("cp037")` — not from the corpus `.PS`/`.txt` files. Each
`test_carddemo_*.py` carries an inline FCT + `_write_seed_files`. cicada's dataset path is
entirely separate from jackal's `DatasetCatalog`; they share only the CardDemo submodule.

Implication for jackal: the pragmatic way to make tier-2 jobs actually green is **direct
seeding** into `DatasetCatalog.seed(dsn, path)` (cicada-style), not running the loader jobs —
several loader jobs are themselves tier-3 (SDSF / AIX toolchain). A `CBEXPORT.jcl` whole-job
scenario (the one real CardDemo JCL combining IDCAMS + COBOL) would seed its 5 input KSDS
files directly, then run STEP01 IDCAMS + STEP02 COBOL through `JobRunner`. The one awkward
input is `TRANSACT` (no single flat `.PS`; built from the transaction/GDG pipeline).

## Related issues

- `jackal-1o2.6` — IDCAMS verb coverage. Items a/c/d done (bare DELETE, standalone SET,
  IF LASTCC, DELETE...PURGE — commits f2dbda36, 75a2b639). Items b (GDG define) and e (AIX
  toolchain) are the tier-3 IDCAMS blockers above.
- `jackal-1o2.4` — Generation Data Groups (overlaps item b).
- `jackal-1o2.3` — SORT and IEBGENER utilities (the tier-3 utility blockers).
- `jackal-1o2` (epic) — broaden JCL execution coverage.

## Reproducing this analysis

The classification was a throwaday probe over `parse_jcl` + `parse_idcams`/`run_idcams`; it is
not checked in as a script. If regenerating, note the two things that made an earlier version
misleading: (1) pass each IDCAMS step's real `step.dds` to `run_idcams` (an empty DD list
turns every `REPRO` into a spurious `KeyError` that looks like a verb gap but is really a
data gap); (2) classify `SDSF` as no-op-able, not a capability gap.
