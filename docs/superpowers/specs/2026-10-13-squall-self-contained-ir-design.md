# squall: self-contained EXEC SQL IR — design

Date: 2026-10-13. Status: approved in brainstorm. Precedes red-dragon-ajps
(COBOL separate compilation: parse, lower and link chained only through files).

## The idea

Everything `__exec_sql` needs to run a statement is written into that
statement's own call site. Nothing is looked up in objects the lowering filled.
A program lowered in one process then runs in another, which is what persisted
lowered units require.

## Why

Today the lowering parses each EXEC SQL into `ParsedSql` and appends it to a
plan list; the IR carries only the list index:

```
%i = const 3
%r = call_function __exec_sql %i
```

The builtin closes over that list, over a cursor map that
`preprocess_program_dict` fills from WORKING-STORAGE `DECLARE CURSOR`s, and over
a field-metadata map extended with VARCHAR groups inferred from the program's
DATA DIVISION. A fresh process has empty stores, so a stored unit's indices
point at nothing.

`SharedSqlStores` exists only because the last-built strategy's builtin is the
one registered, so every program's pools have to be reachable from it
(forge-2xy).

## Design

### 1. Statements carry their text

Every executable EXEC SQL lowers to a call whose first argument is the
statement's text:

```
%s = const "SELECT NAME INTO :WS-NAME FROM CUST WHERE ID = :WS-ID"
%r = call_function __exec_sql %s
```

The builtin parses the text with `parse_exec_sql`, memoised per process by
text, so a PERFORM loop parses a statement once.

### 2. OPEN carries its cursor's declaration

`DECLARE CURSOR` is not an executable statement (Db2 SQL reference) and must
precede references to the cursor. The lowering resolves each OPEN to its
declaration, wherever it was written:

- WORKING-STORAGE: `derive_cursors(data)` in `preprocess_program_dict`, held for
  the program being lowered only.
- PROCEDURE DIVISION: a `DECLARE CURSOR` statement seen earlier in the same
  program.

OPEN lowers to `__exec_sql` with the OPEN text then the declaration text. A
DECLARE CURSOR lowers to nothing. FETCH and CLOSE carry only their own text;
they act on run-time cursor state (open result sets by name), which is not
lowering data. An OPEN whose cursor has no declaration in the program lowers to
a call with its own text only, and the builtin reports the unknown-cursor
SQLCODE it reports today.

### 3. Inferred VARCHAR shapes travel with the statement

The inferred part of `field_meta` is the DCLGEN VARCHAR groups
(`derive_field_meta`): per group, its length child and its text child. For each
host variable a statement binds that is such a group, the call carries three
`str` arguments: the group name, its length child, its text child. Category,
offset and length come from `data_layout`, as they do now.

Sidecar `field_meta` stays run-time configuration on the strategy and keeps
precedence over an inferred shape.

### 4. The builtin

`__exec_sql(text, [declaration], *varchar_shapes)` — the argument layout is
fixed per statement kind (OPEN has a declaration; others do not), so the
builtin never guesses. It holds no plan list and no cursor declarations; the
per-run cursor registry keeps only open-cursor state.

### 5. What is deleted

`SharedSqlStores`, the plan list, the cursor and inferred-metadata stores,
`merge_cursors`, `merge_field_meta`, and the shared-store wiring in
`build_sql_spec`. WHENEVER is unchanged: it is lowering-only state already
turned into IR.

## Behaviour changes

- Two programs that use one host-variable name with different VARCHAR shapes
  no longer see each other's metadata.
- A statement's IR shows its SQL text.
- A malformed statement is reported when it runs, not when it is lowered, with
  the same exception `parse_exec_sql` raises today.

## Tests

- Unit: the IR of a SELECT is `const <text>` + `__exec_sql`; an OPEN of a
  WORKING-STORAGE cursor carries the declaration text; a DECLARE CURSOR emits
  no call; a VARCHAR host variable's shape appears as three arguments.
- Unit: the builtin parses a repeated statement once.
- Cross-process: lower a SQL program, write its IR and data layout with pickle
  to a temp file, load it in a fresh process (a subprocess) with a fresh
  strategy, run it against SQLite, and compare host variables with an
  in-process run. Proves no lowering state is needed at run time.
- Existing suites: squall, the root suite's SQL and CICS+SQL composition tests,
  and the Db2-backed CardDemo tests, with assertions unchanged. Tests that read
  `_cursors_store` or `SharedSqlStores` change to assert on IR or behaviour.

## Out of scope

- The unit file format and the parse/lower/link split (red-dragon-ajps, next).
- Callee `data_layout`s on `LinkedProgram` (only the main program's is kept).
- Cache invalidation.
