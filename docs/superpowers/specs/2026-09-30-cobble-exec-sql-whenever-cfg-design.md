# EXEC SQL WHENEVER in cobble's source CFG

2026-09-30

## The defect

`cobble/dataflow/srccfg/desugar.py`'s `_HANDLERS` has ten entries and
`ExecSqlStatement` is not one of them, so every `EXEC SQL` block falls to
`_plain`: one node, one fall-through edge. Reproduced on a 20-line program with
two directives, one `SELECT` and two handler paragraphs:

```
MAIN-PARA/0   kind=NOP  transfer=EXECSQL     WHENEVER NOT FOUND GO TO NOT-FOUND-PARA
MAIN-PARA/1   kind=NOP  transfer=EXECSQL     WHENEVER SQLERROR  GO TO ERROR-PARA
MAIN-PARA/2   kind=NOP  transfer=EXECSQL     SELECT ... INTO :WS-NAME
edges: /0 -> /1 -> /2 -> /3      (nothing reaches NOT-FOUND-PARA or ERROR-PARA)
```

Four consequences:

1. **No handler edges.** The `SELECT` can transfer control three ways; the CFG
   gives it one successor.
2. **A directive is modelled as an executable node.** `WHENEVER` emits no
   runtime code — squall's `strategy.lower` returns before emitting any IR for
   it — yet it occupies a node with a fall-through edge.
3. **Every `EXEC SQL` is indistinguishable.** Same `NOP` kind, same `EXECSQL`
   transfer. No consumer can tell a directive from a branch point.
4. **Handler paragraphs look dead.** Above they are reachable only by paragraph
   fall-through; in a program whose main paragraph ends in `GOBACK` they are
   unreachable, and reachability, dominator and dead-code queries say so.

## Root cause

The SQL and CICS ASG vocabularies are not symmetric:

```python
ExecCicsStatement(verb: str, options: dict[str, CicsOperand | None])   # structured
ExecSqlStatement(text: str)                                            # a string
```

`_exec_cics` can dispatch on `statement.verb`. There is no `_exec_sql` because
SQL hands the ASG an undifferentiated blob, which squall then re-parses at every
lowering. `guardrails.md` names this directly: text is a boundary, never a
carrier.

## Semantics (verified, not assumed)

Db2 for i, *Handling exception conditions with the WHENEVER statement*:

| Condition | Test |
|---|---|
| `NOT FOUND` | `SQLCODE = +100`, or `SQLSTATE = '02000'` |
| `SQLERROR` | `SQLCODE < 0` |
| `SQLWARNING` | `SQLWARN0 = 'W'`, or `SQLCODE > 0 and <> 100`, or `SUBSTR(SQLSTATE,1,2) = '01'` |

Scope, quoted: a WHENEVER applies to *"all subsequent **source** SQL statements
until another WHENEVER is encountered"*, **regardless of program execution
flow**, and must textually precede the first statement it affects.

Actions Db2 defines: `CONTINUE` and `GO TO`/`GOTO label`. The `DO` forms are
ILE/Pro\*COBOL only and out of scope, consistent with squall's slice-1 plan.

## Why not the CICS handler model

