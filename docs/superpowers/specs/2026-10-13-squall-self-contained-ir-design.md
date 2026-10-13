# squall: self-contained EXEC SQL IR — design

Date: 2026-10-13. Status: approved in brainstorm. Precedes red-dragon-ajps
(COBOL separate compilation: parse, lower and link chained only through files).

## The idea

Everything `__exec_sql` needs to run a statement is written into that
statement's own call site. Nothing is looked up in objects the lowering or the
source rewrite filled. A program lowered in one process then runs in another,
which is what persisted lowered units require.

Ruling (user, 2026-10-13): as much information as possible travels in the IR,
unless that makes no logical sense.

## Why

Today the lowering parses each EXEC SQL into `ParsedSql` and appends it to a
plan list; the IR carries only the list index:

```
%i = const 3
%r = call_function __exec_sql %i
```

The builtin closes over that list and over two more stores filled at compile
time:

- a cursor map, filled by `preprocess_program_dict` from WORKING-STORAGE
  `DECLARE CURSOR`s;
- a field-metadata map, filled from two places: the DCLGEN JSON sidecars the
  source rewrite reads beside each `EXEC SQL INCLUDE`d copybook, and VARCHAR
  groups inferred from the program's DATA DIVISION.

A fresh process has empty stores, so a stored unit's indices point at nothing.
`SharedSqlStores` exists only because the last-built strategy's builtin is the
one registered, so every program's stores have to be reachable from it
(forge-2xy).

## Design

### 1. No DCLGEN sidecars

squall's DCLGEN (`squall/squall/dclgen.py`) writes a copybook and a
`<RECORD>.json` sidecar from the same table schema. The sidecar repeats what the
copybook already says: each category (binary COMP, COMP-3, `PIC X`) is what
`data_layout` derives from the PIC and USAGE, and binding encodes and decodes by
`data_layout`. Its one other fact, a VARCHAR group's length and text children,
is the 49-level pair in the copybook, which `derive_field_meta` already infers.
Its only remaining use is `validate_field_meta`, a per-call check that the JSON
and the copybook agree.

The sidecar goes: DCLGEN writes the copybook only, the source rewrite returns only the
rewritten source, and `validate_field_meta`, `FieldMetaMismatch` and the
strategy's `field_meta` constructor argument are deleted. `tolerant` keeps its
other job, skipping host variables missing from the layout.

### 2. Statements carry their text

Every executable EXEC SQL lowers to a call whose first argument is the
statement's text:

```
%s = const "SELECT NAME INTO :WS-NAME FROM CUST WHERE ID = :WS-ID"
%r = call_function __exec_sql %s
```

The lowering still parses the statement, to find its host variables (section 4)
and its WHENEVER directives; it keeps nothing. The builtin parses the text with
`parse_exec_sql`, memoised per process by text, so a PERFORM loop parses a
statement once.

### 3. OPEN carries its cursor's declaration

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

### 4. VARCHAR shapes travel with the statement

For each host variable a statement binds that is an inferred VARCHAR group, the
call carries three `str` arguments: the group name, its length child, its text
child. For an OPEN, the bound host variables are the OPEN's own (USING) or else
the declaration's.

### 5. The builtin

`__exec_sql(text, [declaration], *varchar_shapes)`. An OPEN with one argument
names an undeclared cursor; otherwise its second argument is the declaration.
Every other kind's arguments after the text are VARCHAR shapes, three at a time.
The builtin holds no plan list, no cursor declarations and no field metadata;
the per-run cursor registry keeps only open-cursor state.

### 6. What is deleted

`SharedSqlStores`, the plan list, the cursor and field-metadata stores,
`merge_cursors`, `merge_field_meta`, `absorb_field_meta`, the sidecar reader and
writer, `validate_field_meta`, `FieldMetaMismatch`, and the shared-store wiring
in `build_sql_spec`. WHENEVER is unchanged: it is lowering-only state already
turned into IR.

## Behaviour changes

- Two programs that use one host-variable name with different VARCHAR shapes no
  longer see each other's metadata.
- A statement's IR shows its SQL text.
- No check that a DCLGEN JSON agrees with its copybook; there is no JSON.
- A PROCEDURE DIVISION `DECLARE CURSOR` no longer has to execute before its
  OPEN; it only has to precede it in the source.

## Tests

- Unit: the IR of a SELECT is `const <text>` + `__exec_sql`; an OPEN of a
  WORKING-STORAGE cursor carries the declaration text; a DECLARE CURSOR emits no
  call; a VARCHAR host variable's shape appears as three arguments.
- Unit: the builtin parses a repeated statement once.
- Cross-process: lower a SQL program, write its IR and data layout with pickle
  to a temp file, load it in a fresh process (a subprocess) with a fresh
  strategy, run it against SQLite, and compare host variables with an
  in-process run. Proves no compile-time state is needed at run time.
- Existing suites: squall, the root suite's SQL and CICS+SQL composition tests,
  and the Db2-backed CardDemo tests, with assertions unchanged. Tests of the
  deleted stores and sidecars are deleted; tests that read `_cursors_store`
  change to assert on IR or behaviour.

## Out of scope

- The unit file format and the parse/lower/link split (red-dragon-ajps, next).
- Callee `data_layout`s on `LinkedProgram` (only the main program's is kept).
- Cache invalidation.
