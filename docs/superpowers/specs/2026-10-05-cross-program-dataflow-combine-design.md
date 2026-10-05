# Cross-program dataflow: linking the per-program results

**Status:** design agreed in conversation 2026-10-05; spec awaiting review
**Scope:** `cobble/cobble/dataflow/` — one new table from `cobble-dataflow-fixpoint` (`jumps.jsonl`), one new command
**Issue:** `red-dragon-forge-hab`
**Supersedes:** the "Unit 2" sketch in `2026-09-30-cobble-dynamic-call-resolution-design.md` §11. See
"Decisions".

## The problem

`cobble-dataflow-fixpoint` analyses one program at a time. A value that arrives from another
program — through a COMMAREA, a `CALL ... USING` argument, or what a called program hands back — is
recorded as `inbound-linkage` or `from-callee` and carries no values. A dynamic jump whose target
comes from such a value misses real targets.

Measured on CardDemo (2026-10-05): 24 dynamic sites, all `EXEC CICS XCTL PROGRAM(<field>)`.
20 resolve completely. 4 each miss one real target, all in the "PF3 returns to whoever started me"
idiom:

| Site | Has | Missing | Why |
|---|---|---|---|
| COCRDSLC:331 | COMEN01C | COCRDLIC | COCRDLIC moves its own name into `CDEMO-FROM-PROGRAM`, then jumps to COCRDSLC |
| COCRDUPC:473 | COMEN01C | COCRDLIC | same |
| COUSR02C:258 | COADM01C, COSGN00C | COUSR00C | COUSR00C moves `'COUSR00C'` there, then jumps to COUSR02C |
| COUSR03C:205 | COADM01C, COSGN00C | COUSR00C | same |

The checked-in `cobble/reference/graph.jsonl` has the same gap, so `cobble-compare` cannot catch it.

## Constraint

No program is analysed as part of a combined whole-program graph, and no program is analysed more
than once. Cross-program work reads the per-program results already on disk.

## The idea

The fixpoint already writes, per program, nearly everything needed to link programs together:

- **`defs.jsonl`** — for every read: which statements could have written those bytes, the values
  they can hold, and why they might hold more. COCRDSLC's read of `CDEMO-FROM-PROGRAM` is already
  there with no writer and the reason `inbound-linkage` — "whatever came in".
- **flow rows in `graph.jsonl`** — every copy, with its statement and exact byte ranges
  (`source_extent`, `target_extent`).
- **`aliases.jsonl`** — how a caller's bytes line up with a callee's, for literal jumps.

The existing query tool (`cobble-dataflow-fixpoint-query reached-by --across-calls`) already walks
backwards through copies byte-precisely and crosses programs over those line-ups.