Cobble already models armed handlers for CICS: `HANDLE CONDITION` writes a
synthetic `__handler[cond]` field ("arming a handler is a definition, not a
jump"), `_raisable` adds a `#raise` TEST dispatching to handlers, and "which
handler is live here" is a reaching-definitions query.

That model is correct for CICS, which arms at **runtime** — re-arming inside a
loop matters. It is **unsound** for WHENEVER, which the precompiler applies
textually:

```cobol
MAIN.  IF X GO TO SKIP.
       EXEC SQL WHENEVER NOT FOUND GO TO H END-EXEC.
SKIP.  EXEC SQL SELECT ... END-EXEC.      <- governed, even on the path that skipped it
```

Reaching definitions says the handler is not armed on that path. Db2 says it is.
The correct scope computation is a source-order scan; flow sensitivity would
lose edges.

## Design

### 1. Structure the vocabulary (`squall/statements.py`)

`squall.statements` is the SQL vocabulary red-dragon's `parse_statement` falls
back to through the `_dialect_parsers` ContextVar. It currently imports only
`dataclasses`, and that leaf property is what `.importlinter` relies on to let
cobble import it while forbidding `squall.parser` and `squall.strategy`.

Move into that leaf: `WheneverCondition`, `GoTo`, `Continue`, `NoOpAction`, and
the three directive grammar lines from `squall/parser/grammar.lark`.
`ExecSqlStatement` gains a typed `directive` field, built by `SqlDialectParser`
at ASG construction. `squall.parser` imports the vocabulary from the leaf for
its full-statement parse, so there remains exactly one definition and one
grammar. `squall.strategy` reads `stmt.directive` instead of re-parsing.

The leaf must not import `squall.parser`: `forbidden` contracts match chains, so
cobble importing `squall.statements` would otherwise pull `squall.parser` in
transitively and break `cobble-no-runtime`.

### 2. Source-order scope pre-pass (`srccfg/build.py`)

A pass over `paragraph_order` in source order, threading
`dict[WheneverCondition, WheneverAction]` and recording, per `EXEC SQL`
statement, the active `GO TO` targets at that point. `CONTINUE` clears a
condition. The result reaches lowering on `Ctx`, exactly as
`build._error_handlers` already feeds `Ctx.error_handlers`.

Per-statement rather than per-paragraph, because the directive can change
mid-paragraph.

### 3. `_exec_sql` handler (`srccfg/desugar.py`)

Registered in `_HANDLERS`. A `WHENEVER` statement lowers to no node at all — it
is a directive, defect 2. Any other `EXEC SQL` lowers to its node followed by
one TEST chain per active condition, false arm falling through to the next:

```
MAIN-PARA/2      kind=NOP   transfer=EXECSQL
MAIN-PARA/2#nf   kind=TEST  SQLCODE = 100
MAIN-PARA/2#err  kind=TEST  SQLCODE < 0
/2 -> /2#nf ; /2#nf -> NOT-FOUND-PARA#label (true) ; /2#nf -> /2#err (false)
/2#err -> ERROR-PARA#label (true) ; /2#err -> /3 (false)
```

This mirrors `squall.strategy._emit_whenever_checks`, which emits
`IF SQLCODE <op> <val> GO TO target` for the same statements. The TEST nodes
read `SQLCODE`, so field provenance sees the dependency.

`SQLWARNING` is modelled with its real predicate — `SQLWARN0 = 'W'` OR
(`SQLCODE > 0` AND `SQLCODE <> 100`) — as an OR `CondFragment`, since `Atom` is
single-predicate by design. `SQLWARN0` is an elementary field in this
workspace's `squall/copybooks/SQLCA.cpy`, so the name resolves.

Cobble models `SQLWARNING` although squall does not branch on it (squall-ud0
needs SQLCA `SQLWARN` populated). Cobble is a static analyser, not a mirror of
squall's runtime: a missing edge is unsound for reachability and dead-code,
where an unexecuted one is merely imprecise.

### 4. Transfer label

Defect 3 is only partly addressed, and deliberately. With the directive typed,
cobble can distinguish a `WHENEVER` from an executable `EXEC SQL` — enough to
emit no node for the former and to know the latter is a branch point. It cannot
label a `SELECT` apart from an `UPDATE`: the `Kind` enum lives in
`squall.parser.sql_model` and identifying it needs the full grammar, which
cobble may not import. Moving `Kind` to the leaf as well would mean moving the
whole statement grammar, which this design does not do.

So the transfer stays `EXECSQL` for executable statements, and a governed one is
recognised by the TEST chain that follows it.

## Out of scope

- `DO`/`PERFORM`/`STOP` actions: not Db2 WHENEVER.
- `SQLSTATE`-based arms of `NOT FOUND` and `SQLWARNING`. Squall writes only
  `SQLCODE` (`binding.write_sqlcode`); `SQLSTATE` is declared and never
  populated. The `SQLCODE` arms subsume them for every program squall can run.
- Making squall branch on `SQLWARNING` at runtime: squall-ud0, unchanged here.
- Cursor-scoped or nested-program scope rules.

## Testing

- `squall`: directive round-trips through `SqlDialectParser` into
  `ExecSqlStatement.directive`; `strategy` lowers from the field with no
  re-parse; existing `test_whenever.py` and the Db2 e2e stay green.
- `cobble` unit: the scope pre-pass over textual order, including the
  skipped-directive case above, `CONTINUE` clearing a condition, and a directive
  after a statement not governing it.
- `cobble` CFG: the 20-line reproduction program above, asserting the concrete
  node ids and edge set — the handler paragraphs reachable from the `SELECT`,
  and the directives contributing no nodes.
- Mutation checks: drop a condition from the active set; make the pre-pass
  flow-sensitive and confirm the skipped-directive test fails.

## Risks

- Relocating the vocabulary touches squall's parser and strategy; the Db2 e2e is
  the guard, and it needs a running Db2 (Colima, then `make db2-up`).
- Node counts rise for SQL-heavy corpora — three TEST nodes per governed
  statement with all conditions active. `cobble-compare`'s 449/803 identity case
  is CICS-only and unaffected; a SQL corpus's CFG node counts will move.
