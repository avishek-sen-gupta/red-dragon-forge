# Squall architecture

Squall is the EXEC SQL coprocessor runtime for the RedDragon COBOL interpreter. It runs
unmodified COBOL programs that embed static SQL (`EXEC SQL … END-EXEC`, Db2 style):
`SELECT … INTO`, `INSERT`/`UPDATE`/`DELETE`, cursors, `COMMIT`/`ROLLBACK`, `CONNECT`,
`WHENEVER`, host variables and `SQLCODE`/`SQLCA`.

SQL runs against a `SqlBackend`. Two backends ship:

| Backend | Module | Driver | Use |
|---|---|---|---|
| `Db2Backend` | `squall/backends/db2.py` | `ibm-db` (the `db2` extra) | Primary backend and integration-test target. Reports the real Db2 `SQLCODE`. |
| `SqliteBackend` | `squall/backends/sqlite.py` | stdlib `sqlite3` | No external dependency. Reports `-1` for any SQLite error. |

## Running modes

- Standalone: a plain COBOL VM with the SQL lowering strategy injected and no CICS. This is
  the shape of a batch program.
- Composed: `red_dragon_forge` passes squall's `CoprocessorSpec` and cicada's to
  `interpreter.project.coprocessor_compile.compile_program`, which builds one program for
  CICS + Db2.

## Passive design

EXEC SQL adds no execution semantics: every statement is a synchronous call. Squall has no
driver, region, dispatcher or suspend/resume. The lowering strategy turns each EXEC SQL
statement into a `CallFunction("__exec_sql", …)` IR call that carries everything the builtin
needs: the statement's text, an OPEN's cursor declaration, and the VARCHAR shapes of the host
variables it binds. A `DECLARE CURSOR` lowers to nothing; its text travels on the OPEN. The
builtin parses the text once per process, binds host variables, runs the statement on the
current connection and returns. A lowered program needs nothing from the lowering to run.

A run starts disconnected. `CONNECT TO` and `SET CONNECTION` pick a backend from the
connection registry; `CONNECT RESET` and `DISCONNECT` clear it. A data statement with no
current connection sets `SQLCODE` to `-1024`. `build_sql_spec(initial_connector=NamedDbConnector(name))`
starts the run already connected, which models the CICS Db2 attachment facility.

## Invariants

1. RedDragon's VM is not edited. SQL reaches the VM only through `CallFunction` to
   registered builtins.
2. Squall does not import cicada, and cicada does not import squall. They meet only through
   builtin names (see Hooks). The root `.importlinter` contract
   `cicada-squall-jackal-independence` enforces this.
3. The binding engine is dialect- and backend-agnostic. It handles the embedded envelope
   only: host variables (`:VAR`), the `INTO` target list, `SQLCODE`/`SQLCA`. The query
   is opaque text; dialect and placeholder style live in the backend.
4. `squall.parser` and `squall.backends` do not import each other, and `squall.backend` and
   `squall.parser.sql_model` import no other squall module. Both are `.importlinter`
   contracts.

## The RedDragon seam

| Piece | Where | Owner |
|---|---|---|
| `serializeExecSql` | `vendor/red-dragon/proleap-bridge/.../StatementSerializer.java` | RedDragon. Emits each EXEC SQL statement as JSON (`type: EXEC_SQL`, verbatim text). |
| `DialectParser` | `vendor/red-dragon/cobol_asg/frontend_extension.py` | RedDragon protocol. Squall implements it as `SqlDialectParser`. |
| `ExecSqlStatement` | `squall/statements.py` | Squall. Built by `SqlDialectParser` from bridge JSON or from a cached ASG. |
| `RedDragonExtensionLoweringStrategy` | `vendor/red-dragon/interpreter/frontend_extension_lowering.py` | RedDragon protocol. Squall implements it as `SqlLoweringStrategy`. |
| `extension_strategies` | `CobolFrontend` in `vendor/red-dragon/interpreter/frontend.py` | RedDragon. A sequence of strategies; each claims statements with `handles`. |
| `CoprocessorSpec`, `compile_program` | `vendor/red-dragon/interpreter/project/coprocessor_compile.py` | RedDragon. Squall's spec comes from `squall.coprocessor.build_sql_spec`. |

Changes to these RedDragon pieces go upstream; `vendor/red-dragon` is not edited here.

## Hooks

`SqlLoweringStrategy` registers four builtins in `Builtins.TABLE`:

