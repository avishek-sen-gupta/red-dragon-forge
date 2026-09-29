# cobble-viz-pathwalk — CFG Path-Walk Animation

*Design spec · 2026-09-28*

---

## 1. Problem and Motivation

`cobble-fields-trace` samples concrete execution paths through a COBOL
program's CFG and records byte-level provenance (`Dep` records). The
output is a JSONL file — correct and complete, but opaque. It is
difficult to build intuition for *how* path sampling achieves coverage,
*why* certain provenance links appear only on some paths, or *when*
a variable's extent first becomes reachable.

This tool produces a self-contained HTML animation from the same data.
It shows:

1. The inter-procedural paragraph-level CFG, with paths lighting up
   one at a time as the sampler walks them.
2. A coverage counter tracking branch edges as they are taken for the
   first time.
3. Per-variable byte provenance strips, filling in as each path
   witnesses new sources flowing into the selected variables.

The primary use case is presentation and documentation. The output is
a single `.html` file with no external dependencies — open in any
browser, no server required.

---

## 2. Scope

Two deliverables:

| # | What | Where |
|---|---|---|
| 1 | `--record-paths` flag on `cobble-fields-trace` | `cobble/cobble/dataflow/fields/trace_report.py` |
| 2 | New `cobble-viz-pathwalk` command | `cobble/cobble/dataflow/fields/pathwalk_viz.py` + CLI entry |

Nothing in `trace.py` changes — the `PathListener` hook already exists
in `sampled_streaming`. The report layer just needs to wire it up.

---

## 3. Part 1 — `--record-paths` Flag

### 3.1 New CLI argument

```
cobble-fields-trace PROGRAM --asg-dir DIR --out TRACE.jsonl \
    [--record-paths PATHS.jsonl]
```

When `--record-paths` is given, a second JSONL file is written alongside
the dep trace. Omitting it preserves existing behaviour exactly.

### 3.2 Path record format

One JSON line per completed path (same order as paths are sampled):

```json
{
  "kind": "path",
  "path_index": 0,
  "nodes": ["PROG_ENTRY/0000-MAIN/label", "PROG_ENTRY/1000-INITIALIZE/0", ...],
  "branch_edges_new": [
    ["PROG_ENTRY", "0010-CHECK-INPUT#test", "TRUE"],
    ["PROG_ENTRY", "0010-CHECK-INPUT#test", "FALSE"]
  ],
  "deps": [
    {
      "program": "PROG_ENTRY",
      "node": "PROG_ENTRY/1000-INITIALIZE/2",
      "target": {"field": "PROG_ENTRY-REC", "region": "working_storage", "start": 3200, "end": 4200},
      "origin": "",
      "source": {"field": "DFHCOMMAREA", "region": "linkage", "start": 0, "end": 1000},
      "source_program": "PROG_ENTRY",
      "definers": []
    }
  ]
}
```

Fields:
- `path_index` — 0-based, matches position in the dep trace
- `nodes` — the full ordered `_Walk.order` sequence (statement-level node IDs)
- `branch_edges_new` — branch edges covered for the first time on this
  path (triple: program, node, edge-kind-value). The union over all
  paths is the coverage denominator.
- `deps` — deps witnessed on this path only (subset of the aggregate
  dep JSONL)

### 3.3 Implementation

In `trace_report._make_sink`, the sink already writes dep rows to the
dep JSONL. A `PathRecord` accumulates the per-path data:

```python
@dataclass
class _PathRecorder:
    path_file: TextIOWrapper
    path_index: int = 0
    pending_deps: list[dict] = field(default_factory=list)
    coverage_so_far: frozenset = frozenset()

    def record_dep(self, dep: Dep) -> None:
        self.pending_deps.append(_dep_dict(dep))

    def record_path(self, nodes: tuple[str, ...]) -> None:
        # called by the PathListener callback
        ...
        self.path_index += 1
        self.pending_deps.clear()
```

The `Sink` is already called per-dep; the `PathListener` is called
per-path. Wiring: `_make_sink` returns both a `Sink` and a
`PathListener`; `_run_trace` passes the listener to `sampled_streaming`.

---

## 4. Part 2 — `cobble-viz-pathwalk`

### 4.1 CLI

