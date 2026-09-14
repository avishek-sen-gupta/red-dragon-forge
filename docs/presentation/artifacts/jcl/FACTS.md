# JCL batch (jackal) — facts for the deck

Captured 2026-09-14 by `docs/presentation/capture/jcl.sh` (helper `jcl_capture.py`), a full run
took 5m05s wall. All runs use the unmodified CardDemo tree `vendor/carddemo/app`.

## Headline: ACCTFILE → READACCT (real CardDemo jobs, one catalog)

- `ACCTFILE.jcl`: STEP05 IDCAMS `DELETE … CLUSTER` + `IF MAXCC LE 08 THEN SET MAXCC = 0`,
  STEP10 `DEFINE CLUSTER` (KEYS(11 0), RECORDSIZE(300 300)), STEP15 `REPRO` PS → KSDS. All RC 0,
  0.32s. [`acctfile-readacct.log.txt`]
- `READACCT.jcl`: PREDEL IEFBR14 (`DISP=(MOD,DELETE,DELETE)`) + STEP05 COBOL `CBACT01C` compiled
  via ProLeap and run on the RedDragon VM, reading the KSDS. All RC 0, 5.53s. [same file]
- Result: KSDS 15000 bytes = 50 × 300-byte records. CBACT01C wrote `ACCTDATA.PSCOMP`, 5350 bytes =
  50 × 107-byte records, decoded (EBCDIC zoned decimal + COMP-3) in `readacct-pscomp-excerpt.txt`.
  Its DISPLAY output is in `readacct-sysout-excerpt.txt`.
- Output fidelity notes, from source: CYC-DEBIT = 2525.00 comes from `MOVE 2525.00` when input is
  zero (`CBACT01C.cbl` 1300-POPUL-ACCT-RECORD). **REISSUE-DATE is blank** because it is set by
  `CALL 'COBDATFT'`, an HLASM routine (`app/asm/COBDATFT.asm`) that is not executed.
- The same chain is the gated e2e test `jackal/tests/integration/test_carddemo_acctfile_e2e.py`.
- `jackal run` CLI on ACCTFILE: 3 steps RC 0 [`cli-acctfile.txt`].

## PROC expansion + COND / RC handling

- **PROC expansion on real JCL:** `expand_procs` turns TRANREPT's `EXEC PROC=REPROC` into
  `STEP05R.PRC001 PGM=IDCAMS`. The `//PRC001.FILEIN/FILEOUT` DD overrides and the `&CNTLLIB`
  symbolic both reach the expanded step. [`tranrept-proc-expansion.txt`;
  `jackal/jackal/jcl/proc_expand.py`; `jackal/tests/integration/test_proc_expansion_carddemo_e2e.py`]
- **Executing TRANREPT still fails** at that expanded step. The expanded SYSIN is a PDS member
  (`AWS.M2.CARDDEMO.CNTL(REPROCT)`), not in-stream data, and the IDCAMS utility only reads in-stream
  SYSIN (`jackal/jackal/utilities.py`). PDS support is open as `jackal-1o2.16`. The next step is SORT,
  which is also unsupported.
- **COND / referback demo:** no CardDemo job that uses `COND=` gets past its earlier steps, so
  `conddemo.jcl` is a job **written for the presentation**, run over real CardDemo datasets and CBACT01C.
  - DELMISS (DELETE of an absent cluster, no MAXCC reset) returns RC 8.
  - SKIPPED `COND=(0,NE)` is BYPASSED.
  - DEFINE and LOAD `COND=(8,LT)` run.
  - READ `COND=((8,LT,DELMISS),(0,NE,LOAD))` runs with `ACCTFILE DD DSN=*.LOAD.ACCTVSAM` (a
    referback) and `&&` temp outputs, RC 0, 5.81s total.
  - The script exits non-zero if any step result differs from the IBM-semantics expectation.
    [`conddemo.log.txt`; `jackal/jackal/cond.py`; `jackal/jackal/runner.py`]

## What executes vs parsed only

