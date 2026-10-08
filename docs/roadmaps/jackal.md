# jackal roadmap

What jackal needs to run batch jobs end to end. The parent epic is `jackal-1o2`. Beads is the
source of truth for status; `bd list --parent jackal-1o2` gives the live view. The target
execution design is
[../records/design/2026-10-05-jcl-to-be-architecture.md](../records/design/2026-10-05-jcl-to-be-architecture.md).
How jackal works is in [../reference/jackal/architecture.md](../reference/jackal/architecture.md).

| Item | Issue | Status |
|---|---|---|
| JCL parse: JOB, EXEC, DD, PROC, COND, in-stream, INCLUDE via the mapa grammar | `jackal-1o2.9` | supported |
| Parse `DCB=dsn` and `DCB=(dsn,…)` | `red-dragon-forge-2cy.2` | not started |
| Keep concatenated DDs after the first in the parsed job | `red-dragon-forge-2cy.3` | not started |
| Keep `IF/THEN/ELSE/ENDIF` structure in the parsed job | `red-dragon-forge-2cy.7` | not started |
| Step outcome as a sum type: RC, abend, bypassed, flushed, unsupported | `red-dragon-forge-5fu` | not started |
| Runner owns the step lifecycle: allocate DDs, dispatch, dispose | `red-dragon-forge-lrk` | not started |
| Datasets own their record attributes, with a variable-record codec | `red-dragon-forge-8in` | not started |
| Split the catalog into a persistent system catalog and a per-job context | `red-dragon-forge-93f` | not started |
| JOB to EXEC step sequencing | — | supported |
| DD: DSN, DISP, in-stream, SYSOUT | — | supported |
| `COND=` step bypass | `jackal-1o2.1` | supported |
| `IF/THEN/ELSE/ENDIF` and `COND=EVEN/ONLY` | `jackal-1o2.8` | not started |
| PROC expansion and symbolic parameters | `jackal-1o2.2` | partial |
| `SET` in PROC expansion | `forge-6qr` | not started |
| Symbolic substrings (`&SYM(1:5)`) | `forge-zmp` | not started |
| `INCLUDE` and `JCLLIB` | `jackal-1o2.15` | not started |
| Referbacks (`DSN=*.STEP.DD`) | `jackal-1o2.10` | supported |
| Temporary datasets (`&&NAME`) | `jackal-1o2.11` | supported |
| DD concatenation | `jackal-1o2.5` | not started |
| `DCB=` attributes (LRECL, RECFM, BLKSIZE) | `jackal-1o2.12` | not started |
| `PARM=` into the program | `jackal-1o2.13` | supported |
| Unknown `PGM=`: explicit unsupported result and stubs | `red-dragon-forge-xkk` | not started |
| `DD DUMMY` and `DSN=NULLFILE` | `jackal-1o2.14` | not started |
| System symbols (`&SYSUID`, `&SYSDATE`, JES symbols) | `jackal-1o2.23` | not started |
| `RESTART=` | `jackal-1o2.25` | not started |
| `TYPRUN=SCAN` and `HOLD` | `jackal-1o2.26` | not started |
| `OUTPUT` statement | `jackal-1o2.27` | not started |
| Sequential (PS) datasets | — | supported |
| VSAM KSDS | — | supported |
| GDG relative and absolute generations | `jackal-1o2.4` | not started |
| PDS and PDSE members (`DSN=LIB(MEMBER)`) | `jackal-1o2.16` | not started |
| VSAM ESDS and RRDS | `jackal-1o2.21` | not started |
| VSAM alternate indexes (`DEFINE AIX`, `BLDINDEX`, `PATH`) | `jackal-1o2.22` | not started |
| IEFBR14 | — | supported |
| IDCAMS `DELETE`, `DEFINE CLUSTER`, `REPRO`, `IF MAXCC`, `SET MAXCC` | — | supported |
| IDCAMS: execute through the comprehensive parser; `VERIFY`, `IF…THEN DO…END` | `red-dragon-forge-vqa` | partial |
| IDCAMS: bare `DELETE`, standalone `SET`, GDG define, alternate-index toolchain | `jackal-1o2.6` | partial |
| SORT subset and IEBGENER | `jackal-1o2.3` | not started |
| IEBCOPY | `jackal-1o2.18` | not started |
| Deeper DFSORT (`INREC`, `OUTREC`, `JOINKEYS`) and ICETOOL | `jackal-1o2.24` | not started |
| Abend model (Sxxx, Uxxx) distinct from return codes | `jackal-1o2.19` | not started |
| Dump DDs (SYSUDUMP, CEEDUMP, SYSABEND) | `jackal-1o2.20` | not started |
| SYSOUT and SYSPRINT capture | `jackal-1o2.7` | not started |
| STEPLIB and JOBLIB load-library resolution | `jackal-1o2.17` | not started |
| `IKJEFT01` DB2 steps through squall, composed in `red_dragon_forge` | `red-dragon-forge-46d` | not started |

Some items depend on others. `bd dep tree jackal-1o2` shows the edges. The main chains: the
abend model (`jackal-1o2.19`) precedes `COND=EVEN/ONLY` (`jackal-1o2.8`) and dump DDs
(`jackal-1o2.20`). PDS support (`jackal-1o2.16`) precedes load-library resolution
(`jackal-1o2.17`) and IEBCOPY (`jackal-1o2.18`). The SORT subset (`jackal-1o2.3`) precedes
deeper DFSORT (`jackal-1o2.24`).
