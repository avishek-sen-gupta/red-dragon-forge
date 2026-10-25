# The fixpoint emits byte provenance; fields-trace goes

Date: 2026-10-25. Status: design, not started.

## Intent

The partition graph, the aggregates stages and the provenance queries read byte provenance from
`cobble-fields-trace`. The trace was the cheap way to get provenance for every field, because the
only fixpoint run cheap enough for the partition pipeline is narrowed to what call targets need
(`--call-targets-only --narrow-areas`). The fixpoint already computes provenance for every byte it
tracks, and it already has a sweep cap (`--sweeps N`) that bounds its cost and reports when a member
did not settle. So one capped, whole-scope fixpoint run can supply both the resolved targets and the
provenance, and the trace, its sampling and its blind spots leave the pipeline.

## Goals

- `cobble-dataflow-fixpoint` has one scope, whole: every written byte is tracked. Its outputs carry
  everything the trace's dep rows carried that consumers use.
- The partition graph, dataset resolution, `cobble-trace-query` and `cobble-access-query` read the
  fixpoint's and combine's outputs instead of trace files.
- `cobble-fields-trace` and `cobble-viz-pathwalk` are deleted, with their tests, docs and Makefile
  steps.
- `cobble-dataflow-area-need`, `--call-targets-only` and `--narrow-areas` are deleted.

## Scale (decided by the user)

The pipeline after this change will run on a corpus of 3,000+ COBOL programs. The bar:

- it finishes, and is restartable: a rerun skips members already done (the fixpoint's per-member
  `members/` cache already works this way; the new outputs must keep it true);
- it does not run out of memory: every stage that writes or reads provenance streams it, and no stage
  holds the whole corpus's rows at once;
- it takes roughly three hours or less end to end ("in the vicinity of", not a hard limit).

Two places hold corpus-wide state today and are checked against this bar, not assumed fine:
combine loads every program's tables into memory at once (`combine/cli.py:_load_all`), and the
fixpoint's publish step dedupes every row against a corpus-wide set (`FirstSighting` behind
`GraphWriter` and `JsonlWriter`). Rows are program-qualified, so the corpus-wide dedupe can become
per member. Combine's memory is measured on the large corpus and becomes follow-up work if it is
the limit.

Every stage logs its progress as it goes, as the experimental stages already do. Speed-ups are not
designed up front: once the change runs on the large corpus, it is profiled, and whatever the
profile names (the fixpoint's join and `_canonical`, combine's growth with whole-scope tables,
output size) becomes follow-up work, with an issue filed for each.

## Non-goals

- No change to how the fixpoint computes values or provenance: no new lattice, no new transfer
  rules. The work is in what it writes out and who reads it.
- No change to combine's algorithm. It keeps `--max-hops`.
- No new sweep-cap flag: `--sweeps N` exists and stays as it is; a run without it is the worklist,
  as today.
- No path-level output. Nothing replaces the per-path view the trace had.

## Anti-goals

- Consumers must not get a lossy substitute silently: anything a trace dep row gave a consumer that
  the fixpoint's output does not give is either added to the output or named in the consumer's
  docs as dropped.
- No string-encoded structure in the new rows; they follow the guardrails (typed Pydantic rows at
  the file boundary).

## What exists today

The facts the builder needs, checked in the code on 2026-10-25.

**Fixpoint outputs** (`cobble/dataflow/fixpoint/build_corpus.py`, module docstring):

- `graph.jsonl`: one `FLOWS_TO` edge per (node, source extent, target extent), with `attrs.node`,
  `attrs.source_extent`, `attrs.target_extent`. A literal, a file record read or a call result is a
  synthetic source field (`<PROG>.LITERAL`, `<PROG>.FILE:<name>`, `%CALL:<target>`) with an empty
  source extent. Intra-program only: a `CALL`/`LINK` contributes a `%CALL:` source and no edge into
  the callee.
- `defs.jsonl`: the definitions reaching each (node, source extent), with `definers`, `values`,
  `reasons`.
- `aliases.jsonl`, `targets.jsonl`, `jumps.jsonl`.
- `--sweeps N` (reverse-postorder passes instead of the worklist) already reports each member as
  "settled in N sweeps" or "NOT SETTLED after N sweeps -- edges are a subset".
