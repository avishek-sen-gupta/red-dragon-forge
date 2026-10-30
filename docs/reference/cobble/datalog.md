# Datalog facts (experimental)

A cobble run written as [Soufflé](https://souffle-lang.github.io/) facts. A question is a `.dl` file
a machine writes; no cobble command runs Soufflé.

```text
cobble-experimental-datalog-facts --run RUN_DIR --out FACTS_DIR
```

Writes `FACTS_DIR/<relation>.facts` for every relation below (tab-separated, Soufflé's default;
a relation with no rows gets an empty file) and `FACTS_DIR/schema.dl`, which declares each
relation with `.decl` and `.input` inside an include guard, so a question may include it more
than once. Each relation is defined once, in
`cobble/experimental/datalog/`, and that definition writes both its facts file and its schema
line. Every artifact is read through its typed reader; nothing is guessed or parsed out of text.

A run missing an artifact the facts need, or holding none of the files a per-program directory
should (`srccfg/cfg-*.jsonl`, `accesses/*.jsonl`, `fixpoint/members/*/counts.json`), fails with exit
status 2, naming it, and writes nothing. `make carddemo-all` writes `$OUT/datalog/`.

## Encoding

- `symbol` for text, `number` for offsets, lengths, counts, levels and line numbers.
- Booleans are `yes` / `no`.
- `-` stands for an absent PERFORM resume or range end.
- Tabs, newlines and carriage returns inside text become spaces, so every line keeps its column
  count.
- Rows are de-duplicated and sorted.

## Relations

| relation | columns | from |
|---|---|---|
| `kg_node` | `id, kind` | `knowledge-graph.jsonl`. One id can name nodes of several kinds: a job and a DD both called `ACCTFILE` |
| `kg_edge` | `src, src_kind, kind, dst, dst_kind` | `knowledge-graph.jsonl`; each end named by id and kind. `PROGRAM` `READS`/`WRITES`/`UPDATES` `COBOL_FILE` by OPEN mode, the file's id its DD name; `PROGRAM` to `CICS_FILE` by CICS verb; `CICS_FILE` `DEFINES_DATASET` `DATASET` from the CSD; `STEP` `READS`/`WRITES`/`UPDATES` `DATASET` by the DD's DISP; `JOB`/`STEP` `JCL_STEP_RUNS`; `TRANSACTION` `STARTS` `PROGRAM`; `PROGRAM` `XCTL`/`XCTL_CANDIDATE`/`CALL` `PROGRAM`; `PROGRAM` `SENDS_MAP`/`RECEIVES_MAP` `BMS_MAP`; `PROGRAM` `COPY` `COPYBOOK` |
| `kg_edge_attr` | `src, src_kind, kind, dst, dst_kind, key, value` | the same edges' attributes, one row per scalar, a nested one keyed by its path (`fields.0.name`): `select_name` on a program-to-`COBOL_FILE` edge (the SELECT name the program opens that DD by), `ddname` and `disp` on a step-to-`DATASET` edge. Together they link a program's SELECT name to the dataset its step binds |
| `field_extent` | `fid, p, name, region, s:number, e:number` | `extents.jsonl`, each extent through `extent_text.byte_range` |
| `field_decl` | `fid, p, name, record, path, level:number, pic, usage, occurs:number, origin` | `extents.jsonl`, one per declared cell; `path` joined with `.` |
| `field_value` | `fid, v` | `extents.jsonl`, cells with a `VALUE` |
| `field_redefines` | `fid, target` | `extents.jsonl`, cells that `REDEFINE` |
| `program` | `p, where` (`internal` / `external`) | `srccfg/cfg-*.jsonl` program rows |
| `cfg_entry` | `p, n` | the program row's `entry`: the first paragraph's label, `%EXTERNAL#label` for an external program; none for a program with no paragraphs |
| `cfg_node` | `p, n, kind, para, line:number, transfer` | CFG node rows |
| `cfg_edge` | `p, a, b, kind` | CFG edge rows |
| `cfg_pred` | `p, n, l, op, r, text, resolved` | `TEST` nodes' atoms |
| `cfg_write` / `cfg_read` | `p, n, f` | node `writes` / `reads` |
| `cfg_target` | `p, n, t, resolved` | nodes with a jump or call target |
| `cfg_file` | `p, n, f` | nodes naming a file |
| `cfg_perform` | `p, s, resume, rend` | `PERFORM` nodes |
| `cfg_call` | `caller, n, transfer, callee, entry, resolved, expr, certain` | CFG call rows |
| `cfg_call_reason` | `caller, n, why` | CFG call rows' `reasons` |
| `access` | `p, n, f, region, s:number, e:number` | `accesses/*.jsonl`, the row's `node` |
| `fp_counts` | `p, settled, writes, covered, unhandled, unmodelled, dynamic, files` (numbers after `settled`) | `fixpoint/members/*/counts.json` |
| `fp_dead_end` / `fp_unresolved` | `p, why` | the same, `dead_ends` / `unresolved_reasons` |
| `fp_use` | `p, n, ext` | `fixpoint/defs.jsonl` |
| `fp_def` / `fp_def_value` / `fp_def_reason` | `p, n, ext, definer` / `v` / `why` | the same |
| `fp_sink` | `p, n, skind, sname, ext` | `fixpoint/sinks.jsonl`: at node `n`, `p` writes the bytes `ext` to a sink of kind `skind` (`FILE`, `MAP`, `TD_QUEUE`). `sname` is the operand as written: a batch SELECT name, or a CICS field such as `LIT-ACCTFILENAME` whose `field_value` is the file |
| `fp_sink_definer` | `p, n, skind, sname, definer` | the same |
| `fp_flow` | `src, dst, n, okind, oname, sext, dext` | `fixpoint/graph.jsonl` edges: at node `n`, bytes `sext` of `src` reach bytes `dext` of `dst`. `okind`/`oname` name the origin when `src` is one (`FILE`, `MAP`, `LITERAL`, `CALL`, …, e.g. `PROG.FILE:CUSTFILE`), `NONE` when `src` is a field |
| `link` | `caller, n, transfer, callee, cext, eext, returns, why` (`ok` when linked) | `combine/links.jsonl` and `fixpoint/aliases.jsonl` |
| `target_site` | `caller, n, kind, transfer, expr` | `combine/targets.jsonl` |
| `target` | `caller, n, kind, transfer, expr, cand` | the same, one per candidate |
| `target_reason` | `caller, n, why` | the same |
| `jump` | `p, n, kind, returns` | `fixpoint/jumps.jsonl` |
| `jump_target_value` / `jump_target_reason` | `p, n, v` / `why` | the same, the target operand |
| `slot` | `id, kind, p, record, field, off:number, size:number` | partition `graph.jsonl` nodes. `kind` is `field` (id `P:RECORD.FIELD`), `dataset` (id `DSN[s:e]`, a byte range of one dataset, `record` its DSN, `p` empty), `origin` or `sink` |
| `origin` | `id, p, kind, name` | partition origin nodes, the typed origin |
| `slot_edge` | `src, dst, certainty, cross, barrier` | partition edges: origin to field, field to field, field to sink, and dataset to field (a read) or field to dataset (a write), the dataset resolved through the CSD or the step's DD. A field-to-dataset edge is how a program's record reaches the real dataset. `cross` is `yes` when the edge joins two programs or a program and a dataset; `certainty` is `exact`, or `possible` on a dataset edge with doubt; `barrier` names the barrier in force (`fanout-8` on every edge), not whether it blocked this edge, which is not exported |
| `slot_align` | `src, dst, so:number, to:number, len:number` | partition edges' alignments: `len` bytes at offset `so` of `src` land at offset `to` of `dst`; an edge with none is whole-field |
| `dep_edge` | `src, dst, p, seq:number, verb` | `depgraph/edges.jsonl` |
| `cluster` | `c, member` (`c0`, `c1`, … in file order) | `aggregates/unified.jsonl` |

## Running a question

```text
souffle --include-dir FACTS_DIR -F FACTS_DIR -D OUT_DIR question.dl
```

`question.dl` holds `#include "schema.dl"`, its rules, and `.output` lines for the relations it wants
back.