What is missing is small: nothing on disk says **what a jump hands over at the moment it jumps**.
A jump is not a read the way a `MOVE` is, so `defs.jsonl` has no row for the passed bytes at the jump
node (verified: COCRDSLC's `XCTL` node has none). Write that down once per jump, and linking programs
is a matter of joining tables.

## Part 1: the fixpoint writes what each jump hands over

`cobble-dataflow-fixpoint` stays single-program and its analysis is unchanged. It gains one output,
read off the settled state it already has: **`members/<P>/jumps.jsonl`**, one self-contained row per
jump, exit or `RETRIEVE`, saying where the jump goes, what memory it hands over, and what that memory
held at that moment. `defs.jsonl` and `graph.jsonl` are not changed.

```json
{"program": "COCRDLIC", "node": "0000-MAIN/12.when.5.11", "line": 538, "kind": "XCTL", "returns": false,
 "target": {"extent": "CCARD-NEXT-PROG@working_storage[856:864]",
            "values": ["COCRDSLC"], "writers": ["0000-MAIN/12.when.5.9"], "reasons": []},
 "transid": {"extent": "", "values": [], "writers": [], "reasons": []},
 "areas": [{"param": 0, "extent": "CARDDEMO-COMMAREA@working_storage[0:160]",
            "fields": [
              {"extent": "CDEMO-FROM-TRANID@working_storage[0:4]",   "values": ["CCLI"],     "writers": ["0000-MAIN/12.when.5.7"], "reasons": []},
              {"extent": "CDEMO-FROM-PROGRAM@working_storage[4:12]", "values": ["COCRDLIC"], "writers": ["0000-MAIN/12.when.5.8"], "reasons": []},
              {"extent": "CDEMO-USER-ID@working_storage[12:20]",     "values": [],           "writers": ["0000-MAIN/1"], "reasons": ["not-a-literal"]}]}]}
```

(Offsets and node ids in examples are illustrative.)

- `kind`: `XCTL`, `LINK`, `CALL`, `RETURN_TRANSID`, `START`, `EXIT` (a `GOBACK` or an
  `EXEC CICS RETURN` without `TRANSID`), or `RETRIEVE` (where a started program receives a `START`'s
  `FROM` bytes; its one area is the `INTO` field).
- `target`: the program jumped to, in one shape whatever the source: `values` are the names it can be,
  and `extent`, `writers` and `reasons` say where they came from. A literal target is just
  `values: ["COMEN01C"]` with an empty `extent` and no writers or reasons. Empty for `RETURN_TRANSID`,
  `START`, `EXIT` and `RETRIEVE`.
- `transid`: for `RETURN_TRANSID` and `START`, the transaction, in the same shape.
- `areas`: each separate block of memory handed over, with `param` = its position. A CICS jump hands
  over one block (its COMMAREA, or the `FROM` area of a `START`); a `CALL ... USING a b c` hands over
  three, one per argument, because they sit at unrelated places in the caller's memory. An `EXIT`
  row lists the program's own received areas (its `DFHCOMMAREA`, or its `USING` parameters), as they
  are when control goes back.
- `fields`: one entry per **elementary field inside the area**, with what the settled state says about
  those bytes at the jump: `values`, `writers` (the nodes that last wrote them) and `reasons` — the
  same three facts a `defs.jsonl` row carries for any other read. Per field rather than one entry per
  area, because a whole-area read returns no value when its bytes come from different writes:
  COCRDLIC's COMMAREA holds `'COCRDLIC'` in only 8 of its bytes.
- `XCTL`, `LINK` and `CALL` are jump nodes in the source CFG (`srccfg.desugar.CALL_TRANSFERS`); their
  areas come from the same operand resolution `fields/aliases.py` uses. `RETURN TRANSID`, `START` and
  `RETRIEVE` are not jump nodes there, so they are found by reading those statements' `TRANSID`,
  `COMMAREA`, `FROM` and `INTO` options at their nodes.

## Part 2: `cobble-dataflow-combine`

```
cobble-dataflow-combine --config <corpus> --fixpoint-dir <dir> --out-dir <dir> (--all | --member NAME [NAME ...])
```

- `--config`: the corpus TOML. Supplies the CSD files (`csd_files`), read with
  `cics.csd_parse.parse_csd` exactly as `cobble/build_graph.py` already does, to map a
  `RETURN TRANSID` / `START` transaction to its program; and the parsed-file directory (`asg_dir`),
  for the callee side of line-ups.
- `--fixpoint-dir`: a `cobble-dataflow-fixpoint` output directory.
- `--all` / `--member`: exactly one, as on `cobble-dataflow-fixpoint`. `--all` links every program
  with results in `<fixpoint-dir>/members/`; `--member A B C` links those programs only. Results of
  other programs are ignored even if present.

### The resolve step

One function answers every question linking asks: **what can these bytes hold at this point, and
where did they come from?** Its input is a program, a node and a byte range — nothing else. It looks
up what is recorded about those bytes at that point itself: in the jump's `jumps.jsonl` row when the
node is a jump, exit or `RETRIEVE` (`defs.jsonl` has no row there), and in the `defs.jsonl` row for
that read otherwise. If neither table has a row — nothing at that node read those bytes — it answers
that no facts are recorded there, and guesses nothing.

- **The node is the point in the program.** Every answer describes the bytes as they are when control
  reaches that node, over every path that reaches it: the writers are the statements that could have
  last written those bytes *before* that node, and a write that only happens after it does not count.
  The same field can give different answers at different nodes.
- **Where paths join, their histories are combined, not kept apart** — the existing fixpoint's rule.
  If one branch writes `'COMEN01C'` and the other copies `CDEMO-FROM-PROGRAM`, the answer at the jump
  is "either", without saying which branch gave which. This is what gives COCRDSLC both candidates.
- **Callers only say where to look.** Linking asks about a jump's `target` field or a field in its
  `areas`, at the jump node. A later general query ("what can `ACCOUNT-RECORD` hold at line 300,
  across programs") would ask about any read, at its node. Because the resolve step takes any
  (program, node, byte range), adding such a query later is purely additive; it is not part of this
  design.

From the facts recorded at that point, it walks back as follows.

Recorded values are known directly. Where the bytes have writers, which bytes they came from is
found by walking backwards over that program's own tables: from each recorded writer to its flow row
and the bytes it copied, then to the `defs` row for those bytes at that writer, rebasing the byte
range through each copy, until reaching one of these. **What a stop means is decided by the node it
stops at, never by a reason string**:

- a read of received bytes with no writer in the program (a LINKAGE `defs` row with no definers,
  reason `inbound-linkage`) → **received**: the program's received area `param` *p*, bytes *[a, b)*;
- a write with a synthetic origin at a node `jumps.jsonl` lists as `LINK` or `CALL` — how the
  fixpoint records what a call left behind (`fields/transfer.py`) → **returned**: that call, the area
  whose byte range the written bytes fall in (matched against the row's `areas`), bytes *[a, b)*;
- a write with a synthetic origin at a node `jumps.jsonl` lists as `RETRIEVE` → **retrieved**: that
  `RETRIEVE`'s area, bytes *[a, b)*. Its reason is the generic `not-a-literal` today, which is why the
  node, not the reason, decides;
- anything else (arithmetic, a file, any other synthetic origin) → **unknown**, keeping its reason.

The walk needs no field identities and no layouts, only byte ranges, and both tables already carry
them in the same text form (`fields/extent_text.py`): a `defs` row's `extent` and a flow row's
`source_extent` / `target_extent`. The fixpoint writes each `defs` row with exactly the extent of the
flow source it describes, so the walk runs on two small per-program indexes built straight from the
rows:

- **writers of these bytes at this node:** `defs.jsonl` keyed by (program, node, extent);
- **what a writer copied:** the flow rows of `graph.jsonl` at that writer's node, matched by byte
  overlap with the bytes being followed.

It does not use `fixpoint/query.py`'s `FieldStore` or `reaches()`: those model fields by id, which
needs `extents.jsonl` (108 MB for the 29 CardDemo programs) and returns field ids rather than byte
ranges and where each path stopped.

### Linking: the call graph and the values together, in rounds

The call graph is an **output** of linking, not an input: some jumps get their targets only from
values another program passes, which is exactly what linking finds.

1. **Start** with the edges known without linking: every jump in `jumps.jsonl` whose target is a
   literal or a field already resolved within its program (`targets.jsonl`). For `RETURN_TRANSID`
   and `START`, the transaction is mapped to its program through the CSD.
2. **Fill.** Received bytes of program P are the union, over every jump currently into P, of that
   jump's handed-over bytes (the `fields` of its `jumps.jsonl` row), lined up with P's received
   area.
   Returned bytes at a `LINK` / `CALL` are the callee's handed-over bytes at its `EXIT` rows.
   Retrieved bytes at a `RETRIEVE` are the `FROM` bytes of every `START` of that program's
   transaction. Where
   those are themselves received or returned, follow them into that program's own callers or
   callees.
3. **Re-read targets.** A jump whose target field depends on received or returned bytes gains the
   names now known as **new edges**.
4. **Repeat** 2–3 until a round adds no edge and no value.

It terminates: programs, jumps, fields and values are finite, and every round only adds. A value
that depends on itself through a cycle of programs is resolved by the rounds, not by recursion.

### Lining two programs up

Caller byte *k* of the area handed over is callee byte *k* of the received area — the 2026-09-07
spec's rule — and only the overlap of the two sides' declared lengths is shared. Linking computes
the line-up for every edge it uses, from the caller's area in `jumps.jsonl` and the callee's
`DFHCOMMAREA` or `USING` parameter at that position, through the functions `fields/aliases.py`
already uses, made public. It cannot take line-ups from `aliases.jsonl`: that table is written before
any cross-program target is known, so it has no row for a dynamic jump — which is exactly the kind of
edge linking discovers.

### `CALL ... USING`

Already bound by position: the bridge emits `procedure_using` (red-dragon `415d7c64`), cobble binds
`CALL` arguments to parameters (cobble `14e323d`), and red-dragon's execution binds them in `USING`
order (`tests/integration/test_cobol_procedure_using.py`, passing 2026-10-05). Argument *i* lines up
with the callee's received area `param` *i*. Nothing upstream is needed.

### Edges of the set

A program in the set may also be jumped to from a program outside it. Linking reads the
`jumps.jsonl` of every program **outside** the set that has results in the fixpoint directory — only
`kind` and `target`, never the values, which outside programs do not contribute. Then:

- any value that depends on received bytes of a set program that a known outside jump reaches keeps
  the reason `outside-analysed-set`, naming those outside programs, beside the values the set did
  supply. Only outside jumps whose target is known — literal, or resolved within that program — count
  here; an outside jump whose target is unresolved could point anywhere, and marking every value with
  it would make the reason meaningless;
- two facts are reported once for the whole run instead: how many outside programs have no results in
  the fixpoint directory (their jumps into the set are unknown), and how many outside jumps have
  unresolved targets.

With `--all` nothing is outside, so neither the reason nor the report appears.

### What is left unknown

Received bytes of a program nothing in the set jumps to — a transaction started from a terminal, a
batch program started by JCL — keep `inbound-linkage`. A computed value stays `not-a-literal`.
Nothing is guessed.

### Missing results

If a `--member` name has no results in the fixpoint directory, the command names every such program
and exits non-zero without writing anything, rather than linking a smaller set than was asked for.
There is no staleness check by file time: copying or checking out files changes modification times,
so such a check would refuse good results as readily as it caught stale ones.

### Outputs: `<out-dir>/`

- **`targets.jsonl`** — the fixpoint's targets table, same shape, with linked candidates added. A
  site's `reasons` keep only what is still unresolved after linking, plus `outside-analysed-set`
  where it applies.
- **`links.jsonl`** — one row per program-to-program edge used: the `aliases.jsonl` shape (caller,
  node, transfer, callee, caller extent, callee extent, returns) plus `"discovered": true` for edges
  found by linking rather than written literally.

The fixpoint's own output directory is never modified, so single-program and linked results can
always be compared. `defs.jsonl` and `graph.jsonl` are not rewritten.

### Cross-program provenance

`cobble-dataflow-fixpoint-query reached-by` / `reaches --across-calls` gains `--links <file>`:
given the combine step's `links.jsonl`, it crosses programs over those line-ups instead of
`aliases.jsonl`'s, so provenance follows discovered jumps too. Without the option it behaves exactly
as today.

### Downstream

`cobble-build --dynamic-call-targets <out-dir>/targets.jsonl`, unchanged. `cobble-build` resolves
nothing itself (decision 4 of the 2026-09-30 spec). Because the CardDemo graph gains the four
missing edges, `cobble/reference/graph.jsonl` is regenerated deliberately, in the same commit as the
change that adds them.

## `aliases.jsonl` stays

It serves the pipeline that skips combining: someone who does not need cross-program targets
resolved runs the fixpoint alone and still gets every caller-to-callee line-up the fixpoint can know
by itself, with `--across-calls` provenance over them. Its one downstream reader is
`cobble-dataflow-fixpoint-query --across-calls` (`query.py`); `cobble-fields-trace` computes its own
line-ups with `commarea_aliases()` and does not read the file. With `--links`, the query reads the
combine step's `links.jsonl` instead, which adds the discovered edges.

Today the table is narrower than "everything the fixpoint can know by itself": `aliases.py` refuses
every jump whose target is a field (`dynamic-target`), including those the single-program analysis
resolved completely — all 24 CardDemo `XCTL`s, 20 of them fully resolved, such as the menu's jump to
11 programs. Lining those up as literal jumps are lined up is tracked separately
(`red-dragon-forge-093`) and does not depend on this design.

## Precision

Context-insensitive: a program's received bytes are the union over all its callers, not tracked per
chain of calls. For the "return to whoever started me" idiom that union is the true answer.

## Testing

Synthetic COBOL only, no corpus members in tests.

- **`jumps.jsonl` rows (unit):** a jump passing a literal, a pass-through of received bytes, a
  computed value, a `CALL` with three arguments (three areas), a `RETURN TRANSID`, a `START` and a
  `RETRIEVE` found from their options, an `EXIT` row after a write-back — each asserting the exact
  row, fields included; and `defs.jsonl` / `graph.jsonl` byte-identical to before.
- **Dependency walk (unit):** received bytes reached through several copies of different widths, a
  partial (reference-modified) copy, a write-back after a `LINK` and after a `CALL` (each mapped to
  the right area), a `RETRIEVE` stop decided by its node, a computed value stopping as unknown.
- **Outside the set (unit):** an outside program with a literal jump into the set produces
  `outside-analysed-set` naming it; one with an unresolved dynamic jump does not, and is counted in
  the run report instead; an outside program with no results is counted in the run report.
- **Linking (unit, over hand-written tables):** the return-to-caller pattern (the `hab` shape); a
  target discovered only across programs (P jumps to what its caller named), proving the call graph
  grows across rounds; a cycle of programs terminating; a window narrower than the area;
  `RETURN TRANSID` re-entry; `START` → `RETRIEVE`; `--member` with an outside caller producing
  `outside-analysed-set`; a `--member` name with no results refused.
- **End to end (integration):** a multi-program synthetic corpus through both commands, asserting
  exact `targets.jsonl` and `links.jsonl` rows, and a `--links` provenance query crossing a
  discovered jump.
- **CardDemo acceptance:** the four `hab` sites gain exactly COCRDLIC / COUSR00C; no other site's
  candidates change; the single-program run's time is unchanged.

## Decisions

1. **Link the existing per-program results; do not re-analyse.** The 2026-09-30 §11 sketch re-ran
   each program with seeded entry states until nothing changed. Superseded: re-analysis repeats the
   most expensive work, and no program may be analysed more than once.
2. **No separate summary format.** An earlier draft of this spec had each program write "notes" — a
   new summary of what every jump passes, byte run by byte run — and rewrote `defs.jsonl` and
   `graph.jsonl` afterwards. Rejected: the notes restated what `defs.jsonl` and the flow rows already
   hold. The only missing fact was what a jump hands over and what it held, which one `jumps.jsonl`
   row per jump supplies.
3. **The analysis core is unchanged, and so are the existing tables.** `jumps.jsonl` is read off the
   settled state; nothing already written changes. Putting a jump's contents in its own row, rather
   than as extra `defs.jsonl` rows, keeps each jump self-contained and leaves `defs.jsonl` meaning
   exactly what it means today.
4. **A separate command.** Linking is a different kind of work from analysing a program; keeping it
   separate leaves `cobble-dataflow-fixpoint` single-program and lets linking be re-run alone.
5. **Byte areas, not fields.** The called program reads the passed bytes through its own layout, so
   programs are lined up by byte position, never by field name.
6. **Explicit scope: `--all` or `--member`.** A subset is linked honestly, with outside callers
   named, so a connected subset of a large corpus can be linked without the rest.
7. **Provenance through the existing query**, fed discovered links, rather than new cross-program
   rows in `defs.jsonl` / `graph.jsonl`.
8. **Linking needs no field layouts.** The walk joins `defs` and flow rows by the byte ranges they
   already carry, so the combine step never loads `extents.jsonl` (about 3.7 MB per program) or the
   query tool's field model. Field layouts are read only for the callee side of a line-up, from the
   parsed file, as `fields/aliases.py` does today.
9. **Subset edges stay honest without becoming noise.** Only outside jumps with a known target mark
   a value `outside-analysed-set`; outside programs without results and outside jumps with unresolved
   targets are reported once per run, not on every value.
