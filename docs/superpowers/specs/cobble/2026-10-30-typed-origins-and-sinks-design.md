# Typed origins and sinks

**Date:** 2026-10-30. **Package:** cobble. **Size:** heavy (a new value type through the field
dataflow, the fixpoint artifacts, provenance and the partition graph).

## Why

A field-dataflow **origin** (where a value came from when it is not storage) and a **sink**
(where bytes leave the program) are each one string whose kind is packed into its spelling. The
spellings are not even uniform:

| today | kind packed how |
|---|---|
| `FILE:ACCTFILE-FILE`, `MAP:COSGN0A`, `FUNCTION:CURRENT-DATE`, `UNKNOWN:CPY-AMT` | `KIND:` prefix |
| `%CALL:COBDATFT`, `%CALL:'SUBPROG'`, `%CALL:%DYNAMIC:WS-PROG` | sigil plus prefix, nested for dynamic |
| `LITERAL` plus a separate `literal` field (`'Y'`, `SPACES`) | bare word, text elsewhere |
| `%CICS-STATE`, `FIGURATIVE`, `LENGTH-OF`, `UNKNOWN-NAME`, `FUNCTION` | bare word |
| `FIELD:A,B` | prefix plus comma-joined names |
| `MAP:M1→WS-UNSTAGED` | any of the above plus an arrow and a target name |
| `SET`, `ACCEPT`, or a Python class name | the statement verb (`UnmodelledWrite.verb`) |
| sinks: `FILE:X`, `MAP:M`, `TSQ:Q`, `TDQ:Q`, `TRANSID:T` | `KIND:` prefix |

Readers recover the kind by parsing: `experimental/partition/dataset_resolution.py` strips `FILE:`
from origins and sinks; `docs/presentation/capture/cobble.sh` compares trace text to `LITERAL` and
`%CICS-STATE`; `fixpoint/query.py` splits edge ids on the first dot. An external reader (the
Datalog experiment) had to classify 606 origin labels against a list it guessed. This breaks the
design principle "do not encode information in string representations".

## Goal

An origin and a sink are each a value with a **kind from a closed enum** and a **name**, from the
statement that creates them to every artifact and reader. No reader learns a kind from text.

### Non-goals

- The CFG's own `FILE:`/`MAP:`/`PROGRAM:` read/write names (`depgraph/flows.py`,
  `srccfg/synthetic.py`). They never flow into origins, have one uniform shape, and are a separate
  change if wanted.
- `OperandExtents.reason` (`"figurative"`, `"unknown-name"`, ...) stays a string inside
  `extent.py`; `transfer.py` maps it to an origin kind at the one place it builds the origin.
