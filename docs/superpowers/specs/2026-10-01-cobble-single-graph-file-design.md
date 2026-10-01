# cobble: one tagged graph file instead of nodes.jsonl + edges.jsonl — Design

**Date:** 2026-10-01
**Status:** proposed
**Read against:** `05d64af`
**Plan:** `docs/superpowers/plans/2026-10-01-cobble-single-graph-file.md`

## Goal

`cobble-build` writes its knowledge graph to **one file**, named by a required `--output`, instead
of `<out_dir>/nodes.jsonl` + `<out_dir>/edges.jsonl`. Every tool that reads that graph moves to
the single file. `cobble-dataflow-fixpoint` writes through the same `GraphWriter`, so its graph
half moves to the same single file too. It keeps its other files.

Success means four things:
- A full `cobble-build` → `cobble-compare` → `cobble-render` run on CardDemo uses one graph file.
- The identity diff against the committed reference is still empty (448 nodes, 832 edges).
- No production code reads or writes a `nodes.jsonl`/`edges.jsonl` pair, except
  `cobble-depgraph` (see Out of scope).
- The fixpoint query answers exactly as before.

## The format

JSONL: one JSON object per line, UTF-8, `\n`-terminated. Every row carries a `type` key whose
value is `"node"` or `"edge"`. The rest of a row is exactly what that half's file holds today.

```
{"type": "node", "id": "COACTVW", "kind": "PROGRAM", "file_path": "app/cbl/COACTVW.cbl", "file_path_reason": null, "attrs": {}}
{"type": "node", "id": "COCOM01Y", "kind": "COPYBOOK", "file_path": null, "file_path_reason": "unresolved", "attrs": {}}
{"type": "edge", "source": "COACTVW", "source_kind": "PROGRAM", "target": "COCOM01Y", "target_kind": "COPYBOOK", "kind": "COPY", "attrs": {"line": 42}}
```

- **Ordering.** Rows stream in the order the writer first sees them, so nodes and edges are
  interleaved. `GraphWriter.add_edge` writes both endpoint nodes before the edge itself. So
  every node row comes before the first edge row that names it, and a reader can resolve
  endpoints in one pass. Readers are not required to rely on this; `read_graph` partitions by
  `type`.
- **Dedupe.** Unchanged. Nodes dedupe on `(kind, id)` and edges on `_edge_key`, keep-first, and
  each kind of row dedupes on its own.
- **Atomicity.** Unchanged. The writer streams to `<path>.tmp` and renames it to `<path>` on
  close. After a crash `<path>` is absent, never truncated.
- **An untagged row is an error.** If a reader is handed a two-file-era `nodes.jsonl`, it fails
  on the first row with an error naming the missing `type` key. It never returns an empty or
  partial graph.
- **Tag values live in one place.** `cobble.knowledge_graph.row_type` holds the `RowType` enum
  (`NODE`, `EDGE`) and the `ROW_TYPE_KEY` constant. No other code spells `"type"`, `"node"` or
  `"edge"` as literals.

## Approaches considered

1. **One JSONL file, tagged rows. Chosen.** `GraphWriter` keeps one stream and never buffers,
   and the file stays line-oriented. The cost is that a reader filters by `type`.
2. **One JSON document, `{"nodes": [...], "edges": [...]}`.** A single Pydantic model could
   read it in one call. But the writer would have to buffer the whole graph, or write two temp
   streams and stitch them on close. That costs memory on the fixpoint's corpus-scale output,
   and streaming is the reason `GraphWriter` exists.
3. **A second writer for `cobble-build`, leaving `GraphWriter` two-file for the fixpoint.**
   Rejected. The format fits the fixpoint as well, and its graph half moving to one file is
   part of the goal. Two writers would mean two dedupe paths to keep in step. A single writer
   with a one-path/two-path switch is also rejected: it is a configuration knob with no caller
   that needs both.

## Components

### Writer: `cobble/knowledge_graph/graph_writer.py`

`GraphWriter(path: Path, corpus_index: CorpusIndex)`. It has one temp file and one rename, and
each row is tagged. `add_node`, `add_edge`, `add_all` and the context-manager protocol are
unchanged, so it still satisfies cicada's `GraphSink` structurally.

### Reader: `cobble/knowledge_graph/export.py`

`read_graph(path: Path) -> tuple[list[GraphNode], list[GraphEdge]]` is the one reader. The
two-file `read_ndjson(nodes, edges)` is removed once it has no callers. `write_ndjson` is removed
too: its only callers were tests, and the round-trip tests move onto `GraphWriter` → `read_graph`,
the real producer and consumer pair.

### CLI contract

| Command | Before | After |
|---|---|---|
| `cobble-build` | `--config` → `<out_dir>/{nodes,edges}.jsonl` | `--config <toml> --output <file>`. Both are required, with no default for `--output`. Its parent directory is created if absent. |
| `cobble-render` | `--config` → `<out_dir>/graph.html` | `--graph <file>`. Writes `<file stem>.html` beside the graph, titled `"<stem> Knowledge Graph"`. No config. |
| `cobble-render-webgl` | `--config` → `<out_dir>/graph-webgl.html` | `--graph <file>`. Writes `<file stem>-webgl.html` beside the graph. No config. |
| `cobble-compare` | no arguments; `out/{nodes,edges}.jsonl` vs `reference/{nodes,edges}.jsonl` | `--graph <file>` vs `cobble/reference/graph.jsonl` |
| `cobble-viz-callgraph` | `--edges <out_dir>/edges.jsonl --cfg … --out …` | `--graph <file> --cfg … --out …` |

