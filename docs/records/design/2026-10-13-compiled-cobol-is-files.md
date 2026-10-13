# red-dragon-forge: Compiled COBOL Is Files — Decision Record

**Date:** 2026-10-13
**Status:** accepted (red-dragon-ajps; red-dragon ADR-183)
**Issues:** red-dragon-ajps, red-dragon-forge-k6l

What the forge's runtimes see now that red-dragon compiles a COBOL program in
three stages chained only through files, and the two changes the forge made
first so that a compiled program needs nothing from the process that compiled it.

## Sources

| Key | Document |
|---|---|
| ADR-183 | red-dragon `docs/architectural-design-decisions.md`, "COBOL compiles in three stages chained through files" |
| LD | red-dragon `docs/linker-design.md` §7.1–§7.2 |
| SQ | `docs/superpowers/specs/2026-10-13-squall-self-contained-ir-design.md` |

## Decisions

**C1. A compile is three files per program.** Parse writes `<stem>-<digest>.ast.json`,
lowering writes `.unit.json`, link writes `.linked.json`, and `compile_program` /
`compile_cobol` return the `LinkedProgram` read back from the linked file (ADR-183, LD).
The digest covers the source bytes and the lowering settings — LP mode, each extension
strategy's `name`, tolerant mode and copybook directories. A stage skips a program whose
file exists. Purpose (user, 2026-10-13): compile once, link many, across processes.

**C2. `compile_program` returns the `LinkedProgram` alone.** No frontend survives lowering,
so every forge caller that unpacked `(frontend, linked)` takes the program; the two that read
`frontend.data_layout` read `linked.data_layout`, the main program's layout, which is the same
value.

**C3. Extension strategies are named.** `CicsLoweringStrategy.name = "cics"`,
`SqlLoweringStrategy.name = "sql"`. The name is part of every compiled file's digest, so a
program compiled with and without SQL gets different files.

**C4. A lowered program is self-contained (prerequisite).** squall's `__exec_sql` call sites
carry the statement text, an OPEN's cursor declaration and the VARCHAR shapes of the host
variables they bind; the plan pool, cursor and field-metadata stores, `SharedSqlStores` and
the DCLGEN JSON sidecars are gone (SQ). CICS IR already carried only primitive values. A
program lowered in one process runs in another; squall's cross-process test proves it.

**C5. Tests keep their compiles in the session's temp directory.** Without a work directory a
compile uses `tempfile.mkdtemp()` and leaves the directory in place (the user kept that
default, 2026-10-13). Each suite's `conftest.py` points `tempfile` at a session-scoped pytest
directory, which pytest prunes, so test runs leave nothing in the system temp location.
Before this, every compile left a directory in `/tmp`: 37,195 had accumulated, 4.4 GB, removed
2026-10-13.

## Not yet

The forge's runtimes do not reuse compiled files: cicada's region start and jackal's
`ProgramCompiler` compile without a work directory, so each start or step compiles afresh into
a new temporary directory (red-dragon-forge-k6l). Staleness beyond source and settings —
copybook edits, red-dragon lowering changes — is a caller's to handle by clearing the
directory.