- **Executes (control plane):**
  - Step sequencing, and job- plus step-level `COND=` including stepname-qualified conditions
    (`cond.py`, `runner.py`).
  - Referbacks `*.STEP.DD`, bypassing the referencing step if its target step did not run.
  - `&&` temp datasets, cleaned up at job end (`catalog.py`).
  - `PARM=` (`cobol_step.py`, `parm.py`).
  - PROC expansion when `proclib_dirs` is given: symbolics, qualified DD overrides, nesting; no
    `SET` (`proc_expand.py`).
  - DISP NEW/OLD/SHR/MOD with DELETE disposal.
  - Roadmap status ✅ for `1o2.1`, `1o2.10`, `1o2.11`, `1o2.13` (`jackal/docs/jcl-execution-roadmap.md`).
- **Executes (programs and data):**
  - COBOL steps on the RedDragon VM, with RC read back from `RETURN-CODE` (`cobol_step.py`).
  - `IEFBR14`.
  - `IDCAMS` restricted to `DELETE [CLUSTER] [PURGE]`, `DEFINE CLUSTER` (keyed KSDS only), `REPRO
    INFILE/OUTFILE`, `IF MAXCC|LASTCC … THEN SET MAXCC`, `SET MAXCC`
    (`jackal/jackal/idcams/grammar.lark`, `idcams/executor.py`).
  - Datasets: PS and VSAM KSDS only (`catalog.py` `_ORG_MAP`).
- **Parsed only:**
  - The JCL parser handles all 38 members; the survey had no parse failures (`jcl_parse_error` count
    0 in `job-survey.json`).
  - Parsed but not executed: IF/THEN/ELSE (`1o2.8`), INCLUDE/JCLLIB (`1o2.15`), GDG (`1o2.4`), DCB
    (`1o2.12`), DD concatenation (`1o2.5`), DUMMY/NULLFILE (`1o2.14`).
  - A comprehensive IDCAMS grammar (`idcams/parser_comprehensive.py`: LISTCAT, PRINT, ALTER, DEFINE
    AIX/GDG/PATH, EXPORT/IMPORT, VERIFY, BLDINDEX) parses every CardDemo IDCAMS block except the
    `CISZ` abbreviation (`test_idcams_comprehensive_carddemo_e2e.py`). It is **not wired to
    execution**: `utilities.py` uses the narrow `idcams/parser.py`.

## Executability survey, refreshed (`job-survey.json`, `job-survey.txt`)

Method: every member of `app/jcl` (38: 33 `.jcl` plus 5 `.JCL`) runs in its own subprocess through
`JobRunner(proclib_dirs=[app/proc])`, with a 120s timeout (none hit). Each job records its first
blocker. There are two modes:
- **standalone**: fresh catalog; only `app/data/EBCDIC` flat files resolve.
- **after_loaders**: the loader jobs run first, best-effort. Only ACCTFILE, TRANTYPE, TRANCATG,
  DISCGRP and TCATBALF succeed. CARDFILE, CUSTFILE and TRANFILE stop at SDSF; XREFFILE stops at AIX.

| | standalone | after_loaders |
|---|---|---|
| Ran, max RC 0 | 5 (ACCTFILE, DISCGRP, TCATBALF, TRANCATG, TRANTYPE) | 6 (+ READACCT) |
| Ran, max RC 8 | 1 (DEFCUST: DELETE of an absent cluster, no MAXCC reset, correct IDCAMS behaviour) | 1 |
| Failed | 32 | 31 |

First-blocker categories (standalone; after_loaders differs only in READACCT):
- **Missing input VSAM/dataset (data gap)**, 8: CBEXPORT, CBIMPORT, INTCALC, POSTTRAN, READACCT,
  READCARD, READCUST, READXREF. After loaders it is 7, since the CARD/CUST/XREF loaders are blocked.
- **SDSF not emulated**, 5: CARDFILE, CLOSEFIL, CUSTFILE, OPENFIL, TRANFILE.
- **IDCAMS verb/syntax not executable**, 9:
  - `DEFINE GENERATIONDATAGROUP` ×4: DALYREJS, DEFGDGB, DEFGDGD, REPTFILE.
  - AIX (`DEFINE`/`DELETE ALTERNATEINDEX`) ×2: TRANIDX, XREFFILE.
  - `CISZ` abbreviation ×1: CREASTMT.
  - `REPRO IFILE/OFILE` abbreviations ×2: INTRDRJ1, INTRDRJ2.
