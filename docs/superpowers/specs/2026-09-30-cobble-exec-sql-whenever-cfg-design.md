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

## The prerequisite defect: the statement does not survive the cache

`ExecSqlStatement` writes one key and reads another:

```python
to_dict()                 -> {"type": "EXEC_SQL", "text": self.text}
SqlDialectParser.parse()  -> ExecSqlStatement(text=data.get("exec_sql_text", "") or "")
```

The bridge emits `exec_sql_text`, so a first parse is correct. `to_dict()` then
writes `text`, and reading that back finds no `exec_sql_text` and yields the
empty string. Reproduced three ways — direct round-trip through `to_dict()`, and
`asg_of()` over a real cached ASG on disk, both giving `text=''` where the JSON
on disk plainly holds the statement.

Cobble's CFG is built from the **cache**, never from source, so **every
`EXEC SQL` cobble sees is already empty**. Nothing caught it because nothing
downstream reads `ExecSqlStatement.text` yet — which is the gap this design
closes, so it must be fixed first or the directive is dropped the same way.

`ExecCicsStatement.to_dict()` documents exactly this hazard and avoids it:

> RedDragon's to_dict() convention is an informational round-trip, but this one
> is load-bearing — cobble's parsed-ASG cache IS `CobolASG.to_dict()`, and every
> stage after its parse reads the JSON rather than the source. A key dropped
> here is a key no consumer can ever recover.

## Root cause

Two, compounding.

**The vocabularies are not symmetric.**

```python
ExecCicsStatement(verb: str, options: dict[str, CicsOperand | None])   # structured
ExecSqlStatement(text: str)                                            # a string
```

`_exec_cics` can dispatch on `statement.verb`. There is no `_exec_sql` because
SQL hands the ASG an undifferentiated blob, which squall then re-parses at every
lowering. `guardrails.md` names this directly: text is a boundary, never a
carrier.

**And the blob does not round-trip**, so even the string is unavailable to any
stage reading the cache.

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

### 1. Make the statement survive the cache (`squall/statements.py`)

Reader and writer must agree. `SqlDialectParser.parse` accepts the bridge's
`exec_sql_text` **and** `to_dict()`'s `text`, because it is fed by both: the
bridge on a first parse, the cache on every read afterwards. A round-trip test
is the point of the change — `parse(stmt.to_dict()) == stmt` — and it covers the
`directive` field added below, which would otherwise be dropped identically.

Independently committable and worth having on its own, since it repairs the
string for any future consumer even if nothing else here lands.

### 2. Let cobble use squall's parser

`squall.parser` is four files whose entire import surface is stdlib, `lark`, and
its own `sql_model`. No connector, no binding, no backends, no strategy — it is
a grammar-based text-to-model parser, which is what cobble does for a living
(it already parses with Lark three times over through `cobol_asg`). Its presence
on `cobble-no-runtime` is over-broad: the contract exists to keep a static
analyser out of runtimes, and this is not one.

```diff
 [importlinter:contract:cobble-no-runtime]
 forbidden_modules =
-    squall.parser
+    squall.preprocess
     squall.strategy
```

The `.importlinter` comment naming cobble's allowed surface is updated in the
same commit; it is a review obligation, not an automated one, and it goes stale
silently.

`SqlDialectParser` then calls `parse_exec_sql` and stores a typed `directive` on
`ExecSqlStatement`. One parser, one grammar, nothing relocated. `squall.strategy`
reads `stmt.directive` for the WHENEVER case instead of re-parsing, which is the
guardrail violation that started this.

Only the directive is stored, not the whole `ParsedSql`: cobble has no use for
the rest, and it would enlarge the cached JSON for every SQL statement in a
corpus. Squall still parses non-WHENEVER statements at lowering for their
execution plan, as now.

Measured cost of parsing at ASG construction: 1.2–4.0 ms per statement, against
4–7 **seconds** of JVM per member, paid once into the cache.

### 3. Source-order scope pre-pass (`srccfg/build.py`)

A pass over `paragraph_order` in source order, threading
`dict[WheneverCondition, WheneverAction]` and recording, per `EXEC SQL`
statement, the active `GO TO` targets at that point. `CONTINUE` clears a
condition. The result reaches lowering on `Ctx`, exactly as
`build._error_handlers` already feeds `Ctx.error_handlers`.

Per-statement rather than per-paragraph, because the directive can change
mid-paragraph.

### 4. `_exec_sql` handler (`srccfg/desugar.py`)

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

### 5. Transfer label

Defect 3 is only partly addressed, and deliberately. With the directive typed,
cobble can distinguish a `WHENEVER` from an executable `EXEC SQL` — enough to
emit no node for the former and to know the latter is a branch point. Labelling
a `SELECT` apart from an `UPDATE` needs `Kind` from the full parse; now that
cobble may call `parse_exec_sql`, that becomes possible, but it is not done
here — no consumer asks for it, and it would widen what the cache carries.

The transfer stays `EXECSQL` for executable statements, and a governed one is
recognised by the TEST chain that follows it.

## Out of scope

- `DO`/`PERFORM`/`STOP` actions: not Db2 WHENEVER.
- `SQLSTATE`-based arms of `NOT FOUND` and `SQLWARNING`. Squall writes only
  `SQLCODE` (`binding.write_sqlcode`); `SQLSTATE` is declared and never
  populated. The `SQLCODE` arms subsume them for every program squall can run.
- Making squall branch on `SQLWARNING` at runtime: squall-ud0, unchanged here.
- Storing the full `ParsedSql` on the statement, and per-kind transfer labels.
- Cursor-scoped or nested-program scope rules.

## Units, in order

1. Cache round-trip fix, with a round-trip test. Stands alone.
2. Contract narrowing plus the typed `directive`, with squall reading it instead
   of re-parsing. Existing `test_whenever.py` and the Db2 e2e are the guard.
3. Source-order scope pre-pass, with its own unit tests.
4. `_exec_sql` handler and the CFG assertions.

## Testing

- **Round-trip**: `parse(stmt.to_dict()) == stmt` for a directive and a
  non-directive statement, and `asg_of` over a written cache recovering the text.
- `squall`: directive round-trips into `ExecSqlStatement.directive`; `strategy`
  lowers from the field with no re-parse; `test_whenever.py` and the Db2 e2e
  stay green.
- `cobble` unit: the scope pre-pass over textual order, including the
  skipped-directive case above, `CONTINUE` clearing a condition, and a directive
  after a statement not governing it.
- `cobble` CFG: the 20-line reproduction program above, asserting the concrete
  node ids and edge set — the handler paragraphs reachable from the `SELECT`,
  and the directives contributing no nodes.
- Mutation checks: drop a condition from the active set; make the pre-pass
  flow-sensitive and confirm the skipped-directive test fails; revert the
  round-trip key and confirm the cache test fails.

## Risks

- The contract narrowing widens cobble's dependency surface to a Lark grammar.
  `uv run lint-imports` and the updated `.importlinter` comment are the guard.
- Touching `squall.parser`/`strategy` puts the Db2 e2e on the critical path, and
  it needs a running Db2 (Colima, then `make db2-up`).
- Node counts rise for SQL-heavy corpora — up to three TEST chains per governed
  statement. `cobble-compare`'s 449/803 identity case is CICS-only and
  unaffected; a SQL corpus's CFG node counts will move.
- Every cached ASG predating unit 1 holds SQL statements that read back empty.
  They are not wrong on disk, only misread, so a re-read is enough and no
  reparse is needed — but any stage that cached a *derived* artifact from the
  empty text must be rebuilt.
