# Partition render: program map and per-program pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cobble-experimental-partition-render` finishes on a corpus of thousands of programs, writing a program map and one page per program's neighbourhood.

**Architecture:** The graph's node and edge records become slotted dataclasses so the one streaming read stays near the file's size. A `GraphIndex` built once in a single pass gives each program's neighbourhood without whole-graph scans. Each neighbourhood is drawn by today's page code, whose per-slot scans become per-node indexes. A new map page draws programs and dataset records.

**Tech Stack:** Python 3.13, Pydantic (dataclass validation), networkx, numpy, sigma.js/graphology (vendored), Playwright for page checks.

**Spec:** `docs/superpowers/specs/2026-10-27-partition-render-neighbourhoods-design.md`

## Global Constraints

- All code under `cobble/cobble/experimental/partition/`; tests under `cobble/tests/experimental/partition/`.
- Frozen dataclasses, no comments beyond one-line module/class headers, pyright strict, python-fp-lint (no loop mutation, complexity ≤ 3).
- Log lines use the stage prefix `partition render` (the `RENDER` constant in `tally.py`).
- The commit hooks are the gate; run only targeted tests while working. Never `--no-verify`.
- No client identifiers anywhere; CardDemo names are fine.
- `docs/reference/cobble/partition.md` and the Makefile change in the commit that changes the CLI.

## Review Focus

- A program with no fields of its own, only origins or sinks: its page is still written, with those nodes.
- A dataset slot linked to one program only: that program's map edge to the dataset record still exists.
- Two programs linked only through a slot: each one's neighbourhood holds the other's linked field, and the map holds no direct program–program edge for it.
- A program name containing `#` or `$` (legal in COBOL): the map's link percent-encodes it so the page opens.
- Rerunning into an existing `--out` directory overwrites every file.

---

### Task 1: Slim graph records and a streaming read

**Files:**
- Modify: `cobble/cobble/experimental/partition/graph_node.py`, `graph_edge.py` — `BaseModel` → `@dataclass(frozen=True, slots=True)` with `__pydantic_config__ = ConfigDict(extra="forbid")`, as `aggregates/byte_node.py` does.
- Modify: `cobble/cobble/experimental/partition/fold.py:55,65` and `cobble/cobble/experimental/aggregates/exact_merge.py:55` — `model_copy(update=...)` → `dataclasses.replace` (only where the copied object is a `GraphNode`/`GraphEdge`).
- Modify: `cobble/cobble/experimental/partition/graph_file.py` — `read_graph` counts lines, then streams with `counted(..., tenths(RENDER, "graph lines read", total), total)`, interning ids, program, record, barrier and reasons with `sys.intern` (pattern: `aggregates/byte_graph_file.py`).
- Test: `cobble/tests/experimental/partition/test_graph_file.py` (create if absent; extend if present).

**Interfaces:**
- Produces: `GraphNode`, `GraphEdge` (same fields, same constructors); `read_graph(path: Path) -> FieldGraph` unchanged signature.

