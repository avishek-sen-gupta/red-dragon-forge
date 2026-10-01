# cobble: one tagged graph file instead of nodes.jsonl + edges.jsonl — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Read against `05d64af`.** That includes `50a144d`, in which the fixpoint stage takes
> `--asg-dir`/`--out-dir` instead of `--config`. Line numbers below are from that commit.

**Goal:** `cobble-build` writes one graph file named by a required `--output`. Every reader of
that graph, and `cobble-dataflow-fixpoint`'s graph half, move to the same single-file format.

**Architecture:** The file is JSONL, one row per line. Each row carries `"type": "node"` or
`"type": "edge"` alongside the fields it carries today. `GraphWriter` changes in place: it takes
one path, keeps one temp file, and renames it on close. Deduping and endpoint-node synthesis do
not change. Because an edge's endpoint nodes are always written before the edge itself, every
node row comes before the first edge row that names it. `export.read_graph(path)` is the one
reader. It replaces `read_ndjson(nodes, edges)`, which is deleted in its own commit once nothing
calls it.

**Tech Stack:** Python 3.13, pytest, networkx, argparse. Run everything through `uv run --no-sync`.

**Spec:** `docs/superpowers/specs/2026-10-01-cobble-single-graph-file-design.md`

## Global Constraints

- The row tag key is `"type"` and its values are `"node"` and `"edge"`. They come from
  `cobble.knowledge_graph.row_type`, and nothing spells them as literals.
- `--output` on `cobble-build` is required and has no default.
- No comments except one-line module/class headers. No `Any`, no `object` in new signatures.
  Frozen dataclasses. No loops that mutate.
- No test counts in living docs. `cobble/README.md` changes in the same commit as the
  behaviour it describes.
- The gate before every commit, from the worktree root:
  `make fmt && uv run pyright && uv run lint-imports && pre-commit run python-fp-lint-check --hook-stage manual --all-files`,
  then `cd cobble && uv run --no-sync python -m pytest`. cobble runs **without**
  `bridge-env.sh`.

## Review Focus

1. **A two-file-era file passed as `--graph`.** A user points a reader at an old
   `out/nodes.jsonl`. The read must fail on the first row with an error naming the missing
   `type` key, not render an empty graph. Pinned in Task 1.
2. **A crash during `cobble-build`.** Nothing is left at `--output`, only `<output>.tmp`, as
   today. Pinned in Task 2 (the file appears only after `close()`).
3. **`--output` in a directory that does not exist yet.** The parent is created, matching how
   `out_dir` is created today. Pinned in Task 2.
4. **The fixpoint query on a graph file.** Node rows must not reach `store_of` as flows.
   Pinned in Task 2.
5. **The XCTL→LINK relabel in `docs/presentation/capture/cobble.sh`.** It must keep node rows,
   or the callgraph reads a graph with no nodes. Checked by hand in Task 5. The script runs
   against the real corpus and has no test.

---

### Task 1: The tagged row and its reader

**Files:**
- Create: `cobble/cobble/knowledge_graph/row_type.py`
- Modify: `cobble/cobble/knowledge_graph/export.py` (add `read_graph`; leave `read_ndjson` until Task 6)
- Test: `cobble/tests/knowledge_graph/test_export.py`

**Interfaces:**
- Produces: `RowType(StrEnum)` with `NODE = "node"`, `EDGE = "edge"`; `ROW_TYPE_KEY = "type"`;
  `read_graph(path: Path) -> tuple[list[GraphNode], list[GraphEdge]]`.

- [ ] **Step 1: Write the failing tests** in `test_export.py`

