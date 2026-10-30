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
| `kg_node` | `id, kind` | `knowledge-graph.jsonl` |
| `kg_edge` | `src, kind, dst` | `knowledge-graph.jsonl` |
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
| `fp_sink` | `p, n, skind, sname, ext` | `fixpoint/sinks.jsonl`, the typed sink |
| `fp_sink_definer` | `p, n, skind, sname, definer` | the same |
| `fp_flow` | `src, dst, n, okind, oname, sext, dext` | `fixpoint/graph.jsonl` edges, the typed origin |
| `link` | `caller, n, transfer, callee, cext, eext, returns, why` (`ok` when linked) | `combine/links.jsonl` and `fixpoint/aliases.jsonl` |
| `target_site` | `caller, n, kind, transfer, expr` | `combine/targets.jsonl` |
| `target` | `caller, n, kind, transfer, expr, cand` | the same, one per candidate |
| `target_reason` | `caller, n, why` | the same |
| `jump` | `p, n, kind, returns` | `fixpoint/jumps.jsonl` |
| `jump_target_value` / `jump_target_reason` | `p, n, v` / `why` | the same, the target operand |
| `slot` | `id, kind, p, record, field, off:number, size:number` | partition `graph.jsonl` nodes |
| `origin` | `id, p, kind, name` | partition origin nodes, the typed origin |
| `slot_edge` | `src, dst, certainty, cross, barrier` (`none` when there is none) | partition edges |
| `slot_align` | `src, dst, so:number, to:number, len:number` | partition edges' alignments; an edge with none is whole-field |
| `dep_edge` | `src, dst, p, seq:number, verb` | `depgraph/edges.jsonl` |
| `cluster` | `c, member` (`c0`, `c1`, … in file order) | `aggregates/unified.jsonl` |

## Running a question

```text
souffle --include-dir FACTS_DIR -F FACTS_DIR -D OUT_DIR question.dl
```

`question.dl` holds `#include "schema.dl"`, its rules, and `.output` lines for the relations it wants
back.
