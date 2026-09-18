# Squall

**EXEC SQL coprocessor runtime for the
[RedDragon](https://github.com/avishek-sen-gupta/red-dragon) multi-language COBOL interpreter.**

Squall runs real, unmodified COBOL programs that embed static SQL (`EXEC SQL … END-EXEC`,
Db2-style) against a pluggable `SqlBackend` — `SELECT … INTO`, DML, cursors,
`COMMIT`/`ROLLBACK`, `SQLCODE`/`SQLCA`, host variables — without modifying RedDragon's core
VM. Two backends ship: a real IBM **`Db2Backend`** (`ibm-db`, the primary integration-test
target) and a `SqliteBackend` for zero-dependency runs.

It is a **peer of [Cicada](../cicada/README.md) (the CICS runtime)**, not a dependent of
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

> Status: implemented. Parser, lowering strategy, binding engine, DCLGEN/copybook
> support, and the `__exec_sql` builtins are in place, with `SqliteBackend` and
> `Db2Backend` behind a common `SqlBackend`. The RedDragon SQL seam is live (the
> `ExecSqlStatement` node, the extension-lowering strategy registry, and the bridge
> `serializeExecSql`), and the Db2 end-to-end suite runs real COBOL through the VM against a
> live Db2 (Docker harness — see `CLAUDE.md`).
