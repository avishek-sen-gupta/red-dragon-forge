# Unmodelled writes, and values at every write source — Design

**Date:** 2026-10-02
**Status:** proposed
**Scope:** `cobble` only. Two units, in this order, both landing before the next
corpus re-run.

## 1. The defect: a statement without a transfer loses its writes

`cobble/dataflow/fields/transfer.py` dispatches on statement class. Eight classes
have a handler — `MOVE`, `INITIALIZE`, arithmetic, `COMPUTE`, `STRING`, `READ`,
`CALL`, `EXEC CICS` — and every other class is an identity transfer: no
definition generated, nothing killed, values untouched.

That is unsound for every class that writes storage. Reproduced through the bridge
and the full pipeline: three fields declared `VALUE 'PROGA'`, each overwritten by
one unhandled statement, then called through:

| Statement | True target | `targets.jsonl` today |
| --------- | ----------- | --------------------- |
| `ACCEPT WS-P1` | unknown | `["PROGA"]`, no reasons — a proven edge |
| `UNSTRING WS-IN … INTO WS-P2` | `PROGC` | `["PROGA"]`, no reasons |
| `SET P3-IS-B TO TRUE` | `PROGB` | `["PROGA"]`, no reasons |

The same loss reaches `graph.jsonl` (no flow from the statement) and `defs.jsonl`
(the statement is never a definer). It is also invisible in the summary: an
unhandled statement adds to `unhandled` but its write operands never enter the
`writes` denominator, so coverage can read 100% while writes are dropped.

Unhandled classes that write: `ACCEPT`, `UNSTRING`, `INSPECT` (`TALLYING`,
`REPLACING`, `CONVERTING`), `SET`, `SEARCH` (`VARYING`), `MOVE CORRESPONDING`,
`ADD`/`SUBTRACT CORRESPONDING`, `WRITE`/`REWRITE … FROM`, `XML GENERATE`.

## 2. Unit 1 — a sound fallback for every unmodelled writer

**Where the targets come from.** Not from ten per-class readers: from the CFG node.
Lowering already gives every statement node its written and read names
(`Node.writes`, `Node.reads`), from two places — the coarse dependency graph's
verb table, `cobble/dataflow/depgraph/flows.py`, which has rules for `UNSTRING`,
`INSPECT`, `SET`, `SEARCH`, both `CORRESPONDING` forms, `WRITE`/`REWRITE` and
`XML GENERATE`; and `desugar.py`'s gap fills, which give `ACCEPT` its target. The
fallback applies to any node whose statement class has no transfer handler, and
reads its writes and reads from the node. Flows are the cross product of the two,
as the coarse graph draws them.

**What the fallback writes.** For each target name, every extent the name resolves
to in the `CellIndex`, and for each:

- **Provenance: a weak update.** The statement is added as a definer; nothing is
  killed. Some of these statements overwrite fully (`ACCEPT`), some partly
  (`INSPECT REPLACING`); the fallback does not know which, and keeping old
  definers is the direction that never drops a real one. Sources are the node's
  read names resolved to extents, so `graph.jsonl` gains the flow; a node with no
  read (`ACCEPT`) gets a synthetic origin named after the verb, as `READ` gets
  `FILE:`.
- **Values: kept, and marked.** The old values may survive (the statement may not
  change them) and new ones may arrive that the walk cannot name, so the target's
  value set keeps what it held and gains a new reason, `unmodelled`. A call site
  through such a field then resolves to candidates with a reason — a
  `*_CANDIDATE` edge — never to a proven edge.

`write()` in `state.py` today kills by `must_cover` for an EXACT target. The
fallback needs a weak write for an EXACT target; the plan decides whether that is a
parameter on `write` or a separate function, and pins the choice with a test that
an EXACT fallback write leaves the prior definer standing.

**Name resolution.** The node holds names, without qualifiers or subscripts. A
name that resolves to several extents writes all of them — weak updates, so an
over-wide write costs precision, never soundness. Prefixed identities (`FILE:`,
`MAP:`, `PROGRAM:`, `TSQ:`, `TRANSID:`) are not storage and are skipped.

**Coverage.** The fallback's resolved targets enter the `writes` denominator and
`covered` like any handled write, and a new summary count, `unmodelled`, says how
many writes went through the fallback. `unhandled` keeps meaning statements with no
handler.

**Not in this unit.** Precise handlers — `SET … TO TRUE` writing the 88-level's
value, `UNSTRING` slicing its source, `ACCEPT` as a named origin — are follow-ons,
each worth doing only where the corpus shows the fallback's imprecision costs
something.

## 3. Unit 2 — the value set at every write source

The walk computes values for every byte range at every node and writes them out at
dynamic call sites only. Unit 2 writes them at every read `defs.jsonl` already
has a row for: each real-storage source of a write (`_at` in
`cobble/dataflow/fixpoint/fixpoint.py`).

**Format: two fields on the existing `defs.jsonl` row**, not a new file. The row's
identity — program, node, extent — is already the read's identity, its consumers
(`fixpoint/query.py`, `fields/trace_query.py`) read rows field by field, and a new
file would need its own sink, member-directory entry and publish step for the same
key.

```json
{"program": "PROGA", "node": "MAIN-PARA/3", "extent": "WS-A@working_storage[0:4]",
 "definers": ["MAIN-PARA/1"], "values": ["YES "], "reasons": []}
```

- `values` — the byte values the read can see, decoded as `targets.jsonl` decodes
  candidates, but **not** trimmed: this is the field's content, not a program name.
- `reasons` — why `values` may be short, the same eight reasons plus `unmodelled`.
- Computed as `values_at(state, source.extent)` at the statement's settled entry
  state — the same call `targets.py` makes, at the same state.

What it does not carry, stated in the README so no one reads silence as an answer:
numeric values (only quoted literals become values; arithmetic and numeric
literals give `not-a-literal`), and reads that feed no write (conditions,
`CALL … USING` arguments, CICS and file operands).

## 4. Order, testing, re-run

1. **Unit 1**, test first: the three-statement program above, bridge-compiled as
   `test_call_shapes_synthetic.py` does, must yield candidates carrying
   `unmodelled` and no proven target; a unit test pins the weak write; a test pins
   the denominator counting fallback writes.
2. **Unit 2**, test first: a bridge-compiled program whose `defs.jsonl` rows are
   asserted whole, values and reasons included, covering a literal copy, a copy
   through a group, a file-read source (`from-file`) and an unmodelled source.
3. **Docs** in the same commits: cobble README's output table, the dynamic-target
   section's reasons table (`unmodelled`), and the coverage counters.
4. **Re-run**, after both land: re-parse with a JAR rebuilt by `make jar-force`,
   then extents, then the fixpoint with `--force`. Every published file changes.

## 5. Out of scope

- `EXEC SQL … INTO` and `FETCH … INTO`. `ExecSqlStatement` carries the SQL as
  opaque text and nothing upstream names its host variables as writes
  (`flows.py`: "a real gap"), so the fallback cannot see them and they stay
  unsound after this change. Closing it needs the host variables parsed out of the
  SQL; it is the first follow-on for a Db2-heavy corpus, and the README says so.

- Values at reads that feed no write (option (b) in the brainstorm). Each such
  unit needs a fresh corpus run, and none was asked for.
- Persisting the per-statement state.
- Precise handlers for the unmodelled classes (§2, last paragraph).
