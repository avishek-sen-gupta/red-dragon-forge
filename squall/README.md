# Squall

**EXEC SQL coprocessor runtime for the [RedDragon](https://github.com/) multi-language COBOL interpreter.**

Squall runs real, unmodified COBOL programs that embed static SQL (`EXEC SQL … END-EXEC`,
Db2-style) against a pluggable database backend (SQLite first) — `SELECT … INTO`, DML,
cursors, `COMMIT`/`ROLLBACK`, `SQLCODE`/`SQLCA`, host variables — without modifying
RedDragon's core VM.

It is a **peer of [Cicada](https://github.com/) (the CICS runtime)**, not a dependent of
it. EXEC SQL is a *coprocessor extension* — not part of the COBOL language and not a CICS
facility — so Squall:

- **runs standalone** (plain COBOL VM + SQL strategy, no CICS), and
- **composes with Cicada** for CICS + Db2 programs.

Unlike CICS, EXEC SQL imposes no higher-level execution semantics — every statement is a
synchronous call — so Squall is purely passive: a lowering strategy, a generic
host-variable binding engine, builtins, and a pluggable `SqlBackend`. No region, no
dispatcher, no suspend/resume.

- Design: [`docs/design/2026-06-13-exec-sql-support-design.md`](docs/design/2026-06-13-exec-sql-support-design.md)
- Philosophy: [`PHILOSOPHY.md`](PHILOSOPHY.md)
- Agent instructions: [`CLAUDE.md`](CLAUDE.md)
- License: MIT — [`LICENSE.md`](LICENSE.md)

> Status: design approved; implementation not yet started.
