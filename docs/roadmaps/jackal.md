# jackal roadmap

What jackal needs to run batch jobs end to end. The parent epic is `jackal-1o2`. Beads is the
source of truth for status; `bd list --parent jackal-1o2` gives the live view. The target
execution design is
[../records/design/2026-10-05-jcl-to-be-architecture.md](../records/design/2026-10-05-jcl-to-be-architecture.md).
How jackal works is in [../reference/jackal/architecture.md](../reference/jackal/architecture.md).

| Item | Issue | Status |
|---|---|---|
| JCL parse: JOB, EXEC, DD, PROC, COND, in-stream, INCLUDE via the mapa grammar | `jackal-1o2.9` | supported |
| Parse `DCB=dsn` and `DCB=(dsn,…)` | `red-dragon-forge-2cy.2` | supported |
| Keep concatenated DDs after the first in the parsed job | `red-dragon-forge-2cy.3` | supported |
| Keep `IF/THEN/ELSE/ENDIF` structure in the parsed job | `red-dragon-forge-2cy.7` | supported |
| JCL object model per the 2026-10-10 blueprint: parsed model and expansion, pinned by an acceptance suite | `red-dragon-forge-2cy.9`, `red-dragon-forge-2cy.10`, `red-dragon-forge-yv3` | done; the census run (`red-dragon-forge-yv3`) needs the corpus, which is not on this machine |
| Step outcome as a sum type: RC, abend, bypassed, flushed, unsupported | `red-dragon-forge-5fu` | supported |
| Runner owns the step lifecycle: allocate DDs, dispatch, dispose | `red-dragon-forge-lrk` | supported |
| Datasets own their record attributes, with a variable-record codec | `red-dragon-forge-8in` | supported |
| Split the catalog into a persistent system catalog and a per-job context | `red-dragon-forge-93f` | supported |
| JOB to EXEC step sequencing | — | supported |
| DD: DSN, DISP, in-stream, SYSOUT | — | supported |
| `COND=` step bypass | `jackal-1o2.1` | supported |
| `IF/THEN/ELSE/ENDIF` and `COND=EVEN/ONLY` | `jackal-1o2.8` | supported |
| PROC expansion and symbolic parameters: cataloged (CLI `--proclib`) and in-stream, nested, null overrides | `jackal-1o2.2` | supported |
| `SET` in PROC expansion | `forge-6qr` | supported |
| Symbolic substrings (`&SYM(1:5)`) | `forge-zmp` | not started |
| `INCLUDE` and `JCLLIB` | `jackal-1o2.15` | not started |
| Referbacks (`DSN=*.STEP.DD`) | `jackal-1o2.10` | supported |
| Temporary datasets (`&&NAME`) | `jackal-1o2.11` | supported |
| DD concatenation: COBOL `OPEN INPUT` and IDCAMS `REPRO` | `jackal-1o2.5`, `red-dragon-forge-2dz` | supported |
| `DCB=` attributes: RECFM, LRECL and the model (`DCB=dsname`, `*.step.dd`, `*.dd`); BLKSIZE is not modelled | `jackal-1o2.12` | supported |
| `LIKE=` and `REFDD=` | `red-dragon-forge-fjr` | supported |
| `PARM=` into the program | `jackal-1o2.13` | supported |
| Unknown `PGM=`: abend `S806`, or stub with RC 0 | `red-dragon-forge-xkk` | supported |
| `DD DUMMY` and `DSN=NULLFILE` | `jackal-1o2.14` | supported |
| System symbols (`&SYSUID`, `&SYSDATE`, JES symbols) | `jackal-1o2.23` | not started |
| `RESTART=` | `jackal-1o2.25` | not started |
| `TYPRUN=SCAN` and `HOLD` | `jackal-1o2.26` | not started |
| `OUTPUT` statement | `jackal-1o2.27` | not started |
| Sequential (PS) datasets | — | supported |
| VSAM KSDS | — | supported |
| GDG relative and absolute generations, roll-in and roll-off | `jackal-1o2.4` | supported |
| GDG base name as every generation (`GDGORDER`, `FIFO`/`LIFO`) | `red-dragon-forge-zbb` | supported |
| PDS and PDSE members (`DSN=LIB(MEMBER)`) | `jackal-1o2.16` | not started |
| VSAM ESDS and RRDS | `jackal-1o2.21` | not started |
| VSAM alternate indexes: a program reads and writes a cluster through a path cataloged by `catnip install` | `jackal-1o2.22` | supported |
| IDCAMS `DEFINE AIX`, `DEFINE PATH`, `BLDINDEX` | `red-dragon-forge-shdi` | not started |
| IEFBR14 | — | supported |
| IDCAMS `DELETE`, `DEFINE CLUSTER`, `DEFINE GDG`, `REPRO` (DUMMY, concatenations) | — | supported |
| IDCAMS `VERIFY` and the modal commands (`IF`/`THEN`/`ELSE`, `DO…END`, `SET`, `CANCEL`) | `red-dragon-forge-vqa` | supported |
| IDCAMS: one grammar (ams.lark) for every command; commands jackal does not run end with 12 | `red-dragon-forge-tsw`, `red-dragon-forge-rqw` | supported |
| IDCAMS: bare `DELETE`, standalone `SET`, GDG define, alternate-index toolchain | `jackal-1o2.6` | partial: bare `DELETE`, GDG define and `SET` supported; alternate indexes (`DELETE … ALTERNATEINDEX`, `DEFINE AIX`, `BLDINDEX`, `PATH`) not started |
| SORT subset and IEBGENER | `jackal-1o2.3` | not started |
| IEBCOPY | `jackal-1o2.18` | not started |
| Deeper DFSORT (`INREC`, `OUTREC`, `JOINKEYS`) and ICETOOL | `jackal-1o2.24` | not started |
| Abend model (Sxxx, Uxxx) distinct from return codes | `jackal-1o2.19` | supported: `S806`, `S322`, `S04C`, and user abends through `CEE3ABD` |
| Invalid packed decimal faults `S0C7` | `red-dragon-forge-13p` | deferred: needs a check in the lowered IR |
| Dump DDs (SYSUDUMP, CEEDUMP, SYSABEND) | `jackal-1o2.20` | not started |
| SYSOUT and SYSPRINT capture | `jackal-1o2.7` | not started |
| STEPLIB and JOBLIB load-library resolution | `jackal-1o2.17` | not started |
| `IKJEFT01` DB2 steps through squall, composed in `red_dragon_forge` | `red-dragon-forge-46d` | supported through the Python API; the CLI composes no SQL |
| `CALL` by data-name reaches programs on the link list (CLI `--link`) | `red-dragon-forge-ua7` | done: a package links the programs its build lists into one image, and a CALL by data-name reaches any of them (`red-dragon-forge-8urg`) |
| A package links a program reached only by `CALL` data-name | `red-dragon-forge-8urg` | not started |
| Link list derived from cobble's dynamic call targets | `red-dragon-forge-btr` | not started |
| A dynamic `CALL` to a program outside the run unit ends the step as z/OS does | `red-dragon-forge-xzw` | not started; the run ends with `UnresolvedProgramError` |

Some items depend on others. `bd dep tree jackal-1o2` shows the edges. The main chains: the
abend model (`jackal-1o2.19`) precedes dump DDs (`jackal-1o2.20`). PDS support (`jackal-1o2.16`) precedes load-library resolution
(`jackal-1o2.17`) and IEBCOPY (`jackal-1o2.18`). The SORT subset (`jackal-1o2.3`) precedes
deeper DFSORT (`jackal-1o2.24`).