| Builtin | Called by | Effect |
|---|---|---|
| `__exec_sql` | every lowered EXEC SQL statement | Dispatch on statement kind, bind, execute, write `SQLCODE`. |
| `__cics_task_end_hook` | cicada at task end (`EXEC CICS RETURN`) | Commit and close every cursor. |
| `__cics_syncpoint_hook` | cicada at `EXEC CICS SYNCPOINT` | Commit; cursors stay open. |
| `__cics_rollback_hook` | cicada at `EXEC CICS SYNCPOINT ROLLBACK` and on abend | Roll back and close every cursor. |

Cicada registers no-op defaults under the three `__cics_*` names, so it runs without squall.

## Package layout

Paths are relative to `squall/squall/`.

| Path | Purpose |
|---|---|
| `coprocessor.py` | `build_sql_spec`: wraps the strategy, source prepass, dialect parser and Db2 stubs as a `CoprocessorSpec`. |
| `strategy.py` | `SqlLoweringStrategy`: lowers `ExecSqlStatement` to self-contained `__exec_sql` calls and registers the builtins. |
| `program_scope.py` | `ProgramScope`: the program being lowered, its cursor declarations and VARCHAR groups. |
| `strategy_stores.py` | Builtin registration into `Builtins.TABLE`. |
| `statements.py` | `ExecSqlStatement` and `SqlDialectParser`. |
| `exec_sql_payload.py` | `ExecSqlPayload`: the Pydantic model for one statement's JSON, from the bridge or the ASG cache. |
| `parser/` | Lark grammar (`grammar.lark`), `parse.py` (statement parse, host-variable extraction, query rewrite), `sql_model.py` (parsed-model value types). |
| `preprocess.py` | Source rewrite before ProLeap: `EXEC SQL INCLUDE x` becomes `COPY x`. |
| `exec_sql_scan.py` | Finds `EXEC SQL … END-EXEC` spans in fixed-format code areas. |
| `fixed_format.py` | Positional model of a fixed-format line. Rewrites touch columns 8–72 only. |
| `data_division_exec_sql.py` | Recovers WORKING-STORAGE `DECLARE CURSOR` texts from the bridge JSON. |
| `binding.py` | Host-variable binding engine and byte codecs (zoned, alphanumeric, COMP-3, binary, VARCHAR). |
| `binding_stores.py` | The binding engine's writes into the VM region. |
| `builtins/exec_sql.py` | The `__exec_sql` builtin and the session, syncpoint and rollback handlers. |
| `connector.py` | `DbConnector`: `NullDbConnector` (start disconnected) and `NamedDbConnector` (start connected). |
| `backend.py` | `SqlBackend` protocol and `SqlResult`. |
| `backends/db2.py`, `backends/sqlite.py` | The two backends. |
| `backends/_stores.py` | A backend's writes to its own cursor map. |
| `dclgen.py` | Generates a host-variable copybook from a table schema. |
| `dclgen_field.py` | `DclgenField`: one host-variable field of a generated record. |
| `dclgen_meta.py` | Derives VARCHAR field metadata from the bridge JSON's data fields. |
| `dclgen_copybooks.py` | Strips `EXEC SQL DECLARE … TABLE` from DCLGEN copybooks into a staging directory. |
| `db2_stubs.py`, `stubs/` | COBOL stand-ins for Db2-supplied programs (`DSNTIAC.cbl`), linked into every run unit. |
| `copybooks/` | Bundled copybooks: `SQLCA.cpy`, `ACCTREC.cpy`. |

Other directories under `squall/`: `tests/unit`, `tests/integration`, `db2/` (Db2 container
init and `dsn-env.sh`), `docker-compose.yml`, `testbed/`.

## Tests

How to run squall's suite: [run-tests.md](../../how-to/run-tests.md). How to start Db2 and
source the DSN: [db2.md](../../how-to/db2.md).

| Tests | Needs |
|---|---|
| `tests/unit/` except `test_backend.py` | Nothing external. The binding engine is tested against a fake backend. |
| `tests/unit/test_backend.py` | Live Db2 for its Db2 cases. |
| `tests/integration/` | `PROLEAP_BRIDGE_JAR`. |
| `tests/integration/test_db2_*` | `PROLEAP_BRIDGE_JAR` and live Db2. |

Tests that need Db2 read `SQUALL_DB2_DSN` directly. Without it, or without a reachable Db2,
they fail. They do not skip.