- Backward compatibility of artifacts, ids or text output (user's ruling: "not worried about
  backward compat, make it whatever makes the thing unambiguous"). A run is rebuilt after this
  change; nothing reads an old run.

### Anti-goals

- A second encoding of the same thing (e.g. keeping the old `origin` string beside the new
  object). One representation.
- Any reader still calling `startswith`/`split`/`removeprefix` on an origin, a sink or an id.

## Decided

1. **Types.** `Origin(kind: OriginKind, name: str, unplaced: str = "")` and
   `Sink(kind: SinkKind, name: str)`, frozen dataclasses, one class per file, in
   `cobble/dataflow/fields/`. Null objects `NO_ORIGIN` (`OriginKind.NONE`) and `NO_SINK`
   (`SinkKind.NONE`) replace the empty string; "is this storage?" becomes a kind test.
2. **Origin kinds** (one per row of the table above):
   `NONE, LITERAL, FILE, MAP, CALL, DYNAMIC_CALL, CICS_STATE, FUNCTION, UNKNOWN_FIELD, FIGURATIVE,
   LENGTH_OF, UNRESOLVED_OPERAND, UNMODELLED`.
   - `LITERAL`: `name` is the literal as written (`'Y'`, `SPACES`, `0`), empty for INITIALIZE.
     `Source.literal`, `FlowEdge.literal`, `FlowAttrs.literal` and `DepRow.literal` go away.
   - `FUNCTION` and `UNKNOWN_FIELD`: `name` is the function or field name, empty where today's
     string is the bare word.
   - `UNRESOLVED_OPERAND` replaces `FIELD:A,B`: **one source per name**, never joined.
   - `UNMODELLED`: `name` is the verb as today (including the class-name fallback).
   - `CALL`: `name` is the member, without quotes, for a batch `CALL 'X'` and for a CICS
     `LINK`/`XCTL` whose `PROGRAM` operand is a literal (`CicsOperand.is_literal`).
     `DYNAMIC_CALL`: `name` is the identifier, for a batch `CALL WS-X` **and** for a CICS
     `LINK`/`XCTL` whose `PROGRAM` is a variable — today written `%CALL:CDEMO-TO-PROGRAM`, which
     reads as a call to a member of that name (user's ruling: fix it).
   - `unplaced` replaces the `→target` suffix: the target operand that had no extent.
3. **Sink kinds:** `NONE, FILE, MAP, TS_QUEUE, TD_QUEUE, TRANSID`.
4. **Wire format: a nested object** (user's choice). Fixpoint `graph.jsonl` edge
   `attrs.origin = {"kind": "FILE", "name": "ACCTFILE-FILE"}` (plus `"unplaced"` only when
   non-empty); `attrs.literal` is removed. Fixpoint `sinks.jsonl` `sink = {"kind": ..., "name": ...}`.
   Kinds serialise as the enum's value, upper-case as listed. `AttrValue` already admits a mapping;
   `FlowAttrs.origin` and `SinkRow.sink` become Pydantic models of the same shape.
5. **One uniform text form** (my call, under the user's ruling): `KIND:name`, or `KIND` alone when
   the name is empty, from one function per type (`Origin.text()`, `Sink.text()`). It builds the
   fixpoint source id `PROG.<text>` (upper-cased as today), the partition terminal ids
   `P|origin|<text>` / `P|sink|<text>` and labels, and trace-query output. The old spellings go:
   `%CALL:X` becomes `CALL:X`, `%CALL:%DYNAMIC:X` becomes `DYNAMIC_CALL:X`, `%CICS-STATE` becomes
   `CICS_STATE`, `LITERAL` + `'Y'` becomes `LITERAL:'Y'` in **both** graphs (so the fixpoint graph
   gets one source node per literal value, as the partition graph already has). `unplaced` is not
   part of the text; it lives only in the object. Ids are opaque keys: nothing parses them.
6. **Partition terminal nodes** gain one field, `terminal: {"kind", "name"}` (my call; set on
   origin and sink nodes, empty object elsewhere is not emitted). Readers use it, never the id.
7. **Every parser of an origin or sink goes.** `dataset_resolution.py` tests `kind == FILE` on
   origin and sink and stops importing depgraph's `FILE_PREFIX`. `docs/presentation/capture/cobble.sh`
   compares trace-query text to `LITERAL` and `%CICS-STATE`; it moves to the new text
   (`LITERAL:`, `CICS_STATE`) — it matches display text a person also reads, which is acceptable for
   a capture script, but it must be updated or it silently matches nothing.
   **Out of scope:** `fixpoint/query.py:762-790` splits every *field* id (`PROG.FIELD`) on its first
   dot to find the program. That is the field-id encoding, not an origin one; origin text in an id
   never contains a dot (literal text does, but `name` is not split), so it keeps working.
8. **Docs and skill in the same commit**: `docs/reference/cobble/field-dataflow.md`,
   `docs/reference/cobble/partition.md`, `cobble/skills/cobble-artifacts/SKILL.md` (the copy under
   `.claude/skills/` is refreshed by `make skills`). Dated specs and plans are not edited.
9. **A run's artifacts are not readable across the change**: provenance raises its "stale
   artifacts" error on a `FlowAttrs` validation failure. `SinkRow` validation
   (`fixpoint/provenance.py:132`) has no such handler today and raises a raw `ValidationError`; it
   gets the same stale-artifacts message (my call).

## Where it lands

| stage | change |
|---|---|
| `fields/state.py` | `Source.origin: Origin`, drop `literal`; drop `LITERAL`/`CICS_STATE` string constants |
| `fields/transfer.py` | every producer builds an `Origin` (lines ~136-175, 537, 581, 677-685, 699-800, 864-916) |
| `fields/sinks.py` | `Sink.name: str` becomes the typed sink (rename the existing `Sink` record, which pairs a sink with its operand, or give it a `sink: Sink` field) |
| `fixpoint/fixpoint.py`, `fixpoint/flow_attrs.py`, `fixpoint/sink_row.py`, `fields/side_tables.py` (`ProgramSink`) | carry the typed values |
| `fields/emit.py` | write the nested object; ids from `text()` |
| `fixpoint/provenance.py`, `fields/dep_row.py` | `DepRow.origin: Origin`, `DepRow.sink: Sink` |
| `fields/trace_query.py` | print `text()` |
| `knowledge_graph/graph_types.py:51` | the comment listing origin spellings |
| `docs/presentation/capture/cobble.sh:169` | match the new text |
| `experimental/partition/graph_build.py`, `graph_node.py`, `dataset_resolution.py` | terminal ids from `text()`, `terminal` field, kind tests |
| tests | ~25 files assert today's strings; fixtures `tests/dataflow/fixpoint/fixpoint_dir.py` and `tests/dataflow/fixpoint/data/jumps_baseline/graph.jsonl` |

## Success

- `rg` finds no `startswith`/`removeprefix`/`split` on an origin, sink or terminal id in cobble.
- A rebuilt CardDemo run differs from the frozen run only by the planned changes: the new
  `origin`/`sink`/`terminal` objects, ids and labels in the new text form, one fixpoint source node
  per literal value, `UNRESOLVED_OPERAND` split per name, and `COACTVWC`'s CICS call through
  `CDEMO-TO-PROGRAM` as `DYNAMIC_CALL`. Every other node, edge and count is unchanged.
- The Datalog experiment's exporter reads `terminal.kind` and drops its label classifier.

## Left to the builder

- Module and enum file names; whether `text()` is a method or a function beside the type.
- Whether `fields/sinks.py`'s existing operand-carrying `Sink` is renamed or wraps the new type.
- Commit split, within the repo rule that each commit is green and carries its tests.