- Scopes (`cobble/dataflow/fixpoint/scope.py`): `WHOLE`, `CALL_TARGETS`, `NARROW_CALL_TARGETS`.
  `--narrow-areas` requires `--call-targets-only`. `cobble-dataflow-fixpoint-diagnose` takes the same
  two flags.

**Trace dep rows** (`cobble/dataflow/fields/trace.py`, `Dep`; written by `trace_report.py`):
`program`, `via` (the call site the program was entered through), `target` extent with `clamped`,
`origin`, `literal` (the literal's text), `sink`, `source` extent, `source_program` (differs from
`program` only at a `LINK` return), `site` (`PROG/node`), `definers` (program-qualified). Sink rows
(`FILE:`, `MAP:`, `TDQ:`) come from `sinks_of` in `cobble/dataflow/fields/sinks.py`, which only the
trace calls. On the CardDemo partition run the traces hold about 2,800 sink rows; the fixpoint's
`graph.jsonl` has none.

**Consumers of trace output:**

| Consumer | Uses |
|---|---|
| `cobble/experimental/partition/graph_build.py` | dep rows become field edges with byte alignments; origins and sinks become terminal nodes, origins named from `origin` and `literal` |
| `cobble/experimental/partition/dataset_resolution.py`, `file_site.py` | file sites from `FILE:` origins and sinks, with `via` telling a call's write-back apart from a file site |
| `cobble/dataflow/fields/trace_query.py` (`cobble-trace-query`) | forward and backward BFS over byte containment, crossing programs along `via` and `source_program` |
| `cobble/dataflow/fields/access_query.py` (`cobble-access-query`) | not trace rows: it reads `cobble-fields-access` rows and only borrows `ByteRange` and `_resolve_from_extents` from `trace_query` |
| `cobble/viz/pathwalk_viz.py` (`cobble-viz-pathwalk`) | recorded paths (`--record-paths`) |

Program crossings in the partition graph already come from combine's `links.jsonl` as well as from
the trace; `--links` stays.

## The design, as decided

1. **One scope.** Delete `CALL_TARGETS`, `NARROW_CALL_TARGETS`, `--call-targets-only`,
   `--narrow-areas`, the `cobble-dataflow-area-need` command (decided by the user) and its file
   format (`area_need_file.py`, `area_need_cli.py`). The area machinery the fixpoint's own walk
   uses (`AreaTable` in `prepared_program`, `area_worklist`, `explain_request`) stays; whatever of it
   is left with no caller once narrowing is gone is deleted too. The out-dir
   stops recording a scope and the scope-switch check goes with it. Old narrowed out-dirs are not
   handled: no backward compatibility (decided by the user). `cobble-dataflow-fixpoint-diagnose`
   loses the same flags.
2. **The fixpoint writes what the trace wrote.** Its outputs gain what consumers used from dep rows
   and it lacks today: sink rows, and each synthetic source's origin and literal text on its
   `FLOWS_TO` edge (`FlowEdge` drops `Source.literal` today, and the origin is only recoverable by
   parsing the source field id). The `clamped` flag already rides on extent text as a `~` suffix, and
   definers already exist in `defs.jsonl`. Sinks go in a file of their own, `sinks.jsonl`, not as
   `FLOWS_TO` edges: combine reads every `FLOWS_TO` edge in `graph.jsonl` as a flow. A sink's
   definers come from the state after the statement's own writes, as the trace's `_sunk` takes them.
3. **Crossings come from combine.** There is no `via` in the fixpoint's output: a consumer that
   followed bytes across a call follows combine's `links.jsonl` windows instead, the way the
   partition graph already does with `--links`.
4. **Consumers move.** The partition graph builds its edges and terminals from the fixpoint's
   output (plus `links.jsonl`, the knowledge graph and `targets.jsonl`, as today). Dataset
   resolution finds file sites in the fixpoint's output. `cobble-trace-query` and
   `cobble-access-query` walk the fixpoint's provenance, crossing programs through `links.jsonl`.
5. **Deletions.** `cobble-fields-trace` (`trace.py`, `trace_report.py`), `call_targets.py` with the
   `targets` parameter of `commarea_aliases` (the fixpoint only ever passes the empty table),
   `cobble-viz-pathwalk` (`pathwalk_viz.py` and its template), their tests,
   their docs (`docs/reference/cobble/trace.md`, the pathwalk part of `viz.md`) and their Makefile
   lines. `aliases.py` stays: `build_corpus.py` uses it.