- **IDCAMS SYSIN from a PDS member (via REPROC)**, 3: PRTCATBL, TRANBKP, TRANREPT.
- **Other programs not emulated:**
  - IEBGENER ×2: DUSRSECJ, ESDSRRDS.
  - SORT ×1: COMBTRAN.
  - DFHCSDUP ×1: CBADMCDJ.
  - FTP ×1: FTPJCL.
  - IKJEFT1B ×1: TXT2PDF1.
- **Runtime error**, 1: WAITSTEP. An in-stream `SYSIN DD *` passed to a COBOL step raises
  `TypeError: Unhandled DSN type: InStreamDSN()` (`catalog.py` `allocate`, via `cobol_step.py`).
- Caveat: only the first blocker is recorded. Several jobs have more blockers later (for example,
  TRANREPT and CREASTMT also contain SORT).

**Versus 2026-07-09** (`jackal/docs/analysis/2026-07-09-carddemo-job-executability.md`, 33 `.jcl` jobs):
- **Zero-setup runs.** July's tier 1 was "1/33 (DEFCUST)". Today, among the same 33: 5 run to RC 0
  and DEFCUST completes with RC 8. The five IDCAMS loader jobs run without seeding because the
  catalog resolves `DISP=SHR` DSNs straight from `data/EBCDIC` (`catalog.py` `_allocate_direct`).
- **Proven COBOL jobs.** Still only READACCT (CBACT01C). July's "capability-clean" COBOL jobs
  (READCARD/READCUST/READXREF/POSTTRAN/INTCALC/CBEXPORT/CBIMPORT) remain unproven: all stop at
  missing VSAM inputs, whose loaders are themselves blocked.
- **Levers from July, still open:** SDSF no-op (5 jobs), GDG define (`1o2.4`/`1o2.6` b), AIX
  (`1o2.22`), SORT/IEBGENER (`1o2.3`). All are open in `jackal/beads/issues.jsonl`.
- **New since July:** PROC expansion landed. It moves PRTCATBL/TRANBKP/TRANREPT past "unknown PGM
  REPROC" to a new blocker, PDS-member SYSIN (`1o2.16`). The IDCAMS keyword abbreviations
  (`CISZ`, `IFILE/OFILE`) were not in July's list.

## Honest gaps and breakages found (not fixed)

- **Utilities not emulated:** SORT/DFSORT, IEBGENER (`1o2.3`), ICETOOL/deeper DFSORT (`1o2.24`),
  IEBCOPY (`1o2.18`), SDSF, DFHCSDUP, FTP, IKJEFT01/1B (TSO/Db2 batch, roadmap Layer 5). An
  unknown PGM falls through to reading `<PGM>.cbl` and raises `FileNotFoundError`
  (`runner.py` `_run_step`).
- **Data plane:** no GDG (`1o2.4`), PDS/members (`1o2.16`), ESDS/RRDS (`1o2.21`) or AIX (`1o2.22`).
  DCB is ignored (`1o2.12`): REPRO borrows the output KSDS record size for PS input (jackal-ifq
  workaround, `idcams/executor.py`).
- **Runtime:** no SYSOUT capture (`1o2.7`); DISPLAY goes to the Python process stdout. No abend
  model (`1o2.19`). HLASM subroutines (COBDATFT) are not executed.
- **`python -m jackal run` fails:** "No module named jackal.__main__". There is no
  `jackal/jackal/__main__.py`; the spec's capture command must use the `jackal` console script
  (`jackal/pyproject.toml`).
- **CLI defaults:** `--source-dir` etc. default to `$CARDDEMO_HOME/app/cbl`
  (`jackal/jackal/cli.py`), but the tests treat `CARDDEMO_HOME` as the `app` directory
  (`test_carddemo_acctfile_e2e.py`). The defaults therefore only work when `CARDDEMO_HOME` is the
  repository root.
- **CLI limits:** there is no `--proclib-dir` flag, so PROC jobs cannot be expanded from the CLI.
  Each run uses a throwaway temp dir, so jobs cannot be chained and outputs are not kept (`cli.py`).