```
cobble-viz-pathwalk \
    --cfg       PROGRAM.json        # srccfg bundle (from cobble-srccfg-build)
    --paths     PATHS.jsonl         # path records (from cobble-fields-trace --record-paths)
    --vars      WS-OUTPUT-FIELD,K-AMOUNT-FIELD,...   # comma-separated field names
    --output    pathwalk.html
    [--speed    50]                 # ms per node step (default 50)
    [--pause    600]                # ms pause between paths (default 600)
    [--program  PROG_ENTRY]           # restrict to one program's paragraphs (optional)
```

### 4.2 What the tool does (Python side)

1. **Load CFG** — parse the srccfg bundle JSON, extract all `Node`
   objects. Group by `node.paragraph` to produce the paragraph-level
   graph. Paragraphs become animation nodes; PERFORM/CALL/LINK edges
   between paragraphs become animation edges.

2. **Collapse to paragraph graph** — for each statement-level node ID
   in every path record, map it to its paragraph (split on `/`, take
   index 1). The path at paragraph level is the de-duplicated ordered
   sequence of paragraphs (preserving order, removing consecutive
   repeats). This is what the animation cursor steps through.

3. **Compute layout** — use `networkx` topological layering
   (`nx.topological_generations`) from the paragraph graph entry node,
   assign y-coordinates by layer, x-coordinates by position within
   layer. Nodes that form cycles (PERFORM loops) get a `#loop` suffix
   in their id — place these at the same layer as their entry. Export
   positions as `{id: [x, y]}`.

4. **Build animation bundle** — a single JSON object embedded in the
   HTML:
   ```json
   {
     "nodes": [{"id": "0000-MAIN", "label": "0000-MAIN", "x": 0.5, "y": 0.0, "kind": "LABEL"}],
     "edges": [{"source": "0000-MAIN", "target": "1000-INITIALIZE", "kind": "PERFORM"}],
     "paths": [
       {
         "paragraphs": ["0000-MAIN", "1000-INITIALIZE", "2000-PROCESS", ...],
         "branch_edges_new": [...],
         "provenance": {
           "WS-OUTPUT-FIELD": [
             {"bytes": [2029, 2037], "source": "DFHCOMMAREA", "source_bytes": [0, 8], "origin": ""}
           ]
         }
       }
     ],
     "vars": ["WS-OUTPUT-FIELD", "K-AMOUNT-FIELD"],
     "var_extents": {
       "WS-OUTPUT-FIELD": {"start": 2029, "end": 2037},
       "K-AMOUNT-FIELD": {"start": 482, "end": 489}
     },
     "speed_ms": 50,
     "pause_ms": 600
   }
   ```

5. **Render HTML** — embed the bundle as `const DATA = {...};` in a
   self-contained HTML template (all CSS and JS inline, no CDN).

### 4.3 HTML animation design

#### Graph panel (left ~65% of viewport)

Rendered on an SVG element sized to the viewport.

**Node visual states:**

| State | Shape | Fill | Stroke | Label |
|---|---|---|---|---|
| Unvisited | circle r=14 | none (hollow) | `#94a3b8` 1.5px | grey |
| Active (cursor here) | circle r=14 | `#fbbf24` | `#f59e0b` 2.5px | bold |
| Pulsing (path passing through) | circle r=14→18→14 CSS animation 300ms | `#60a5fa` | `#3b82f6` 2px | white |
| Visited (settled) | circle r=14 | `#3b82f6` 0.35 opacity | `#1d4ed8` 2px | white |
| Newly covered (first time hit) | brief flash `#f472b6` pink before settling | | | |

**Edge visual states:**

| State | Stroke | Width | Style |
|---|---|---|---|
| Unvisited | `#cbd5e1` | 1px | dashed |
| Active (cursor traversing) | `#fbbf24` | 3px | solid, pulse opacity |
| Settled (visited ≥1 time) | `#3b82f6` | 2.5px | solid |
| Newly covered branch | `#f472b6` flash → settled | | |

**Coverage indicator** — top-right corner of graph panel:
```
Branch coverage  47 / 112  (42%)
████████░░░░░░░░░░░░░░░  
Path 3 / 56
```
The bar fills left-to-right as new branch edges are covered.

#### Provenance strips panel (right ~35% of viewport)

One strip per selected variable, stacked vertically.