6. **Pipeline.** `make partition-traces` becomes parse, extents, `cobble-dataflow-fixpoint --all
   --sweeps $(PARTITION_SWEEPS)` (whole scope), combine; no area need, no per-member trace loop.
   `PARTITION_SWEEPS` is a Makefile variable the user sets; it has no default here and the user picks
   it.
7. **A capped run says so.** The existing "NOT SETTLED" report stays and is what a reader checks
   when a join looks wrong.

## Acceptance: the byte provenance matches

Decided by the user: the gate compares byte provenance, not the partition graph. Before fields-trace
is deleted, on CardDemo, every trace dep row is compared with the fixpoint's provenance rows:

- **Matched on:** program, node, source (extent, or the synthetic origin with its literal text), target
  (extent, or sink name).
- **Trace rows the fixpoint lacks** are the gate. Each is either fixed or listed with its reason as
  an accepted difference in the commit that switches the consumers. Expected reasons: a move whose
  subscript the trace resolved on its path and the fixpoint widened to the whole table, and rows a
  capped run had not reached (named by the "NOT SETTLED" report).
- **Fixpoint rows the trace lacks** are reported as counts, not gated: they are paths the trace
  never sampled.
- **Cross-program rows** (trace rows whose `via` or `source_program` is set) are compared against
  `links.jsonl` windows rather than fixpoint rows.

The comparison is a script the builder writes for the switch; it does not need to stay in the repo
once the trace is gone.

## Answers to the builder check

- **A call's write-back against a file site.** The fixpoint already credits a call's commarea or
  `BY REFERENCE` arguments to a `%CALL:<target>` synthetic source, and a file record read to
  `FILE:<name>`, so the two are told apart by the synthetic source's kind, not by `via`.
- **Following bytes across a call.** `links.jsonl` rows carry `caller`, `node`, `callee`,
  `caller_extent`, `callee_extent` and `returns`. A `LINK` return, which the trace handled with
  `source_program`, is the link bound back when `returns` is true, as the partition graph already
  does with `--links`.
- **Sinks at emission.** `sinks_of(statement, files)` takes only the statement and the FD-record to
  file map; it needs no reaching state. Emission calls it per statement node.
- **Dynamic call sites in the fixpoint.** Unchanged: the fixpoint writes `targets.jsonl` itself and
  a dynamic site stays a `%CALL:` source; the fixpoint takes no targets file. Pipeline order stays
  fixpoint, then combine.

Calls I made (the user can overrule):

- The queries' path-derived output (path counts, branch coverage, dead ends of callees not entered)
  goes, and their docs say so. `DeadEnd` and `Coverage` go with the trace.
- The only readers of trace files are the ones in the consumer table; `graph_cli.py`'s `--traces`
  becomes the fixpoint out-dir. `PARTITION_PATHS` goes with the trace loop.

## What the user accepted as trade-offs

- A capped run is a subset of the converged answer. Provenance from it is incomplete, never
  invented. A loop index whose value set was cut short can make a subscripted move look exact
  (`TAB(WS-I)` with `WS-I` seen as `{1}`), which can give unify a false join. This is rare and
  accepted as an engineering trade; the "NOT SETTLED" report is the trace back.
- The fixpoint merges paths, so a flow that only exists in one combination of branches is reported
  as possible where the trace might have shown it exactly on one path. Consumers already chain
  one-hop edges, so nothing they use depends on path combinations.
- The whole-scope run is the expensive step that remains; combine's tables grow with it.

## Left to the builder

- The exact shape of the new or extended rows: whether sinks and literal text extend `graph.jsonl`
  edges and `defs.jsonl`, or go in a new file. Keep consumers reading typed rows; prefer extending
  what exists if it stays one relation per file.
- How the queries' results are worded once they no longer come from paths.
- The order of commits. A sensible order: fixpoint emission first (with tests), then each consumer,
  then the scope and area-need deletions, then the trace and pathwalk deletions with docs and
  Makefile.
- Measuring cost: run CardDemo whole-scope with a few `--sweeps` values and record time and how
  many members settle, before and after, in the commit or an issue.