```python
from cobble.knowledge_graph.export import read_graph
from cobble.knowledge_graph.row_type import ROW_TYPE_KEY, RowType


def _tagged_lines(path: Path) -> Path:
    rows = (
        {ROW_TYPE_KEY: RowType.NODE.value, "id": "COACTVW", "kind": "PROGRAM",
         "file_path": "app/cbl/COACTVW.cbl", "file_path_reason": None,
         "attrs": {"lang": "COBOL"}},
        {ROW_TYPE_KEY: RowType.NODE.value, "id": "COCOM01Y", "kind": "COPYBOOK",
         "file_path": None, "file_path_reason": "unresolved", "attrs": {}},
        {ROW_TYPE_KEY: RowType.EDGE.value, "source": "COACTVW", "source_kind": "PROGRAM",
         "target": "COCOM01Y", "target_kind": "COPYBOOK", "kind": "COPY",
         "attrs": {"line": 42}},
    )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_one_tagged_file_reads_back_as_its_nodes_and_its_edges(tmp_path: Path) -> None:
    nodes, edges = read_graph(_tagged_lines(tmp_path / "graph.jsonl"))

    assert nodes == [
        GraphNode(id="COACTVW", kind=NodeKind.PROGRAM,
                  location=Path("app/cbl/COACTVW.cbl"), attrs={"lang": "COBOL"}),
        GraphNode(id="COCOM01Y", kind=NodeKind.COPYBOOK,
                  location=NoFileLocation(FileLocationReason.UNRESOLVED), attrs={}),
    ]
    assert edges == [
        GraphEdge(source="COACTVW", source_kind=NodeKind.PROGRAM, target="COCOM01Y",
                  target_kind=NodeKind.COPYBOOK, kind=EdgeKind.COPY, attrs={"line": 42}),
    ]


def test_an_untagged_row_is_refused_rather_than_read_as_nothing(tmp_path: Path) -> None:
    old = tmp_path / "nodes.jsonl"
    old.write_text(json.dumps({"id": "A", "kind": "PROGRAM", "attrs": {}}) + "\n")

    with pytest.raises(KeyError, match=ROW_TYPE_KEY):
        read_graph(old)
```


- [ ] **Step 2: Run them to see them fail**

Run: `cd cobble && uv run --no-sync python -m pytest tests/knowledge_graph/test_export.py -v`
Expected: ImportError on `read_graph` / `row_type`.

- [ ] **Step 3: Implement**

`cobble/cobble/knowledge_graph/row_type.py`:

```python
"""Which half of the graph one line of a graph file holds."""

from enum import StrEnum

ROW_TYPE_KEY = "type"


class RowType(StrEnum):
    NODE = "node"
    EDGE = "edge"
```

In `export.py`, after `_rows`:

```python
def _row_type(row: Mapping[str, object]) -> RowType:
    return RowType(row[ROW_TYPE_KEY])


def read_graph(path: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Read (nodes, edges) back from one graph file, each row tagged with its half."""
    rows = tuple(_rows(path))
    return (
        [_node_from_json(row) for row in rows if _row_type(row) is RowType.NODE],
        [_edge_from_json(row) for row in rows if _row_type(row) is RowType.EDGE],
    )
```

- [ ] **Step 4: Run them to see them pass.** Same command. Expected: PASS.
- [ ] **Step 5: Mutation check.** Swap `NODE`/`EDGE` in one comprehension, then make `_row_type`
      use `row.get`. Both tests must fail. Revert.
- [ ] **Step 6: Gate and commit** — `feat(cobble): read a graph from one tagged JSONL file`

---

### Task 2: GraphWriter writes one file; cobble-build takes --output; the fixpoint follows

`GraphWriter`'s constructor changes, so both of its callers move in this commit.

**Files:**
- Modify: `cobble/cobble/knowledge_graph/graph_writer.py`
- Modify: `cobble/cobble/build_graph.py` (module docstring, `_out_paths` removed, `_extract_all`,
  `_report_merged`, `_parse_args`, `main`, the `_targets_path` docstring that cites `_out_paths`)
