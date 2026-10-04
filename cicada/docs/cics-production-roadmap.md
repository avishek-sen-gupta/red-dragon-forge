# cicada — CICS Production-Estate Roadmap

**What this is:** what cobble and cicada need in order to analyse, then run, a production CICS
estate that is not CardDemo. Ordered by how many programs each gap touches. The companion
Beads epic is **`red-dragon-forge-dbk`**; every item below links to its issue, and Beads holds
the status.

**Last updated:** 2026-10-05.

**Evidence:**
- A feature-usage census of an external production CICS estate (a static scan of every
  `EXEC CICS` statement in roughly two thousand programs).
- A probe of cicada's CICS grammar with every command form the census found.
- A read of cicada's lowering, VSAM engine and dispatcher.

Numbers below are from the census; "programs" means programs in that estate.

---

## Where the calls go

| Category | Share of statements |
|---|---|
| VSAM file control (`READ`, browse, `WRITE`, `REWRITE`, `DELETE`, `UNLOCK`) | 43% |
| Program and transaction control (`LINK`, `RETURN`, `START`, `RETRIEVE`, `XCTL`) | 28% |
| `ASKTIME` / `FORMATTIME` | 11% |
| Condition handling (`HANDLE`/`IGNORE CONDITION`, `HANDLE AID`) | 7% |
| BMS / terminal | 5% |
| Everything else | ~6% |

**The house error style is `NOHANDLE` plus an inline `EIBRESP` / `DFHRESP()` check**, in over
90% of programs. So the *values* the runtime writes (`EIBRESP`, `EIBRESP2`, `DUPKEY`) matter
more than the mechanics of condition dispatch.

## Parsing: not a blocker ✅

cicada's CICS grammar parses all 42 command forms the census found, including spool, `ROUTE`,
ISC, `QUERY SECURITY`, and the `DATASET` alias of `FILE`. The open risk is ProLeap's COBOL parse
rate and copybook resolution on a large estate, which only a measurement shows (`dbk.1`).

## Static (cobble)

Already in the graph: `LINK`/`XCTL` (non-literal targets carried for dataflow), `RETURN
TRANSID`, `START TRANSID`, `SEND`/`RECEIVE MAP`, and the file verbs with both `FILE` and
`DATASET`. A real CSD is used when the corpus ships one; otherwise `synth_csd` reconstructs
transactions.

| # | Item | Issue | P | Reach |
|---|---|---|---|---|
| 0 | Measure the cobble build on the target estate; command-form grammar regression test | `dbk.1` | 1 | — |
| 1 | TS queues as graph nodes | `dbk.2` | 2 | ~66 programs |
| 2 | `START TERMID` and `FROM` on `START_TRANSID` edges | `dbk.3` | 3 | 1,017 programs issue `START` |
| 3 | Spool output linked to the online program that writes it | `dbk.4` | 3 | 28 programs |

## Execution (cicada)

| # | Item | Issue | P | Reach | Evidence |
|---|---|---|---|---|---|
| 1 | `FORMATTIME` ignores its `ABSTIME` operand and formats now-in-UTC; `YYMMDD` unimplemented | `forge-4of` | 1 | ~1,641 programs | read |
| 2 | Partial-key access: the FCT key length overrides `KEYLENGTH`, so `GENERIC` `READ`/`STARTBR`/`DELETE` are suspected broken | `dbk.5` | 1 | up to 1,143 | read, unverified |
| 3 | Conditions that never fire (`ENDFILE`, `ENDDATA`, `QIDERR`, `ITEMERR`) | `forge-3ie` | 2 | 60+ `HANDLE`, 400+ `IGNORE` | issue |
| 4 | `EIBRESP2` always 0 | `dbk.8` | 2 | 708 | read |
| 5 | **One terminal per region:** `START TERMID` to another terminal is rejected | `dbk.6` | 2 | 1,017 | read |
| 6 | **No alternate-index paths:** no `DUPKEY`, read-only linear scan | `dbk.7` | 2 | 1,044 compare `DUPKEY` | read |
| 7 | **No unit of work over VSAM:** `SYNCPOINT ROLLBACK` and abend backout can't undo file changes | `forge-s10` | 2 | 16 explicit + every abending task | read |
| 8 | TS queues | `forge-o94` | 2 | ~66 | — |
| 9 | `RECEIVE MAP` ignores `MAPSET` | `forge-qh5` | 2 | 1,026 (bites only on duplicate map names) | issue |
| 10 | Missing `DFHRESP` names resolve to sentinel 9999; audit the code table | `dbk.9`, `forge-rkh` | 3 | ~30 | read |
| 11 | Low-volume verbs: spool, `ROUTE`, `SEND PAGE`, `DELAY`, `GETMAIN`, `ENQ`/`DEQ`, terminal `INQUIRE`/`SET`, ISC | `forge-cfb` | 3 | ~50 | — |
| 12 | Bare `SEND`, `RESETBR`, `HANDLE AID` | `forge-34j`, `forge-t12`, `forge-xcs` | 3 | 22 / 5 / 9 | — |
| 13 | `NOTOPEN` is never produced (needs file open/close state) | `forge-bxh` | 3 | defensive branches only | issue |

Items 5–7 are **structural**: each changes a model, not a builtin.
- **[5]** The region owns one terminal. It needs a terminal table: displays and printers, each
  with its own pending-`START` queue.
- **[6]** VSAM needs base cluster + alternate index + path as one model. jackal's batch AIX
  (`jackal-1o2.22`) needs the same model, so design them together. cicada must not import
  jackal (`.importlinter`).
- **[7]** The VSAM engine writes through. It needs per-task before-images, committed or
  backed out together with squall's unit of work.

An unsupported verb compiles and abends loudly only when execution reaches it. So gaps
11–12 fail per call path, not per program.

**Suggested order:**
1. `forge-4of` and `dbk.5`: the highest reach. `dbk.5` starts by verifying the defect.
2. `forge-3ie`, `dbk.8`, `dbk.9`: the values programs check.
3. The structural three: `dbk.6`, `dbk.7`, `forge-s10`, each brainstormed before code.
4. `forge-o94`, `forge-qh5`.
5. The tail.

## Not used by the census estate — deprioritized

Channels and containers; `WEB`/`DOCUMENT`/`SOAPFAULT`; `SIGNON`/`SIGNOFF`/`VERIFY PASSWORD`;
interval scheduling (`START INTERVAL`/`AT`/`AFTER`, `CANCEL`); `WAIT`/`POST`/`CONVERSE`;
explicit `ABEND`/`DUMP TRANSACTION`; TD queues.

## Maintaining this doc

When an issue closes, update its row. When a new gap appears while onboarding an estate, add it
under `red-dragon-forge-dbk` and here. Regenerate the issue snapshot with
`bd export -o issues/issues.jsonl` before committing issue changes.
