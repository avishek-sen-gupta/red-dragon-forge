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
| Alternate-index paths: `DUPKEY`, updatable paths (CICS files over catnip's paths) | `red-dragon-forge-dbk.7` | supported; defining them through IDCAMS is `red-dragon-forge-shdi` |
| Unit of work over VSAM: `SYNCPOINT ROLLBACK` and abend backout undo file changes | `forge-s10` | not started |
| TS queues: `READQ`/`WRITEQ`/`DELETEQ TS` | `forge-o94` | not started |
| `RECEIVE MAP` honours `MAPSET` | `forge-qh5` | partial |
| `DFHRESP` names missing from the table; one table instead of two | `red-dragon-forge-dbk.9`, `forge-rkh` | partial |
| Low-volume verbs: spool, `ROUTE`, `SEND PAGE`, `DELAY`, `GETMAIN`, `ENQ`/`DEQ`, terminal `INQUIRE`/`SET`, ISC | `forge-cfb` | not started |
| Bare `SEND` (terminal control) | `forge-34j` | supported |
| `HANDLE ABEND LABEL`/`CANCEL`: an abend the program raises transfers to the exit; `ABEND CANCEL` ignores it | `red-dragon-forge-cswt` | supported |
| `HANDLE CONDITION` / `HANDLE ABEND LABEL` targets resolve as a COBOL procedure reference does: any case, and a paragraph name used in several sections means the copy in the `HANDLE` statement's own section | `red-dragon-forge-b71y` | supported |
| A LINKed program's abend reaches the caller's exit or abends the task; `LINK` to an unknown program raises `PGMIDERR` | `red-dragon-forge-ysu4`, `red-dragon-forge-ch0o` | supported |
| Abends raised beneath the program (4038 `CALL` not found, program checks) reach a `HANDLE ABEND` exit | `red-dragon-forge-k0ny` | not started |
| `HANDLE ABEND RESET`/`PROGRAM`, `ASSIGN ABCODE`, the `RECEIVE MAP` timeout through the exit | `red-dragon-forge-uo3t` | not started |
| `RESETBR` | `forge-t12` | not started |
| `HANDLE AID` dispatch | `forge-xcs` | not started |
| `NOTOPEN` produced from file open/close state | `forge-bxh` | not started |
| `XCTL` to an unknown program raises `PGMIDERR` in the program instead of crashing the driver | `forge-6jj` | supported |
| Interval scheduling: `START INTERVAL`/`AFTER`/`AT` are parsed and recorded, not scheduled; `CANCEL` | — | partial |
| Conversational programs served over TN3270 | — | not started |
| Channels and containers; `WEB`/`DOCUMENT`; `SIGNON`/`SIGNOFF`/`VERIFY PASSWORD`; `WAIT`/`POST`/`CONVERSE`; `DUMP TRANSACTION` | — | not started |
| A spec built without the region's `program_cache` made every `EXEC CICS LINK` silently do nothing: the strategy fell back to an empty cache of its own. `install_cics_runtime` now requires the cache, so a caller that forgets it is refused | `red-dragon-forge-q6d` | **fixed** 2026-10-09 |
| A spec built without the region's transaction map rejected every `EXEC CICS START` as an unknown transaction; the TN3270 region did. Both now require the map too | `red-dragon-forge-7pb` | **fixed** 2026-10-09 |
| A dataset whose record identifier does not start at offset 0, browsed with `STARTBR`: `NotImplementedError` is unhandled, crashes the whole served region (not a clean ABEND) -- same family as `dbk.7`. A KSDS keyed at any offset browses through the indexed driver, and a path through `AlternateIndexDriver`, which supports `STARTBR` | `red-dragon-forge-dbk.7` | **fixed** 2026-10-14 |
| Duplicate sibling-group COBOL names in one `OCCURS` entry crash field resolution (`KeyError`) even when every child name is unique | `red-dragon-forge-5h7` | not started; the repro was not recorded |
| A single non-UTF-8 byte anywhere in source (even in a comment) crashes the whole compile with no line context | `red-dragon-forge-5h7` | not started; the repro was not recorded |

The terminal table (`dbk.6`) and VSAM unit of work (`forge-s10`) each change a model, not a
builtin. The alternate-index model is catnip's: batch programs and CICS files both read and write
through paths. Only IDCAMS `DEFINE AIX`, `DEFINE PATH` and `BLDINDEX` remain
(`red-dragon-forge-shdi`).