- Modify: `cobble/cobble/dataflow/fixpoint/build_corpus.py` (`NODES_FILE`/`EDGES_FILE` at
  130–131 → `GRAPH_FILE`; `_writer` at 682; the module docstring's file list at 24–31)
- Modify: `cobble/cobble/dataflow/fixpoint/query.py` (the `EDGES_FILE` import at 54, the `FieldStore`
  docstring at 218, `load` at 772–783)
- Modify: `cobble/README.md` (lines that describe `cobble-build`'s output and the fixpoint's file table)
- Test: `cobble/tests/knowledge_graph/test_graph_writer.py`, `cobble/tests/test_build_graph.py`,
  `cobble/tests/dataflow/fields/test_fields_build_corpus.py`,
  `cobble/tests/dataflow/fields/test_fields_crossing.py`

**Interfaces:**
- Consumes: `RowType`, `ROW_TYPE_KEY`, `read_graph` (Task 1).
- Produces: `GraphWriter(path: Path, corpus_index: CorpusIndex)`; `build_graph._parse_args(argv: Sequence[str]) -> argparse.Namespace`
  with `.config: Path`, `.output: Path`; `build_corpus.GRAPH_FILE = "graph.jsonl"`.

- [ ] **Step 1: Rewrite the writer tests to the one-path form.** In `test_graph_writer.py`, every
  `GraphWriter(nodes_path, edges_path, corpus_index)` becomes `GraphWriter(graph_path, corpus_index)`
  with `graph_path = tmp_path / "graph.jsonl"`. Replace `_read_jsonl(nodes_path)` with
  `_tagged(graph_path, RowType.NODE)`, and do the same for edges:

```python
def _tagged(path: Path, row_type: RowType) -> list[dict]:
    return [
        row for row in (json.loads(line) for line in path.read_text().splitlines())
        if row[ROW_TYPE_KEY] == row_type.value
    ]
```

Add one test for the ordering and atomic-rename behaviour:

```python
def test_an_edge_follows_its_endpoints_and_the_file_appears_only_on_close(
    tmp_path: Path,
) -> None:
    graph_path = tmp_path / "graph.jsonl"
    writer = GraphWriter(graph_path, _corpus_index_stub())
    writer.add_edge(
        GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                  target_kind=NodeKind.PROGRAM, kind=EdgeKind.CALL)
    )
    assert not graph_path.exists()
    writer.close()

    rows = [json.loads(line) for line in graph_path.read_text().splitlines()]
    assert [(row[ROW_TYPE_KEY], row.get("id", row.get("kind"))) for row in rows] == [
        ("node", "A"), ("node", "B"), ("edge", "CALL"),
    ]
    assert not graph_path.with_suffix(".jsonl.tmp").exists()
```

- [ ] **Step 2: Add the CLI test** to `test_build_graph.py`

```python
def test_the_graph_goes_where_output_says_and_output_is_required() -> None:
    args = _parse_args(["--config", "c.toml", "--output", "out/corpus.jsonl"])
    assert (args.config, args.output) == (Path("c.toml"), Path("out/corpus.jsonl"))

    with pytest.raises(SystemExit) as refused:
        _parse_args(["--config", "c.toml"])
    assert refused.value.code == 2
```

- [ ] **Step 3: Run them to see them fail.**
  `cd cobble && uv run --no-sync python -m pytest tests/knowledge_graph/test_graph_writer.py tests/test_build_graph.py -v`

- [ ] **Step 4: Implement the writer.** In `graph_writer.py`, replace the two temp files with one.
  Add the tag to both row dicts. Update the module docstring ("Both nodes and edges stream to
  one .jsonl file, each row tagged with its half…"):

```python
    def __init__(self, path: Path, corpus_index: CorpusIndex) -> None:
        self._corpus_index = corpus_index
        self._nodes_written = FirstSighting()
        self._edges_written = FirstSighting()
        self._tmp = path.with_suffix(path.suffix + ".tmp")
        self._path = path
        self._file = self._tmp.open("w")
```

  `add_node` writes `{ROW_TYPE_KEY: RowType.NODE.value, "id": …}`, and `add_edge` writes
  `{ROW_TYPE_KEY: RowType.EDGE.value, "source": …}`, both to `self._file`. `close()` becomes:

```python
    def close(self) -> None:
        self._file.close()
        self._tmp.rename(self._path)
```

- [ ] **Step 5: Implement cobble-build.** In `build_graph.py`:
  - Delete `_out_paths`.
  - `_parse_args(argv: Sequence[str])` adds
    `parser.add_argument("--output", required=True, type=Path, help="The graph file to write: one JSON line per node and per edge, tagged with which it is")`
    and returns `parser.parse_args(argv)`.
  - `_extract_all(config, output, corpus_index, csd, store)` keeps `ensure_dir(config.out_dir)`
    (`targets.jsonl` and the generated CSD still live there) and adds `ensure_parent(output)`
    from `cobble.path_utils`. It opens `GraphWriter(output, corpus_index)`.
  - `_corpus_failures(config, output)` passes `output` through.
  - `_report_merged(output)` does `merge_graph(*read_graph(output))` and logs `Wrote %s` once.
  - `main()` does `args = _parse_args(sys.argv[1:])`, then `load_corpus_config(args.config)`, then
    `_corpus_failures(config, args.output)` and `_report_merged(args.output)`.
  - Module docstring: "Writes the graph to --output as one JSONL file …"; and
    "Invoke as: … --config <path> --output <file>".

- [ ] **Step 6 (fixpoint): rewrite the fixpoint tests to the graph file.**
  In `cobble/tests/dataflow/fields/test_fields_build_corpus.py`:
  - Imports: `GRAPH_FILE` replaces `EDGES_FILE` (line 26) and `NODES_FILE` (line 28). Add
    `from cobble.knowledge_graph.row_type import ROW_TYPE_KEY, RowType`.
  - Next to the existing `_rows` (line 114), add the same `_tagged` helper as Step 1, typed for
    this file:

```python
def _tagged(path: Path, row_type: RowType) -> tuple[dict, ...]:
    return tuple(row for row in _rows(path) if row[ROW_TYPE_KEY] == row_type.value)
```

  - 161 and 474: `json.loads((out_dir / "edges.jsonl").read_text(...))` reads one edge. It
    becomes `(edge,) = _tagged(out_dir / GRAPH_FILE, RowType.EDGE)`. Keep the assertions after
    it as they are. Unpacking the 1-tuple also pins that there is exactly one edge, which the
    old single `json.loads` did implicitly.
  - 180: `_rows(out_dir / "edges.jsonl")` becomes `_tagged(out_dir / GRAPH_FILE, RowType.EDGE)`.
  - 232 (the byte-for-byte determinism check across `PYTHONHASHSEED`s): `EDGES_FILE` becomes
    `GRAPH_FILE`. The graph file now also carries the node rows, so this check covers node
    order too. Nodes are written on first sighting, in edge order, so the check should still
    pass. If it fails, the order really is non-deterministic: stop and report it, and do not
    exclude nodes from the check.
  - 246–250: build `nodes` from `_tagged(out_dir / GRAPH_FILE, RowType.NODE)` instead of
    splitting `nodes.jsonl`.
  - 259, 285, 423: the substring checks on `edges.jsonl` text become the same checks on
    `"".join(json.dumps(row) for row in _tagged(out_dir / GRAPH_FILE, RowType.EDGE))`. They
    stay substring checks, because "PROGB appears nowhere in the edges" is what they assert.
    Bind that string to a local `edges` where the test already has one (423).
  - 360: the docstring says "one shared edges.jsonl"; make it "one shared graph.jsonl".
  - 408: `_rows(out_dir / NODES_FILE)` becomes `_tagged(out_dir / GRAPH_FILE, RowType.NODE)`.
  - 453: `assert not (out_dir / "edges.jsonl").exists()` becomes `GRAPH_FILE`.
  - 700 and 911: `for name in (NODES_FILE, EDGES_FILE, EXTENTS_FILE, DEFS_FILE)` becomes
    `(GRAPH_FILE, EXTENTS_FILE, DEFS_FILE)`.

  In `cobble/tests/dataflow/fields/test_fields_crossing.py`, add `_written_graph` beside
  `_written` (line 972), and at 982, 996 and 1026 replace
  `_written(out, "edges.jsonl", _two_program_edge_rows())` with
  `_written_graph(out, _two_program_edge_rows())`. The node row names a field the edges
  already use, so a node row that leaked into `flows` would change the answers the tests
  already assert:

```python
def _written_graph(out, edge_rows) -> None:
    node = {ROW_TYPE_KEY: RowType.NODE.value, "id": "XPROGA.WS-AREA", "kind": "FIELD", "attrs": {}}
    edges = ({ROW_TYPE_KEY: RowType.EDGE.value, **row} for row in edge_rows)
    _written(out, GRAPH_FILE, (node, *edges))
```

  Before relying on the claim that a leaked node row would change the answers, check it in
  the Step 10 mutation check. If the answers do not move, add an assertion that does: e.g.
  `len(load(out).flows) == len(_two_program_edge_rows())`.

- [ ] **Step 7 (fixpoint): implement.**
  - `build_corpus.py` 130–131: replace both constants with `GRAPH_FILE = "graph.jsonl"`.
  - `_writer` (682) becomes
    `return GraphWriter(arguments.out_dir / GRAPH_FILE, locations)`.
  - Module docstring (24–31): "Six files" becomes "Five files". The `nodes.jsonl` and
    `edges.jsonl` entries become one entry:
    `graph.jsonl    the FIELD endpoints (no attributes) and one FLOWS_TO per (node, source extent, target extent), each row tagged node or edge`.
  - `query.py`: import `GRAPH_FILE` in place of `EDGES_FILE` (54), and
    `ROW_TYPE_KEY`, `RowType` from `cobble.knowledge_graph.row_type`. Add:

```python
def _edge_rows(graph: tuple[rows.Row, ...]) -> tuple[rows.Row, ...]:
    return tuple(row for row in graph if rows.text(row, ROW_TYPE_KEY) == RowType.EDGE)
```

    `load` (780) passes `_edge_rows(rows.read(out_dir / GRAPH_FILE))`. The `FieldStore`
    docstring (218) changes from "``nodes.jsonl`` is not read: every FIELD node it holds…" to
    "The graph file's node rows are not read: every FIELD node is an endpoint of some edge…".
  - Check `rg -n "rows\.read|def read" cobble/cobble/dataflow/fixpoint/rows.py` at execution
    time. `50a144d` changed `rows.py`, so confirm `read` still returns `tuple[Row, ...]` and
    `text` still exists before using them.

- [ ] **Step 8: README.** In `cobble/README.md`:
  - 57: `uv run cobble-build --config config/carddemo.toml --output out/carddemo.jsonl   # extract the graph -> out/carddemo.jsonl`.
  - 118: "`--config` is required by every stage but `cobble-compare`" stays true. Add that
    `cobble-build` also requires `--output`, the graph file it writes.
  - 466: "writes six files" becomes "writes five files".
  - 471–472: one row,
    `| `graph.jsonl` | `FIELD` endpoint, and `(node, source extent, target extent)` | node rows: nothing but the id; edge rows: the `FLOWS_TO` relation and `node`, the statement that moved the bytes. Each row's `type` says which |`.
  - 648: "one shared `edges.jsonl`" becomes "one shared `graph.jsonl`".
  - 657: "each of the six files" becomes "each of the five files".
  - Afterwards, `rg -n "nodes\.jsonl|edges\.jsonl|\{nodes,edges\}|six files" cobble/README.md`
    should match only the renderer, compare and callgraph lines (238, 894–905, 948),
    which Tasks 3–5 rewrite.

- [ ] **Step 9: Run the cobble suite.** `cd cobble && uv run --no-sync python -m pytest`.
  Expected: all pass. `read_ndjson` still exists, so the renderers and compare still compile.
  Until Tasks 3–5 land they will report that `nodes.jsonl` is not found.
- [ ] **Step 10: Mutation check.** Drop the tag from `add_edge`, then point `query.load` back at
  the unfiltered rows. The writer tests and a crossing test must fail. Revert.
- [ ] **Step 11: Gate and commit** — `feat(cobble): write the graph as one tagged file; cobble-build takes --output`

---

### Task 3: The renderers read --graph

**Files:**
- Modify: `cobble/cobble/render_graph.py`, `cobble/cobble/render_graph_webgl.py`
- Modify: `cobble/README.md` (45, 59, 218, 894–905, 946–948)
- Test: `cobble/tests/knowledge_graph/test_render.py`

**Interfaces:**
- Consumes: `read_graph` (Task 1), `GraphWriter(path, corpus_index)` (Task 2) to build fixtures.
- Produces: `render_graph._render(graph_path: Path) -> Path` (returns the HTML written, at
  `graph_path.with_suffix(".html")`); `render_graph_webgl._render(graph_path: Path) -> Path`
  (at `graph_path.with_name(f"{graph_path.stem}-webgl.html")`).

- [ ] **Step 1: Write the failing test** in `test_render.py`:

```python
def test_the_page_lands_beside_the_graph_and_is_titled_by_its_stem(tmp_path: Path) -> None:
    graph_path = tmp_path / "carddemo.jsonl"
    with GraphWriter(graph_path, _corpus_index_resolving_nothing()) as writer:
        writer.add_edge(
            GraphEdge(source="COACTVW", source_kind=NodeKind.PROGRAM, target="COCOM01Y",
                      target_kind=NodeKind.COPYBOOK, kind=EdgeKind.COPY)
        )

    written = render_graph._render(graph_path)

    assert written == tmp_path / "carddemo.html"
    assert "<title>carddemo Knowledge Graph</title>" in written.read_text()
```

`_corpus_index_resolving_nothing()` uses the same stub pattern as `test_graph_writer.py`'s
`_corpus_index_stub`. Move that helper into `cobble/tests/knowledge_graph/conftest.py` as a
plain function, so both test files import one copy. The title check is a substring because the
page is a whole HTML document. The title line is the one fact this test owns. Before writing
the assertion, check how `render_html` emits the title.

- [ ] **Step 2: Run it to see it fail.**
- [ ] **Step 3: Implement.** In both modules, `_parse_args(argv)` takes
  `--graph` (required, `type=Path`, help "The graph file cobble-build wrote") instead of `--config`.
  `main()` refuses a missing file with
  `logger.error("error: %s not found — run `cobble-build --output` first", args.graph)` and
  returns 1. Otherwise it calls `_render(args.graph)`. `_render` reads
  `merge_graph(*read_graph(graph_path))`, titles the page `f"{graph_path.stem} Knowledge Graph"`,
  and returns the path it wrote. Drop the now-unused `load_corpus_config` import. Rewrite both
  module docstrings to the new input and output.
- [ ] **Step 4: Run it to see it pass.** Then do the webgl smoke by hand:
  `uv run --no-sync cobble-render-webgl --graph <tmp graph>` (sfdp needed), expecting
  `<stem>-webgl.html`.
- [ ] **Step 5: Mutation check.** Write the HTML to `graph.html` in `graph_path.parent`. The test must fail.
- [ ] **Step 6: README.** Update every `cobble-render`/`cobble-render-webgl` invocation to `--graph out/carddemo.jsonl`
  and every output path to `out/carddemo.html` / `out/carddemo-webgl.html`.
- [ ] **Step 7: Gate and commit** — `feat(cobble): the renderers take --graph and write beside it`

---

### Task 4: cobble-compare reads --graph against one reference file

**Files:**
- Modify: `cobble/cobble/compare.py`
- Create: `cobble/reference/graph.jsonl` (converted from the two reference files)
- Delete: `cobble/reference/nodes.jsonl`, `cobble/reference/edges.jsonl`
- Modify: `cobble/README.md` (44, 58, and 118 — `cobble-compare` now takes `--graph`, so it is no longer the stage without arguments)
- Test: `cobble/tests/test_compare.py`

**Interfaces:**
- Consumes: `read_graph`, `GraphNode`, `GraphEdge`.
- Produces: `compare._node_key(node: GraphNode) -> tuple[str, str]`;
  `compare._edge_key(edge: GraphEdge) -> tuple[str, str, str, str, str]`;
  `compare._absent_inputs(reference: Path, graph: Path) -> tuple[Path, ...]`; `compare._parse_args(argv: Sequence[str])` (`--graph` required); `compare._run(args: argparse.Namespace) -> int`.

- [ ] **Step 1: Convert the reference.** Use a scratch script (scratchpad dir, `uv run --no-sync python <path>`).
  It reads `reference/nodes.jsonl`, then `reference/edges.jsonl`, adds the `type` tag to each
  row, and writes `reference/graph.jsonl` with nodes first. Then
  `git rm reference/nodes.jsonl reference/edges.jsonl`. Verify:
  `read_graph(Path("reference/graph.jsonl"))` yields 448 nodes and 832 edges, matching the
  `wc -l` of the deleted files.
- [ ] **Step 2: Rewrite the tests to the typed keys and the one file.**
  - `test_the_keys_are_the_documented_identities` builds a `GraphNode`/`GraphEdge` and asserts
    the same tuples.
  - `test_absent_inputs_names_both_sides` becomes
    `_absent_inputs(tmp_path / "reference" / "graph.jsonl", tmp_path / "out" / "x.jsonl")`, and
    asserts both paths come back in that order.
  - `test_an_unextracted_tree_names_the_command_that_extracts` writes an empty
    `reference/graph.jsonl`. It calls `_run(_parse_args(["--graph", str(tmp_path / "out" / "x.jsonl")]))`,
    expects 1, and asserts that `"cobble-build --config"` and `"--output"` both appear in the error.
- [ ] **Step 3: Run them to see them fail.**
- [ ] **Step 4: Implement.** `_REFERENCE = _REPO_ROOT / "reference" / "graph.jsonl"`.
  Use the same shape as `build_graph`: `_parse_args(argv: Sequence[str])` and `_run(args) -> int`.
  `main()` stays as `configure_cli_logging(); return _run(_parse_args(sys.argv[1:]))`. `_run`
  checks `_absent_inputs` first, then makes two direct reports in place of `_SETS`:

```python
    ref_nodes, ref_edges = read_graph(_REFERENCE)
    out_nodes, out_edges = read_graph(args.graph)
    diff = _report("NODES", set(map(_node_key, ref_nodes)), set(map(_node_key, out_nodes))) + _report(
        "EDGES", set(map(_edge_key, ref_edges)), set(map(_edge_key, out_edges))
    )
```

  `_node_key` / `_edge_key` take the typed objects and use `.kind.value` and friends. Delete
  `_load`. The module docstring and the "absent" error message name `--graph` and
  `cobble-build --config config/carddemo.toml --output out/carddemo.jsonl`.
- [ ] **Step 5: Run them to see them pass.**
- [ ] **Step 6: README** — `uv run cobble-compare --graph out/carddemo.jsonl   # identity-diff against reference/graph.jsonl (must be empty: 448/832)`.
- [ ] **Step 7: Gate and commit** — `feat(cobble): cobble-compare reads --graph against one reference file`

---

### Task 5: cobble-viz-callgraph reads --graph, typed

**Files:**
- Modify: `cobble/cobble/viz/callgraph_cmd.py`
- Modify: `docs/presentation/capture/cobble.sh`
- Modify: `cobble/README.md` (~238)
- Create: `cobble/tests/viz/test_callgraph.py`

**Interfaces:**
- Consumes: `read_graph`, `GraphEdge`, `EdgeKind`.
- Produces: `extract(graph_path: Path, target_programs: frozenset[str]) -> CallDepGraph` (signature unchanged except the name of its first parameter).

- [ ] **Step 1: Write the failing test.** Build the graph with `GraphWriter` in `tmp_path`: a `LINK`
  edge `A -> B` with `attrs={"paragraph": "P1", "commarea": "CA"}`, a `COPY` edge `A -> CPY`,
  and a `LINK` edge `B -> C`, where `C` is not a target program.

```python
def test_only_link_edges_between_target_programs_are_kept(tmp_path: Path) -> None:
    graph = extract(_graph(tmp_path), frozenset({"A", "B"}))

    assert graph == CallDepGraph(
        entry="A",
        nodes=(
            ProgramNode(program="A", calls=("B",), called_by=()),
            ProgramNode(program="B", calls=(), called_by=("A",)),
        ),
        edges=(CallEdge(from_program="A", to_program="B", paragraph="P1", commarea="CA"),),
    )
```

  This pins today's `LINK`-only filter. It does not fix forge-057 (XCTL/CALL are dropped);
  that stays its own issue.
- [ ] **Step 2: Run it to see it fail.** The current raw parse reads the file's node rows as
  edges with no `kind`, so the test may pass by accident before Step 3. If it does, break the
  `LINK` filter to confirm the test bites, then continue.
- [ ] **Step 3: Implement.** Replace `_RawEdge` with `GraphEdge`. `extract` reads `read_graph(graph_path)[1]`.
  `_valid_link` tests `edge.kind is EdgeKind.LINK` and reads `edge.attrs.get("commarea")`.
  `_extract_para` reads `edge.attrs.get("paragraph")` and `edge.source`. Both wrap the value in
  `str(...)` because `attrs` values are `AttrValue`. In `main`, `--edges` becomes `--graph`
  (help: "The graph file cobble-build wrote"). The module docstring's `Input:` line becomes
  `<file given to cobble-build --output>`.
  Split `main` into `_parse_args(argv)` and `_run(args) -> int`, as in Tasks 2–4; the entry
  point becomes `sys.exit(main())`. `_run` gets the renderers' missing-file refusal: if
  `args.graph` is not a file, it logs `"error: %s not found — run `cobble-build --output` first"`
  and returns 1. Pin that with a second test:
  `_run(_parse_args(["--graph", str(tmp_path / "absent.jsonl"), "--cfg", str(tmp_path / "cfg.json"), "--out", str(tmp_path / "out.json")])) == 1`.
- [ ] **Step 4: Run it to see it pass. Mutation check:** accept `EdgeKind.COPY`, then drop the
  target-program check. The test must fail both times.
- [ ] **Step 5: The capture script.** In `docs/presentation/capture/cobble.sh`:
  - build gets `--output out/carddemo.jsonl`
  - compare gets `--graph out/carddemo.jsonl`
  - render gets `--graph out/carddemo.jsonl` instead of `--config`, and its outputs are renamed
  - the stats block reads one file and splits rows on `type`
  - `callgraph_cmd --edges` becomes `--graph`
  - the XCTL→LINK relabel copies node rows through unchanged and relabels only edge rows with
    `kind == "XCTL"`

  Read the script through once afterwards (Review Focus 5). It needs the corpus and JARs to
  run, so it is not run here; say so in the handoff.
- [ ] **Step 6: README** — the `cobble-viz-callgraph` example (~238) uses `--graph out/carddemo.jsonl`.
- [ ] **Step 7: Gate and commit** — `feat(cobble): cobble-viz-callgraph reads --graph`

---

### Task 6: Remove the two-file reader and writer

`read_ndjson` has no caller after Tasks 3–5. `write_ndjson` never had a production caller; only
the round-trip tests used it.

**Files:**
- Modify: `cobble/cobble/knowledge_graph/export.py` (delete `read_ndjson`, `write_ndjson`,
  `_write_lines`, `_node_row`, `_edge_row`, `_kind_value`, `_location`, and any imports only they
  used; module docstring now describes the reader of one tagged file)
- Modify: `cobble/tests/knowledge_graph/test_export.py`

- [ ] **Step 1: Confirm no callers.**
  `rg -n "read_ndjson|write_ndjson" -g '!vendor' -g '!docs/superpowers' -g '!issues'` should list
  only `export.py` and `test_export.py`.
- [ ] **Step 2: Move the round-trip tests onto the real producer.** `_round_tripped` writes the
  sample through `GraphWriter(tmp_path / "graph.jsonl", stub)` (one `add_node` per node, one
  `add_edge` per edge) and reads it back with `read_graph`. Delete the per-file assertions that
  only made sense for two files (`test_write_ndjson_one_line_per_node_and_edge`). Keep every
  assertion about kinds, locations and attrs unchanged.
- [ ] **Step 3: Delete the functions.** Run `uv run pyright`, which will flag any import left orphaned.
- [ ] **Step 4: Run the cobble suite.** Expected: all pass.
- [ ] **Step 5: Final sweep.**
  `rg -n "nodes\.jsonl|edges\.jsonl" cobble/cobble cobble/README.md docs/presentation/capture`
  should match only `cobble/dataflow/depgraph/*`. That is depgraph's own pair of files, out of
  scope. `docs/presentation/artifacts/` are captured outputs from an earlier run, left as they
  are.
- [ ] **Step 6: Gate (with `make test-all`) and commit** — `refactor(cobble): drop the two-file graph reader and writer`