A reader whose `--graph` file does not exist exits 1, with a message that names the file and
`cobble-build --output`. That is the same behaviour as today's missing-pair check.

`cobble-build` keeps `--config`, and `out_dir` keeps its other jobs. The generated CSD is
written there. `targets.jsonl` is read from there to enrich dynamic call sites. Only the graph's
location moves to `--output`.

The two renderers name their output from the graph's stem, not the config's. With
`--output out/carddemo.jsonl`, the pages are `out/carddemo.html` and `out/carddemo-webgl.html`.

### cobble-viz-callgraph reads typed edges

`extract` reads `read_graph(path)` and filters `GraphEdge`s on `EdgeKind.LINK`, instead of
indexing raw JSON dicts. The filter itself is unchanged; see Out of scope.

### The committed reference

`cobble/reference/nodes.jsonl` (448 rows) and `cobble/reference/edges.jsonl` (832 rows) are
converted once, by a script that is not kept. The result is `cobble/reference/graph.jsonl`:
the node rows first, then the edge rows, each tagged. The two old files are deleted. The
conversion only adds the tag; it changes no other field and no row's identity.

### The fixpoint (`cobble-dataflow-fixpoint`)

Its outputs go from six files to five:

| file | change |
|---|---|
| `graph.jsonl` | **new.** It replaces `nodes.jsonl` + `edges.jsonl`: FIELD endpoint rows and FLOWS_TO edge rows, tagged. |
| `extents.jsonl`, `defs.jsonl`, `aliases.jsonl`, `targets.jsonl` | unchanged |

The name is a module constant, `build_corpus.GRAPH_FILE = "graph.jsonl"`, in `--out-dir`. The
stage does not take `--output`: its output is a directory, and the graph file is one table in it.

`query.load(out_dir)` reads the edge rows of `graph.jsonl` and ignores the node rows. It already
ignored `nodes.jsonl`, because every FIELD node is an edge endpoint. Query answers do not change.

The determinism test compares output bytes across `PYTHONHASHSEED`s. It now covers node order as
well as edge order. Node rows are written on first sighting in edge order, so this is expected to
hold. If it does not, that is a real non-determinism to fix, not to exclude from the test.

## Consumer inventory

Every reader of the two files, found by search at `05d64af`:

| Consumer | Today | Change |
|---|---|---|
| `build_graph._report_merged` | reads its own pair back to tally edge kinds | `read_graph(output)` |
| `render_graph.py`, `render_graph_webgl.py` | `read_ndjson` on `<out_dir>` | `--graph`, `read_graph` |
| `compare.py` | raw JSON from `out/` and `reference/` | `--graph`, `read_graph`, typed keys |
| `viz/callgraph_cmd.py` | raw JSON from `--edges` | `--graph`, `read_graph`, typed edges |
| `dataflow/fixpoint/query.py` | `rows.read(EDGES_FILE)` | edge rows of `GRAPH_FILE` |
| `docs/presentation/capture/cobble.sh` | build, compare and render invocations; a stats block reading both files; an XCTL→LINK relabel of `edges.jsonl` | every invocation moves to the new flags; the stats block splits on `type`; the relabel passes node rows through and relabels only XCTL edge rows |
| `cobble/README.md` | invocations, outputs, the fixpoint's file table | updated with each change, in the same commit |

Nothing outside `cobble/` reads these files. `red_dragon_forge`, cicada, squall and jackal have
no reference to them.

## Testing

Each behaviour gets one test that asserts everything the behaviour implies. Tests are unit
tests with no corpus, under `cobble/tests/`.

- **Reader.** A tagged file reads back as exactly its nodes and edges, by equality. An untagged
  row raises an error naming `type`.
- **Writer.** Every existing writer test is moved to the one-path form. A new test pins that the
  endpoint node rows come before the edge row, and that the file appears only on close.
- **`cobble-build` CLI.** `--output` is parsed to a `Path`, and omitting it exits 2.
- **Renderer.** The HTML lands beside the graph, named and titled from its stem. The WebGL
  renderer needs sfdp, so it is smoke-run by hand.
- **Compare.** Typed identity keys. Absent inputs are named. A missing `--graph` file names
  `cobble-build --output`.
- **Callgraph.** This command has no tests today; it gets its first. Only LINK edges between
  target programs are kept, checked by equality on the whole `CallDepGraph`.
- **Fixpoint.** The existing build-corpus and crossing tests are moved to `graph.jsonl`. The
  crossing fixtures include a node row, which proves the query skips node rows.

Each new test is mutation-checked: break the code it covers in its two most obvious ways and
confirm the test fails.

What no test here covers: a real CardDemo `cobble-build` + `cobble-compare` run. It needs the
JARs and the corpus. It is run by hand before the last commit, and its result is reported as
it is.

## Out of scope

- **`cobble-depgraph`'s own `nodes.jsonl`/`edges.jsonl`/`pairs.json`.** These are a different
  graph from a different stage, with a different row shape, and are not written by
  `GraphWriter`.
- **forge-057.** `cobble-viz-callgraph` keeps only LINK edges, so XCTL/CALL hand-offs are
  dropped. This change keeps that filter as it is, and its new test pins today's behaviour.
- **`docs/presentation/artifacts/`.** These are outputs captured from an earlier run.
  Re-capturing is a separate step.
- **A Pydantic model per row.** The reader keeps `export.py`'s existing hand-narrowing
  (`_node_from_json`, `_edge_from_json`), which this change does not alter.