Each strip:
- Header: field name + byte range e.g. `WS-OUTPUT-FIELD  [2029–2037]`
- Body: a row of cells, one per byte in the field's extent
- Each cell is 8×20px, initially hollow (`#f1f5f9` fill, `#cbd5e1` border)
- When a dep flowing into this field is witnessed on a path, the cells
  for the target byte range are filled with the source's colour
- Source colour palette (consistent across strips):
  - `LITERAL` → `#fbbf24` amber
  - `DFHCOMMAREA` → `#60a5fa` blue
  - `FILE:<ddname>` → `#34d399` green (one shade per file)
  - `UNKNOWN:EIBRESP` → `#f87171` red
- A colour legend below the strips

When a path is being walked, cells that are about to be written
pulse briefly before settling to their source colour.

Fields with more than 40 bytes use a 4×N grid rather than a single
row.

#### Animation loop (JavaScript)

```
state:
  path_index  = 0           // which path we're on
  step_index  = 0           // position within current path's paragraph list
  covered     = Set()       // branch edges covered so far
  node_visits = Map()       // node_id → visit count
  dep_record  = Map()       // var_name → Map(byte_offset → source_colour)

tick():
  path  = DATA.paths[path_index]
  paras = path.paragraphs

  if step_index < paras.length:
    node = paras[step_index]
    // advance cursor: pulse current node + edge from prev
    // update dep_record for any deps in this path at this paragraph
    step_index++
    setTimeout(tick, DATA.speed_ms)
  else:
    // path complete: settle all pulsing nodes/edges
    // mark branch_edges_new as newly covered (pink flash → settled)
    // update coverage counter + bar
    // update provenance strips: fill in dep cells
    step_index = 0
    path_index++
    if path_index < DATA.paths.length:
      setTimeout(tick, DATA.pause_ms)
    // else: animation complete, show summary

controls:
  Play/Pause button — toggles a `running` flag checked in tick()
  Speed slider — adjusts DATA.speed_ms live (10ms–500ms)
  Reset button — returns to path 0, clears all visited state
```

---

## 5. Layout Algorithm Details

The paragraph graph is a DAG with back-edges at loop headers
(nodes whose id contains `#loop`). Strategy:

1. Remove back-edges temporarily.
2. Run `nx.topological_generations` → layers.
3. Within each layer, sort by program name then paragraph name for
   stable ordering.
4. Assign `y = layer_index / max_layer`, `x = position_in_layer / layer_size`.
5. Scale to SVG viewport (pad 60px on all sides).
6. Re-add back-edges — they curve upward (negative dy) and are
   rendered with a dashed arc rather than a straight line.

For programs with multiple entry paragraphs or disconnected components,
treat each component separately and stack them vertically with a gap.

---

## 6. Files Touched

```
cobble/
  cobble/dataflow/fields/
    trace_report.py       ← add --record-paths, _PathRecorder, wire PathListener
    pathwalk_viz.py       ← new: CLI + Python side of cobble-viz-pathwalk
    pathwalk_template.html ← new: HTML/JS/CSS animation template (embedded)
  pyproject.toml          ← add cobble-viz-pathwalk entry point
  tests/dataflow/fields/
    test_pathwalk_viz.py  ← new: unit tests for bundle generation
```

No changes to `trace.py`, `state.py`, `layout.py`, or any analysis code.

---

## 7. Testing

- `test_pathwalk_viz.py`:
  - Bundle generation from a minimal 3-paragraph CFG + 2 path records
  - Paragraph collapse: statement nodes correctly mapped to paragraphs
  - Layout: no two nodes at the same (x, y)
  - Provenance: dep records for selected vars appear in the right cells
  - HTML: `DATA =` appears in output, file is self-contained (no external URLs)
- Existing `test_fields_trace_report.py`: add a test that `--record-paths`
  produces a valid JSONL where `path_index` is strictly increasing and
  every node in `nodes` appears in the CFG

---

## 8. Out of Scope

- Interactive exploration (pause/step/click) — future work
- Cross-LINK path animation (multiple programs on screen) — the
  `--program` flag restricts to one program's paragraph subgraph;
  callees are shown as single "external call" nodes
- Video export — the browser's native screen recording is sufficient
  for the presentation use case; no server-side rendering
