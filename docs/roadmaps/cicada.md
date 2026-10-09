# cicada roadmap

What cicada and cobble need to analyse and run a production CICS estate beyond CardDemo. The
epic is `red-dragon-forge-dbk`; beads holds the detail for each item. Verbs that are supported
are listed in [the cicada architecture page](../reference/cicada/architecture.md#supported-verbs).

| Item | Issue | Status |
|---|---|---|
| Grammar parses every `EXEC CICS` command form found in a production estate scan | — | supported |
| Measure the cobble build and cicada on a production estate; command-form grammar regression test | `red-dragon-forge-dbk.1` | not started |
| cobble graph: TS queues as nodes | `red-dragon-forge-dbk.2` | not started |
| cobble graph: `START TERMID` and `FROM` on `START_TRANSID` edges | `red-dragon-forge-dbk.3` | partial |
| cobble graph: spool output linked to the program that writes it | `red-dragon-forge-dbk.4` | not started |
| `FORMATTIME` honours its `ABSTIME` operand; `YYMMDD` and other date formats | `forge-4of` | partial |
| Partial-key access: `GENERIC` `READ`/`STARTBR`/`DELETE` use `KEYLENGTH`, not the FCT key length | `red-dragon-forge-dbk.5` | partial |
| Conditions outside the raisable set (`ENDFILE`, `ENDDATA`, `QIDERR`, `ITEMERR`) are raised | `forge-3ie` | partial |
| `EIBRESP2` set per command and condition | `red-dragon-forge-dbk.8` | not started |
| More than one terminal per region: `START TERMID` to another terminal | `red-dragon-forge-dbk.6` | partial |
| Alternate-index paths: `DUPKEY`, updatable paths | `red-dragon-forge-dbk.7` | partial |
| Unit of work over VSAM: `SYNCPOINT ROLLBACK` and abend backout undo file changes | `forge-s10` | not started |
| TS queues: `READQ`/`WRITEQ`/`DELETEQ TS` | `forge-o94` | not started |
| `RECEIVE MAP` honours `MAPSET` | `forge-qh5` | partial |
| `DFHRESP` names missing from the table; one table instead of two | `red-dragon-forge-dbk.9`, `forge-rkh` | partial |
| Low-volume verbs: spool, `ROUTE`, `SEND PAGE`, `DELAY`, `GETMAIN`, `ENQ`/`DEQ`, terminal `INQUIRE`/`SET`, ISC | `forge-cfb` | not started |
| Bare `SEND` (terminal control) | `forge-34j` | not started |
| `RESETBR` | `forge-t12` | not started |
| `HANDLE AID` dispatch | `forge-xcs` | not started |
| `NOTOPEN` produced from file open/close state | `forge-bxh` | not started |
| `XCTL` to an unknown program abends instead of crashing the driver | `forge-6jj` | not started |
| Interval scheduling: `START INTERVAL`/`AFTER`/`AT` are parsed and recorded, not scheduled; `CANCEL` | — | partial |
| Conversational programs served over TN3270 | — | not started |
| Channels and containers; `WEB`/`DOCUMENT`; `SIGNON`/`SIGNOFF`/`VERIFY PASSWORD`; `WAIT`/`POST`/`CONVERSE`; `DUMP TRANSACTION` | — | not started |
| `cics/tn3270/region.py`: `build_region()` never threaded `program_cache` into `build_cics_spec`, so every `EXEC CICS LINK` on a TN3270-served region silently no-op'd regardless of config | — | **fixed** 2026-10-09, see [records/analysis/2026-10-09-tn3270-link-cache-runtime-gaps.md](../records/analysis/2026-10-09-tn3270-link-cache-runtime-gaps.md) |
| Non-zero-`key_offset` dataset + `STARTBR`: `NotImplementedError` is unhandled, crashes the whole served region (not a clean ABEND) -- same family as `dbk.7`, see the same doc | `red-dragon-forge-dbk.7` | partial |
| Duplicate sibling-group COBOL names in one `OCCURS` entry crash field resolution (`KeyError`) even when every child name is unique | — | not started, repro in the same doc |
| A single non-UTF-8 byte anywhere in source (even in a comment) crashes the whole compile with no line context | — | not started, repro in the same doc |

The terminal table (`dbk.6`), alternate-index model (`dbk.7`) and VSAM unit of work (`forge-s10`)
each change a model, not a builtin. jackal's batch alternate index (`jackal-1o2.22`) needs the
same model as `dbk.7`.
