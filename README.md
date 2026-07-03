# red-dragon-forge

**Composition layer for RedDragon COBOL coprocessor runtimes.**

Assembles multiple coprocessor extensions (CICS, EXEC SQL, and others later) into one compiled,
runnable COBOL program — without any ingredient runtime knowing about the others.

- [Cicada](https://github.com/) — the CICS runtime (dispatcher, VSAM, BMS).
- [Squall](https://github.com/) — the EXEC SQL coprocessor runtime.

Neither depends on nor is modified by this repo. `red-dragon-forge` depends on both, plus
`red-dragon` itself, and owns the actual `[cics_spec, sql_spec, ...]` wiring via a generic
`CoprocessorSpec` seam — see
[`docs/design/2026-07-04-cics-sql-composition-design.md`](docs/design/2026-07-04-cics-sql-composition-design.md)
for the full design.

> Status: design approved; implementation not yet started.