- [ ] **Step 1: Write the failing test** `test_read_graph_reads_back_what_write_graph_wrote_logging_every_tenth`: write `SPREAD_OUT`-like graph (10 nodes, 10 edges, 20 lines) with `write_graph`, read it with `read_graph` under `caplog`; assert `read == graph`, `type(read.nodes[0]).__slots__` exists (`hasattr(read.nodes[0], "__slots__")` is `True` and `hasattr(read.nodes[0], "__dict__")` is `False`), and the logged messages equal `["partition render: graph lines read 2/20", "... 4/20", ..., "partition render: graph lines read 20/20", "partition render: graph lines read 20/20 done"]` (exact list from `tenths`' behaviour; read `tally.py` for the format).
- [ ] **Step 2: Run** `cd cobble && uv run --no-sync pytest tests/experimental/partition/test_graph_file.py -q` — Expected: FAIL on `__dict__`/logging.
- [ ] **Step 3: Implement** the record and reader changes above.
- [ ] **Step 4: Run** `uv run --no-sync pytest tests/experimental/partition tests/experimental/aggregates -q` — Expected: PASS.
- [ ] **Step 5: Measure** with a scratchpad script: `tracemalloc` around `read_graph` on CardDemo's `graph.jsonl` (13 MB). Before: 70 MB, 1,322 bytes per item. Record the after figure in the commit message.
- [ ] **Step 6: Commit** `perf(cobble): partition graph records are slotted dataclasses, read streamed with progress`.

### Task 2: Layout without whole-graph scans

**Files:**
- Modify: `cobble/cobble/experimental/partition/layout.py`.
- Test: `cobble/tests/experimental/partition/test_partition_render.py` (existing layout tests are the output guard).

**Interfaces:**
- Produces: `layout(graph: FieldGraph) -> dict[str, tuple[float, float]]`, output identical to today.

- [ ] **Step 1: Pin today's output.** No new test: there is no injection point to count scans, and the output must not change. Save `layout(SPREAD_OUT)` and `layout(read_graph(CardDemo graph.jsonl))` to a scratchpad pickle before editing. The existing tests `test_linked_fields_sit_closer_together_than_a_field_nothing_links` and `test_each_program_keeps_to_its_own_region_and_slots_sit_among_their_fields` stay the committed guard.
- [ ] **Step 2: Implement** one pass building `ends: dict[str, tuple[str, ...]]` (node → neighbouring node ids, both directions) and `members: dict[str, tuple[str, ...]]` (program → node ids, via `itertools.groupby` on the sorted owned pairs). `_programs` uses groupby; `_local` takes the program's members and builds its edges from `ends` restricted to members; `_ties`' "through" and `_among` read `ends[slot]`.
- [ ] **Step 3: Run** `uv run --no-sync pytest tests/experimental/partition/test_partition_render.py -q` and the scratchpad equality check on `SPREAD_OUT` and CardDemo's graph — Expected: PASS, points identical (exact float equality).
- [ ] **Step 4: Time** `layout` on CardDemo's graph before/after; record both in the commit message.
- [ ] **Step 5: Commit** `perf(cobble): partition layout indexes edges by node instead of scanning them per slot and program`.

### Task 3: Graph index and neighbourhoods

**Files:**
- Create: `cobble/cobble/experimental/partition/graph_index.py` (`GraphIndex` frozen dataclass + `graph_index`), `neighbourhood.py` (`neighbourhood`).
- Test: `cobble/tests/experimental/partition/test_neighbourhood.py`.

**Interfaces:**
- Produces:
  - `GraphIndex(nodes: Mapping[str, GraphNode], touching: Mapping[str, tuple[GraphEdge, ...]], programs: Mapping[str, tuple[str, ...]])` — `touching[id]` every edge with `id` as an end; `programs[name]` the ids of every non-dataset node of that program, sorted; built in one pass each.
  - `graph_index(graph: FieldGraph) -> GraphIndex`
  - `neighbourhood(index: GraphIndex, program: str) -> FieldGraph` — nodes per the spec's three rules, in id order; edges: every edge in `touching` of a kept node whose both ends are kept, each once, in (source, target) order.

- [ ] **Step 1: Write the failing test** `test_a_program_s_neighbourhood_is_its_nodes_their_neighbours_and_every_reader_and_writer_of_a_slot_it_reaches`, on `SPREAD_OUT` (import it from `test_partition_render`, or move it to a shared `graphs.py` test module if importing a test module trips the linter) extended with an edge `Q:REC.B → S:REC.A`. Assert exact node-id tuples:
  - `P`: every `P:` node, `P|sink|MAP:M`, `DS[0:4]`, `Q:REC.A`.
  - `Q`: every `Q:` node, `DS[0:4]`, `P:REC.A`, `S:REC.A`.
  - `S`: `S:REC.A`, `S:REC.B`, `Q:REC.B`.
  - and the edge pairs of `P`'s neighbourhood: its four internal chains, its three sink edges, `P:REC.A→DS[0:4]`, `DS[0:4]→Q:REC.A`.
- [ ] **Step 2: Run** `uv run --no-sync pytest tests/experimental/partition/test_neighbourhood.py -q` — Expected: FAIL, import error.
- [ ] **Step 3: Implement** `graph_index` and `neighbourhood`.
- [ ] **Step 4: Run** the test — Expected: PASS. Mutation-check: drop rule 3 (slot readers) and confirm `P` loses `Q:REC.A`; drop the both-ends filter and confirm extra edges appear.
- [ ] **Step 5: Commit** `feat(cobble): a partition graph index and each program's neighbourhood`.

### Task 4: The program map

**Files:**
- Create: `cobble/cobble/experimental/partition/program_map.py` (`MapNode`, `MapEdge`, `MapData` Pydantic models in their own files per one-class-per-file: `map_node.py`, `map_edge.py`, `map_data.py`), `program_map.html` (template, same `/*SCRIPTS*/` and `/*DATA*/` markers as `partition_page.html`).
- Test: `cobble/tests/experimental/partition/test_program_map.py`; extend `page_driver.py` with `drive_map(path: Path) -> MapReport` (`map_report.py`, frozen dataclass).

**Interfaces:**
- Consumes: `GraphIndex` from Task 3.
- Produces:
  - `MapNode(id: str, kind: Literal["program", "dataset"] as an enum MapKind in map_kind.py, label: str, x: float, y: float, fields: int, href: str)` — `href` is `programs/<percent-encoded id>.html` for a program, `""` for a dataset.
  - `MapEdge(source: str, target: str, links: int)` — undirected, `source < target`.
  - `program_map(index: GraphIndex) -> MapData` — a program node per `index.programs` key, a dataset node per distinct `record` of dataset nodes; an edge per pair of different groups linked by ≥ 1 graph edge (a node's group: its program, or its record for a slot), `links` = number of graph edges; laid out by `nx.spring_layout(seed=LAYOUT_SEED, weight="weight")`.
  - `map_page(data: MapData, sources: Sequence[str]) -> str`.

- [ ] **Step 1: Write the failing tests**
  - `test_the_map_has_one_node_per_program_and_dataset_record_and_an_edge_per_linked_pair`: on `SPREAD_OUT` plus `Q:REC.B → S:REC.A`; assert `[(n.id, n.kind, n.fields, n.href) for n in nodes]` is `[("DS", dataset, 1, ""), ("P", program, 9, "programs/P.html"), ("Q", program, 6, "programs/Q.html"), ("S", program, 2, "programs/S.html")]` (`fields`: node count of the group) and edges `[("DS", "P", 1), ("DS", "Q", 1), ("Q", "S", 1)]`; a program named `A#B` gets href `programs/A%23B.html`.
  - `test_the_map_page_loads_and_each_program_links_to_its_page` (Playwright via `drive_map`): `MapReport(errors=(), nodes=4, edges=3, hrefs=("programs/P.html", "programs/Q.html", "programs/S.html"), searched="Q")` — searching `Q` and pressing Enter highlights node `Q`.
- [ ] **Step 2: Run** `uv run --no-sync pytest tests/experimental/partition/test_program_map.py -q` — Expected: FAIL, import error.
- [ ] **Step 3: Implement** the models, `program_map`, `map_page` and the template: sigma graph, node size by `fields`, edge size by `log(links)`, click on a program sets `location.href = node.href`, hover shows label and neighbours, a search box that centres on the matched node.
- [ ] **Step 4: Run** the tests — Expected: PASS. Mutation-check: count edges per pair once instead of per graph edge (links all 1 → still passes here, so also assert a pair with 2 graph edges gives `links=2` by adding `P:REC.B→DS[0:4]` in the first test).
- [ ] **Step 5: Commit** `feat(cobble): a program map page of the partition graph`.

### Task 5: The render writes a directory

**Files:**
- Modify: `cobble/cobble/experimental/partition/page.py` — `page(graph, sources: Sequence[str])` emits `<script src="...">` tags; `partition_page.html` unchanged apart from that.
- Modify: `cobble/cobble/experimental/partition/render_cli.py` — `--out` is a directory; writes `scripts/graphology.umd.min.js`, `scripts/sigma.min.js`, `index.html` (`map_page(program_map(index), ("scripts/graphology.umd.min.js", "scripts/sigma.min.js"))`) and `programs/<id>.html` per program (`page(neighbourhood(index, name), ("../scripts/…", "../scripts/…"))`), creating directories, overwriting files; logs via `counted(names, tenths(RENDER, "pages written", n), n)` and one line with the largest neighbourhood's program and node count.
- Modify: `cobble/tests/experimental/partition/test_partition_render.py` — the embed test asserts `<script src="/*one*/"></script>`; the dataset-follow test writes the scripts beside the page and passes their relative paths.
- Modify: `Makefile` `partition-render` target: `--out $(PARTITION_DIR)/render`; `docs/reference/cobble/partition.md` render section (output layout, neighbourhood rules, map behaviour); the plan link in the spec is unaffected.
- Test: `cobble/tests/experimental/partition/test_partition_cli.py` — extend its render test (or add `test_the_render_writes_a_map_shared_scripts_and_one_page_per_program`).

**Interfaces:**
- Consumes: `read_graph` (Task 1), `graph_index`, `neighbourhood` (Task 3), `program_map`, `map_page` (Task 4).

- [ ] **Step 1: Write the failing test**: run `main(["--graph", g, "--out", out])` on Task 3's extended `SPREAD_OUT` written with `write_graph`; assert `sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) == ["index.html", "programs/P.html", "programs/Q.html", "programs/S.html", "scripts/graphology.umd.min.js", "scripts/sigma.min.js"]`; that `programs/P.html`'s embedded node ids equal Task 3's `P` list; run `main` twice and assert the second run succeeds (overwrite); and that the logs include `"partition render: largest neighbourhood P, 11 nodes"`.
- [ ] **Step 2: Run** `uv run --no-sync pytest tests/experimental/partition/test_partition_cli.py tests/experimental/partition/test_partition_render.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `page`, `render_cli`, Makefile and doc changes.
- [ ] **Step 4: Run** those tests — Expected: PASS. Then render CardDemo: `cd cobble && uv run --no-sync cobble-experimental-partition-render --graph out-rebuild-20261026-forced/graph.jsonl --out <scratchpad>/render`; record time and peak RSS (`/usr/bin/time -l`); drive `index.html` and `programs/COACTUPC.html` with the page drivers and confirm no script errors.
- [ ] **Step 5: Commit** `feat(cobble): partition render writes a program map and one page per program's neighbourhood`.
