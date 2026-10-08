# cobble roadmap

Open work on cobble, the static analyser. Beads is the source of truth for status;
`bd show <issue>` gives the live view. How cobble works is in
[../reference/cobble/config.md](../reference/cobble/config.md) and the pages it links.

| Item | Issue | Status |
|---|---|---|
| Parse a corpus to a resumable ASG cache, recording per-member failures | — | supported |
| Pre-flight reports: unresolved copybooks, unparseable COBOL, unparseable JCL | — | supported |
| Stub missing copybooks so a member parses | — | supported |
| Read members with high bytes (latin-1, byte-identity) | — | supported |
| Synthesise a CSD from member names and literal transaction ids | `forge-jqx` | partial |
| Time out a bridge subprocess and report the member as skipped | `red-dragon-forge-ul8` | not started |
| `diagnose-cobol` refuses a missing `copybook_dirs` entry | `red-dragon-forge-gdf` | not started |
| Decode PROC members like every other member | `red-dragon-forge-eph` | not started |
| JCL grammar: more than one null or JES2 control statement per job segment | `red-dragon-forge-8x8` | not started |
| BMS commands resolve `macros_dir` like every other path | `red-dragon-forge-jy9` | not started |
| Field dataflow: `EXEC SQL ... INTO` and `FETCH ... INTO` writes | `red-dragon-forge-9kg` | not started |
| Field dataflow: drop the `XCTL` commarea write-back | `red-dragon-forge-3o4` | not started |
| Crossing walk keeps a callee write-back that covers bytes already landed on | `red-dragon-forge-nsv` | not started |
| Crossing walk reports whether `hops` is minimal beyond `--depth` | `red-dragon-forge-u3v` | not started |
| Crossing walk names an external origin instead of reading as an absence | `red-dragon-forge-bm7` | not started |
| Alias rows say machine-readably whether a reason is a fact or a limit | `red-dragon-forge-b7k` | not started |
| Two members with an empty `PROGRAM-ID` count as a collision | `red-dragon-forge-35o` | not started |
| Lowering refuses an unknown expression node instead of emitting 0 | `forge-ozw` | not started |
| `make jar` rebuilds a bridge when only its Java sources change | `jackal-231` | not started |
