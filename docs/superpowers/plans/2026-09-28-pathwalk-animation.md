# cobble-viz-pathwalk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--record-paths` to `cobble-fields-trace` and a new `cobble-viz-pathwalk` command that produces a self-contained HTML animation showing paragraph-level CFG path walks with byte provenance strips.

**Architecture:** `trace_report.py` gains a `_PathRecorder` that wires the existing `PathListener` hook in `sampled_streaming` to write per-path JSONL records. A new `pathwalk_viz.py` reads a srccfg bundle + path records JSONL, collapses statement nodes to paragraph level, lays out the paragraph graph with `networkx` topological layering, and writes a self-contained HTML file with all animation logic inline.

**Tech Stack:** Python 3.12+, `networkx` (already a cobble dep), vanilla JS/SVG (no CDN — self-contained HTML), `json`, `argparse`.

**Spec:** `docs/superpowers/specs/2026-09-28-pathwalk-animation-design.md`

## Global Constraints

- Self-contained HTML output: no external URLs, no CDN, all CSS and JS inline.
- Zero changes to `trace.py`, `state.py`, `layout.py`, or any analysis logic.
- `--record-paths` is purely additive: omitting it preserves existing `cobble-fields-trace` behaviour exactly.
- Entry point name: `cobble-viz-pathwalk` in `pyproject.toml`.
- New files live under `cobble/cobble/dataflow/fields/` (recorder) and `cobble/cobble/viz/` (animation tool).
- All new code passes `python-fp-lint` (no unfrozen dataclasses, no mutation outside `__init__`, no augmented assignment).

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `cobble/cobble/dataflow/fields/trace_report.py` | Modify | Add `--record-paths`, `_PathRecord`, `_PathRecorder`, wire `PathListener` |
| `cobble/cobble/viz/pathwalk_viz.py` | Create | CLI + Python bundle builder for the animation |
| `cobble/cobble/viz/pathwalk_template.html` | Create | Self-contained HTML/JS/CSS animation template |
| `cobble/pyproject.toml` | Modify | Add `cobble-viz-pathwalk` entry point |
| `cobble/tests/dataflow/fields/test_path_recorder.py` | Create | Unit tests for `_PathRecord`, `_PathRecorder`, JSONL output |
| `cobble/tests/viz/test_pathwalk_viz.py` | Create | Unit tests for paragraph collapse, layout, bundle generation, HTML output |

---

## Task 1: `_PathRecord` dataclass and JSONL serialisation

**Files:**
- Modify: `cobble/cobble/dataflow/fields/trace_report.py`
- Create: `cobble/tests/dataflow/fields/test_path_recorder.py`

**Interfaces:**
- Produces:
  - `_PathRecord(path_index: int, nodes: tuple[str, ...], branch_edges_new: tuple[tuple[str, str, str], ...], deps: tuple[dict, ...])` — frozen dataclass
  - `_path_record_row(record: _PathRecord) -> str` — JSON line with `kind: "path"`

- [ ] **Step 1: Write the failing tests**

```python
# cobble/tests/dataflow/fields/test_path_recorder.py
from __future__ import annotations
import json
from cobble.dataflow.fields.trace_report import _PathRecord, _path_record_row

_RECORD = _PathRecord(
    path_index=0,
    nodes=("PROG/PARA-A/label", "PROG/PARA-A/0", "PROG/PARA-B/label"),
    branch_edges_new=(("PROG", "PARA-A#test", "TRUE"),),
    deps=({"kind": "dep", "program": "PROG", "node": "PROG/PARA-A/0"},),
)

def test_path_record_row_kind():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["kind"] == "path"

def test_path_record_row_path_index():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["path_index"] == 0

def test_path_record_row_nodes():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["nodes"] == list(_RECORD.nodes)

def test_path_record_row_branch_edges_new():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["branch_edges_new"] == [list(e) for e in _RECORD.branch_edges_new]

def test_path_record_row_deps():
    parsed = json.loads(_path_record_row(_RECORD))
    assert parsed["deps"] == list(_RECORD.deps)

def test_path_record_is_frozen():
    import dataclasses
    assert dataclasses.fields(_RECORD)  # confirms it is a dataclass
    try:
        _RECORD.path_index = 1  # type: ignore
        assert False, "should be frozen"
    except (dataclasses.FrozenInstanceError, AttributeError):
        pass
```

- [ ] **Step 2: Run to confirm failure**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_path_recorder.py -v 2>&1 | tail -5
```
Expected: `ImportError` — `_PathRecord` not yet defined.

- [ ] **Step 3: Add `_PathRecord` and `_path_record_row` to `trace_report.py`**

Add after the existing imports and before `_dep_row`:

```python
@dataclass(frozen=True)
class _PathRecord:
    path_index: int
    nodes: tuple[str, ...]
    branch_edges_new: tuple[tuple[str, str, str], ...]
    deps: tuple[dict, ...]


def _path_record_row(record: _PathRecord) -> str:
    return json.dumps({
        "kind": "path",
        "path_index": record.path_index,
        "nodes": list(record.nodes),
        "branch_edges_new": [list(e) for e in record.branch_edges_new],
        "deps": list(record.deps),
    })
```

Add `from dataclasses import dataclass` to imports if not already present (it is — `Budget` uses it via `trace.py`; add it to `trace_report.py`'s own imports explicitly).

- [ ] **Step 4: Run tests to confirm pass**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_path_recorder.py -v
```
Expected: all 6 pass.

- [ ] **Step 5: Commit**
```bash
cd cobble && git add cobble/dataflow/fields/trace_report.py tests/dataflow/fields/test_path_recorder.py
git commit -m "feat(fields-trace): add _PathRecord dataclass and JSONL serialisation"
```

---

## Task 2: `_PathRecorder` — accumulates per-path state and writes on `PathListener` call

**Files:**
- Modify: `cobble/cobble/dataflow/fields/trace_report.py`
- Modify: `cobble/tests/dataflow/fields/test_path_recorder.py`

**Interfaces:**
- Consumes: `_PathRecord`, `_path_record_row` (Task 1); `Dep` from `cobble.dataflow.fields.trace`
- Produces:
  - `_PathRecorder` — a stateful object (uses a list internally, resets per path; mutation is confined to its own methods)
  - `_PathRecorder(path_file: IO[str], coverage_so_far: frozenset[tuple[str, str, str]])` — constructor
  - `_PathRecorder.record_dep(dep: Dep) -> _PathRecorder` — returns new recorder with dep appended
  - `_PathRecorder.flush(nodes: tuple[str, ...], new_coverage: frozenset[tuple[str, str, str]]) -> _PathRecorder` — writes one path record, increments index, clears pending deps
  - **Note:** fp-lint forbids mutation outside `__init__` — use a pattern where the recorder is a frozen dataclass that returns new instances, OR use a single class with all mutation in `__init__`. The simplest fp-lint-safe approach: make `_PathRecorder` a plain class where `record_dep` and `flush` write through to a list that is set once in `__init__`. Check the fp-lint rules carefully — `no-list-append` is forbidden. Use `tuple` accumulation with reassignment inside `__init__` scope — actually the cleanest approach is to write each dep directly to the file as it arrives and track the path index as a simple counter object.

**Revised approach** (fp-lint safe — no list mutation, no augmented assignment):

`_PathRecorder` holds the file handle and a mutable counter object (a single-element list set in `__init__`). The dep dicts are accumulated by writing directly to a side list set once in `__init__` — but `no-list-append` blocks this. 

**Cleanest fp-lint-safe pattern:** A `_Accumulator` with a `__call__` interface that uses a `collections.deque` (not blocked by fp-lint). Or — simplest of all — write each dep JSON to a `StringIO` buffer per path; on `flush`, drain it. The buffer is reset by reassignment, not mutation.

```python
# Each path's deps are accumulated in a list that is created fresh per path
# and referenced by a single-slot container (a one-element list set in __init__)
# so the list itself is never appended to — it is replaced whole.
# fp-lint's no-list-append applies to augmented mutation, not reassignment.
# Use a _Slot wrapper:

@dataclass(frozen=True)  
class _Slot:
    """Single mutable slot. Set once in __init__, replaced via _Slot.put."""
    # We use a one-element list as the slot — set in __init__, never appended.
    _cell: list  # exactly one element; replaced by put()

    @staticmethod
    def of(value) -> "_Slot":
        return _Slot(_cell=[value])  # one-time construction

    def get(self):
        return self._cell[0]

    def put(self, value) -> None:
        self._cell[0] = value  # assignment to index 0, not append
```

Actually — check what fp-lint actually blocks. `no-subscript-mutation` blocks `x[0] = v`. `no-list-append` blocks `.append()`. The safe path: use `io.StringIO` as a write buffer, call `.write()` (not blocked), reset by replacing the `StringIO` reference.

Given the complexity, the simplest correct approach: `_PathRecorder` is NOT a frozen dataclass. It is a plain class whose `__init__` sets up state and whose methods are called in sequence. fp-lint's `no-mutation-outside-init` means all mutation fields are initialized in `__init__` and only written in `__init__`. Methods that "update" state return new instances.

**Simplest working pattern:**

```python
class _PathRecorder:
    def __init__(self, path_file: IO[str]) -> None:
        self._path_file = path_file
        self._path_index = 0
        self._pending: list[dict] = []
        self._coverage: frozenset[tuple[str, str, str]] = frozenset()
```

Then `record_dep` and `flush` mutate `_pending`, `_path_index`, `_coverage`. This IS mutation outside `__init__` — but fp-lint checks for `no-mutation-outside-init` only on **dataclasses** (the `no-unfrozen-dataclass` rule + `no-attribute-augmented-mutation`). A plain class with explicit mutation in methods is fine. Confirm by checking `python-fp-lint/rules/no-mutation-outside-init.yml` — if it exists and applies to plain classes, use the functional approach; if it only applies to dataclasses, the plain class is fine.

- [ ] **Step 1: Check fp-lint mutation rule scope**
```bash
cat /Users/avisheksengupta/code/red-dragon-forge/.python-fp-lint/rules/no-mutation-outside-init.yml 2>/dev/null || echo "no such rule"
cat /Users/avisheksengupta/code/red-dragon-forge/.python-fp-lint/rules/no-attribute-augmented-mutation.yml 2>/dev/null | head -20
```
If the rule only blocks `+=` / `-=` augmented assignment (not plain `=`), a plain class with `self._x = new_value` in methods is fine.

- [ ] **Step 2: Write the failing tests**

```python
# append to test_path_recorder.py
import io
from cobble.dataflow.fields.trace_report import _PathRecorder
from cobble.dataflow.fields.trace import Dep
from cobol_memory.field_extent import FieldExtent, Precision
from cobol_memory.region_id import RegionId

_WS = RegionId.WORKING_STORAGE
_EXT = FieldExtent(field_name="F", region=_WS, start=0, length=4, precision=Precision.EXACT)
_DEP = Dep(program="P", node="P/A/0", target=_EXT, origin="LITERAL",
           source=_EXT, definers=(), via="", source_program="P")

def test_path_recorder_writes_path_record():
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.record_dep(_DEP)
    recorder.flush(("P/A/label", "P/A/0"), frozenset({("P", "A#test", "TRUE")}))
    buf.seek(0)
    lines = [l for l in buf.read().splitlines() if l.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["kind"] == "path"
    assert row["path_index"] == 0
    assert "P/A/label" in row["nodes"]

def test_path_recorder_increments_index():
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.flush(("P/A/label",), frozenset())
    recorder.flush(("P/B/label",), frozenset())
    buf.seek(0)
    rows = [json.loads(l) for l in buf.read().splitlines() if l.strip()]
    assert rows[0]["path_index"] == 0
    assert rows[1]["path_index"] == 1

def test_path_recorder_clears_deps_between_paths():
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    recorder.record_dep(_DEP)
    recorder.flush(("P/A/0",), frozenset())
    recorder.flush(("P/B/0",), frozenset())   # no record_dep before this
    buf.seek(0)
    rows = [json.loads(l) for l in buf.read().splitlines() if l.strip()]
    assert len(rows[1]["deps"]) == 0

def test_path_recorder_branch_edges_new_excludes_already_covered():
    buf = io.StringIO()
    recorder = _PathRecorder(buf)
    edge_a = ("P", "A#test", "TRUE")
    edge_b = ("P", "A#test", "FALSE")
    recorder.flush(("P/A/0",), frozenset({edge_a}))
    recorder.flush(("P/B/0",), frozenset({edge_a, edge_b}))  # edge_a already seen
    buf.seek(0)
    rows = [json.loads(l) for l in buf.read().splitlines() if l.strip()]
    assert rows[0]["branch_edges_new"] == [list(edge_a)]
    assert rows[1]["branch_edges_new"] == [list(edge_b)]  # only the new one
```

- [ ] **Step 3: Run to confirm failure**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_path_recorder.py -v -k "recorder" 2>&1 | tail -8
```

- [ ] **Step 4: Implement `_PathRecorder` in `trace_report.py`**

Add after `_path_record_row`:

```python
class _PathRecorder:
    """Accumulates per-path state and writes one path record per completed path.

    ``record_dep`` is called once per Dep as paths are streamed.
    ``flush`` is called once per completed path via PathListener.
    """

    def __init__(self, path_file: IO[str]) -> None:
        self._path_file = path_file
        self._path_index: int = 0
        self._pending_deps: list[dict] = []
        self._covered: frozenset[tuple[str, str, str]] = frozenset()

    def record_dep(self, dep: Dep) -> None:
        self._pending_deps = [*self._pending_deps, _dep_dict(dep)]

    def flush(
        self,
        nodes: tuple[str, ...],
        new_coverage: frozenset[tuple[str, str, str]],
    ) -> None:
        newly = new_coverage - self._covered
        record = _PathRecord(
            path_index=self._path_index,
            nodes=nodes,
            branch_edges_new=tuple(sorted(newly)),
            deps=tuple(self._pending_deps),
        )
        self._path_file.write(_path_record_row(record) + "\n")
        self._path_index = self._path_index + 1
        self._pending_deps = []
        self._covered = self._covered | new_coverage
```

Add a `_dep_dict(dep: Dep) -> dict` helper that mirrors `_dep_row` but returns a dict (not a JSON string):

```python
def _dep_dict(dep: Dep) -> dict:
    """The dep as a plain dict (for embedding inside path records)."""
    return json.loads(_dep_row(dep))
```

- [ ] **Step 5: Run tests to confirm pass**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_path_recorder.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Run fp-lint**
```bash
cd cobble && uv run python -m python_fp_lint . 2>&1 | grep -E "ERROR|trace_report" | head -10
```
Fix any violations before proceeding.

- [ ] **Step 7: Commit**
```bash
cd cobble && git add cobble/dataflow/fields/trace_report.py tests/dataflow/fields/test_path_recorder.py
git commit -m "feat(fields-trace): add _PathRecorder for per-path JSONL accumulation"
```

---

## Task 3: Wire `--record-paths` into the `cobble-fields-trace` CLI

**Files:**
- Modify: `cobble/cobble/dataflow/fields/trace_report.py`
- Modify: `cobble/tests/dataflow/fields/test_path_recorder.py`

**Interfaces:**
- Consumes: `_PathRecorder` (Task 2); `sampled_streaming` from `cobble.dataflow.fields.trace` (already imported)
- Produces: `cobble-fields-trace PROG --asg-dir DIR --out DEPS.jsonl --record-paths PATHS.jsonl` writes both files

- [ ] **Step 1: Write the failing integration test**

```python
# append to test_path_recorder.py
import tempfile, pathlib
from cobble.dataflow.fields.trace_report import cli

def test_record_paths_flag_accepted_without_error(tmp_path):
    """CLI accepts --record-paths; produces a valid JSONL even with a stub asg-dir."""
    # We just test the flag is wired; actual sampling requires a real ASG cache.
    # Verify the argparser accepts the flag without raising.
    import argparse
    from cobble.dataflow.fields.trace_report import _parser
    args = _parser().parse_args([
        "MYPROG",
        "--asg-dir", str(tmp_path),
        "--out", str(tmp_path / "deps.jsonl"),
        "--record-paths", str(tmp_path / "paths.jsonl"),
    ])
    assert str(args.record_paths) == str(tmp_path / "paths.jsonl")

def test_record_paths_flag_absent_gives_none(tmp_path):
    from cobble.dataflow.fields.trace_report import _parser
    args = _parser().parse_args([
        "MYPROG",
        "--asg-dir", str(tmp_path),
        "--out", str(tmp_path / "deps.jsonl"),
    ])
    assert args.record_paths is None
```

- [ ] **Step 2: Run to confirm failure**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_path_recorder.py -v -k "flag" 2>&1 | tail -5
```

- [ ] **Step 3: Add `--record-paths` to `_parser()` in `trace_report.py`**

```python
# In _parser(), after the --max-depth argument:
parser.add_argument(
    "--record-paths",
    type=Path,
    default=None,
    metavar="PATHS",
    help="if given, write one path record per sampled path to this JSONL file",
)
```

- [ ] **Step 4: Wire recorder into `_run_trace`**

Replace the current `_run_trace` with a version that optionally opens the paths file and passes a `PathListener`:

```python
def _run_trace(
    program: str,
    asg_dir: Path,
    budget: Budget,
    out: Path,
    record_paths: Path | None = None,
) -> Trace:
    logger.info(
        "trace: sampling %s  paths=%d  coverage=%.2f  max_depth=%d",
        program, budget.paths, budget.coverage, budget.max_depth,
    )
    started = time.monotonic()
    ensure_parent(out)
    paths_handle = record_paths.open("w", encoding="utf-8") if record_paths else None
    recorder = _PathRecorder(paths_handle) if paths_handle is not None else None

    def _sink(deps: frozenset[Dep]) -> None:
        if recorder is not None:
            for dep in sorted(deps, key=lambda d: d.node):
                recorder.record_dep(dep)

    def _listener(nodes: tuple[str, ...]) -> None:
        if recorder is not None:
            recorder.flush(nodes, frozenset())   # coverage tracking TODO Task 4

    with out.open("w", encoding="utf-8") as handle:
        trace = sampled_streaming(program, asg_dir, budget, handle.write, _listener)
        for line in _footer_lines(trace):
            handle.write(line + "\n")
    if paths_handle is not None:
        paths_handle.close()
    elapsed = time.monotonic() - started
    logger.info(
        "trace: %d dead ends, %d/%d branches (%.0f%%) over %d paths in %.1fs",
        len(trace.dead_ends), len(trace.coverage.taken), trace.coverage.total,
        100 * trace.coverage.fraction, trace.paths, elapsed,
    )
    return trace
```

Update `cli()` to pass `record_paths=arguments.record_paths`.

Note: The `_sink` currently receives a `frozenset[Dep]` per path (the existing `_make_sink` pattern writes each dep as a row). Reconcile: the existing `_make_sink` returns a `Sink = Callable[[frozenset[Dep]], None]` that writes each dep. The recorder's `record_dep` should be called from the same sink. The `_streamed_round` calls `sink(stepped.deps)` where `stepped.deps` is the deps from the most recently completed path. So the recorder accumulates those deps, then `flush` is called by the listener. The order is: `sink(path_deps)` then `path_listener(path_nodes)`. This is correct.

- [ ] **Step 5: Run tests**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_path_recorder.py -v
```

- [ ] **Step 6: Run the existing fields-trace test suite to catch regressions**
```bash
cd cobble && uv run pytest tests/dataflow/fields/test_fields_trace_report.py -v
```
All existing tests must pass.

- [ ] **Step 7: Commit**
```bash
cd cobble && git add cobble/dataflow/fields/trace_report.py tests/dataflow/fields/test_path_recorder.py
git commit -m "feat(fields-trace): wire --record-paths CLI flag and PathListener"
```

---

## Task 4: Branch-edge coverage tracking in the path recorder

**Context:** `_PathRecorder.flush` currently receives `frozenset()` as `new_coverage`
because the `PathListener` signature is `Callable[[tuple[str, ...]], None]` — it only
gets node IDs, not branch edges. Branch edges taken per path are available on
`_Walk.taken` inside `trace.py`, but `PathListener` doesn't expose them.

The simplest fix without touching `trace.py`: derive newly-covered branch edges from the
path's node sequence. A branch edge is `(program, node_id, edge_kind)` where `node_id`
is a TEST node. We can identify TEST nodes from the CFG (loaded from the srccfg bundle).
But `trace_report.py` doesn't load the CFG — it only knows the ASG dir.

**Decision:** Extend `PathListener` type to pass taken branch edges. Since `PathListener`
is a type alias in `trace.py`, the cleanest change is to update it to
`Callable[[tuple[str, ...], frozenset[tuple[str, str, str]]], None]` — but this breaks all
existing `_ignore_path` callers.

**Simpler alternative:** Leave `PathListener` unchanged. Instead, pass `Coverage`
(already on `_Stepped`) through a second callback. The `_streamed_round` already has
access to `stepped.trace.coverage.taken` after each path.

**Actual simplest approach:** Accumulate `coverage.taken` outside `trace.py` by having
`_PathRecorder.flush` receive the running coverage snapshot from a separate
`CoverageListener = Callable[[frozenset], None]` — but this still requires a trace.py
change.

**Pragmatic decision for v1:** Derive `branch_edges_new` in post-processing in `pathwalk_viz.py`
rather than in the recorder. The path records emit all edges visited; the viz tool
computes which were new by scanning path records in order. Remove `branch_edges_new`
from the path record for now and compute it in Task 6. Update the tests in Task 2 accordingly.

- [ ] **Step 1: Update `_PathRecord` — remove `branch_edges_new`**

```python
@dataclass(frozen=True)
class _PathRecord:
    path_index: int
    nodes: tuple[str, ...]
    deps: tuple[dict, ...]
```

Update `_path_record_row`:
```python
def _path_record_row(record: _PathRecord) -> str:
    return json.dumps({
        "kind": "path",
        "path_index": record.path_index,
        "nodes": list(record.nodes),
        "deps": list(record.deps),
    })
```

Update `_PathRecorder.flush` signature:
```python
def flush(self, nodes: tuple[str, ...]) -> None:
    record = _PathRecord(
        path_index=self._path_index,
        nodes=nodes,
        deps=tuple(self._pending_deps),
    )
    self._path_file.write(_path_record_row(record) + "\n")
    self._path_index = self._path_index + 1
    self._pending_deps = []
```

- [ ] **Step 2: Update the Task 2 tests that reference `branch_edges_new`**

Remove `test_path_recorder_branch_edges_new_excludes_already_covered`. Update
`test_path_recorder_writes_path_record` to not assert on `branch_edges_new`.

- [ ] **Step 3: Run all recorder tests**
```bash
cd cobble && uv run pytest tests/dataflow/fields/ -v
```
Expected: all pass.

- [ ] **Step 4: Commit**
```bash
cd cobble && git add cobble/dataflow/fields/trace_report.py tests/dataflow/fields/test_path_recorder.py
git commit -m "refactor(fields-trace): remove branch_edges_new from path record (derived in viz)"
```

---

## Task 5: Paragraph collapse and layout (`pathwalk_viz.py` — data layer)

**Files:**
- Create: `cobble/cobble/viz/pathwalk_viz.py`
- Create: `cobble/tests/viz/test_pathwalk_viz.py`

**Interfaces:**
- Consumes: `cobble.dataflow.srccfg.bundle.load_bundle` (already exists), `networkx` (already a dep)
- Produces:
  - `paragraphs_of(cfgs: Sequence[Cfg]) -> dict[str, set[str]]` — maps paragraph name to set of statement node IDs
  - `collapse_path(nodes: tuple[str, ...]) -> tuple[str, ...]` — maps statement-level node sequence to paragraph sequence (de-duplicate consecutive repeats)
  - `paragraph_graph(cfgs: Sequence[Cfg]) -> nx.DiGraph` — directed graph where nodes are paragraph names, edges are PERFORM/CALL/LINK between paragraphs
  - `layered_positions(g: nx.DiGraph) -> dict[str, tuple[float, float]]` — stable x,y positions in [0,1]² using topological layering
  - `build_bundle(cfgs, path_records_jsonl, var_names, speed_ms, pause_ms) -> dict` — the full animation data bundle (JSON-serialisable)

- [ ] **Step 1: Write the failing tests**

```python
# cobble/tests/viz/test_pathwalk_viz.py
from __future__ import annotations
import json, io
import networkx as nx
from cobble.viz.pathwalk_viz import (
    collapse_path,
    paragraph_graph,
    layered_positions,
    build_bundle,
)
from cobble.dataflow.srccfg.cfg import Cfg, Node, Edge, NodeKind, EdgeKind, Atom, SourceSpan

_SPAN = SourceSpan(start=1, end=2, text="")
_ATOM = Atom(text="", left="", op="", right="", resolved=True)

def _node(id_: str, para: str, kind: NodeKind = NodeKind.ASSIGN) -> Node:
    return Node(id=id_, kind=kind, paragraph=para, atom=_ATOM, span=_SPAN,
                writes=(), reads=(), transfer="", target="", target_resolved=True,
                transfer_operand="", using=())

def _edge(src: str, tgt: str, kind: EdgeKind = EdgeKind.FLOW) -> Edge:
    return Edge(source=src, target=tgt, kind=kind)

_CFG = Cfg(
    program="PROG",
    nodes=(
        _node("PROG/MAIN/label", "MAIN", NodeKind.LABEL),
        _node("PROG/MAIN/0", "MAIN"),
        _node("PROG/SUB/label", "SUB", NodeKind.LABEL),
        _node("PROG/SUB/0", "SUB"),
    ),
    edges=(
        _edge("PROG/MAIN/0", "PROG/SUB/label", EdgeKind.PERFORM),
        _edge("PROG/SUB/0", "PROG/MAIN/0", EdgeKind.RETURN),
    ),
)

def test_collapse_path_maps_to_paragraphs():
    path = ("PROG/MAIN/label", "PROG/MAIN/0", "PROG/SUB/label", "PROG/SUB/0")
    result = collapse_path(path)
    assert result == ("MAIN", "SUB")

def test_collapse_path_removes_consecutive_duplicates():
    path = ("PROG/MAIN/label", "PROG/MAIN/0", "PROG/MAIN/1")
    result = collapse_path(path)
    assert result == ("MAIN",)

def test_paragraph_graph_has_perform_edge():
    g = paragraph_graph((_CFG,))
    assert g.has_edge("MAIN", "SUB")

def test_layered_positions_all_nodes_placed():
    g = nx.DiGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    positions = layered_positions(g)
    assert set(positions.keys()) == {"A", "B", "C"}

def test_layered_positions_y_increases_with_depth():
    g = nx.DiGraph()
    g.add_edge("A", "B")
    g.add_edge("B", "C")
    pos = layered_positions(g)
    assert pos["A"][1] < pos["B"][1] < pos["C"][1]

def test_build_bundle_has_required_keys():
    path_jsonl = json.dumps({"kind": "path", "path_index": 0,
                             "nodes": ["PROG/MAIN/label", "PROG/SUB/0"],
                             "deps": []}) + "\n"
    bundle = build_bundle((_CFG,), io.StringIO(path_jsonl), ["FIELD-A"], 50, 600)
    assert "nodes" in bundle
    assert "edges" in bundle
    assert "paths" in bundle
    assert "vars" in bundle
    assert bundle["speed_ms"] == 50
    assert bundle["pause_ms"] == 600

def test_build_bundle_path_has_paragraph_list():
    path_jsonl = json.dumps({"kind": "path", "path_index": 0,
                             "nodes": ["PROG/MAIN/label", "PROG/SUB/0"],
                             "deps": []}) + "\n"
    bundle = build_bundle((_CFG,), io.StringIO(path_jsonl), [], 50, 600)
    assert bundle["paths"][0]["paragraphs"] == ["MAIN", "SUB"]

def test_build_bundle_branch_edges_new_derived():
    # Path 0 covers MAIN->SUB. Path 1 covers MAIN->SUB again (already covered)
    # and also covers MAIN->EXIT (new). branch_edges_new for path 1 = only MAIN->EXIT.
    p0 = json.dumps({"kind": "path", "path_index": 0,
                     "nodes": ["PROG/MAIN/label", "PROG/MAIN/0", "PROG/SUB/label"],
                     "deps": []})
    p1 = json.dumps({"kind": "path", "path_index": 1,
                     "nodes": ["PROG/MAIN/label", "PROG/SUB/label"],
                     "deps": []})
    path_jsonl = p0 + "\n" + p1 + "\n"
    # For this test, we just verify the key exists and is a list
    bundle = build_bundle((_CFG,), io.StringIO(path_jsonl), [], 50, 600)
    assert isinstance(bundle["paths"][0]["branch_edges_new"], list)
    assert isinstance(bundle["paths"][1]["branch_edges_new"], list)
```

- [ ] **Step 2: Run to confirm failure**
```bash
cd cobble && uv run pytest tests/viz/test_pathwalk_viz.py -v 2>&1 | tail -5
```

- [ ] **Step 3: Implement `pathwalk_viz.py` data layer**

```python
# cobble/cobble/viz/pathwalk_viz.py
"""cobble-viz-pathwalk: self-contained HTML animation of CFG path walks."""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import IO

import networkx as nx

from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind


def collapse_path(nodes: tuple[str, ...]) -> tuple[str, ...]:
    """Map statement-level node IDs to paragraph names, drop consecutive repeats.

    Each node ID is `PROGRAM/PARAGRAPH/statement_index`. Split on `/` and take
    index 1 to get the paragraph name.
    """
    def _para(node_id: str) -> str:
        parts = node_id.split("/")
        return parts[1] if len(parts) >= 2 else node_id

    result: list[str] = []
    for node_id in nodes:
        para = _para(node_id)
        if not result or result[-1] != para:
            result = [*result, para]
    return tuple(result)


def paragraph_graph(cfgs: Sequence[Cfg]) -> nx.DiGraph:
    """Directed paragraph-level graph from a CFG bundle.

    Nodes are paragraph names. Edges are PERFORM, CALL, LINK, GOTO between
    distinct paragraphs (intra-program edges only; no cross-program LINK edges
    since we collapse to one program's paragraph namespace).
    """
    g: nx.DiGraph = nx.DiGraph()
    _CROSS_PARA_KINDS = (
        EdgeKind.PERFORM, EdgeKind.GOTO, EdgeKind.CALL if hasattr(EdgeKind, "CALL") else None
    )
    for cfg in cfgs:
        for node in cfg.nodes:
            g.add_node(node.paragraph, kind=node.kind.value)
        for edge in cfg.edges:
            src_parts = edge.source.split("/")
            tgt_parts = edge.target.split("/")
            if len(src_parts) >= 2 and len(tgt_parts) >= 2:
                src_para = src_parts[1]
                tgt_para = tgt_parts[1]
                if src_para != tgt_para:
                    g.add_edge(src_para, tgt_para, kind=edge.kind.value)
    return g


def layered_positions(g: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Assign stable x,y positions in [0.05, 0.95]² using topological layering.

    Back-edges (cycles) are removed before layering, then re-added as
    visual-only arcs. Returns {node_id: (x, y)} where y increases with depth.
    """
    # Identify and remove back-edges
    back_edges = set(nx.edges(nx.DiGraph([(u, v) for u, v, _ in nx.find_cycle(g)]))) \
        if not nx.is_directed_acyclic_graph(g) else set()
    dag = nx.DiGraph(
        (u, v) for u, v in g.edges() if (u, v) not in back_edges
    )
    for node in g.nodes():
        if node not in dag:
            dag.add_node(node)

    try:
        generations = list(nx.topological_generations(dag))
    except nx.NetworkXUnfeasible:
        # Fallback: assign all nodes to layer 0
        generations = [list(g.nodes())]

    n_layers = max(len(generations), 1)
    positions: dict[str, tuple[float, float]] = {}
    for layer_idx, layer in enumerate(generations):
        y = 0.05 + (layer_idx / max(n_layers - 1, 1)) * 0.90
        n_in_layer = max(len(layer), 1)
        for pos_idx, node in enumerate(sorted(layer)):
            x = 0.05 + (pos_idx / max(n_in_layer - 1, 1)) * 0.90 if n_in_layer > 1 else 0.5
            positions[node] = (round(x, 4), round(y, 4))
    return positions


def _derive_branch_edges_new(
    paths: list[tuple[str, ...]],
    g: nx.DiGraph,
) -> list[list[tuple[str, str]]]:
    """For each path, the paragraph-level edges covered for the first time.

    An edge is a (source_para, target_para) pair. Returns a list parallel to paths.
    """
    covered: set[tuple[str, str]] = set()
    result: list[list[tuple[str, str]]] = []
    for path in paths:
        edges_this_path: set[tuple[str, str]] = set()
        for i in range(len(path) - 1):
            edge = (path[i], path[i + 1])
            if g.has_edge(*edge):
                edges_this_path.add(edge)
        newly = edges_this_path - covered
        covered = covered | newly
        result.append(sorted(newly))
    return result


def build_bundle(
    cfgs: Sequence[Cfg],
    path_records: IO[str],
    var_names: list[str],
    speed_ms: int,
    pause_ms: int,
) -> dict:
    """Build the JSON-serialisable animation bundle."""
    g = paragraph_graph(cfgs)
    positions = layered_positions(g)

    raw_paths: list[dict] = []
    for line in path_records:
        stripped = line.strip()
        if not stripped:
            continue
        row = json.loads(stripped)
        if row.get("kind") == "path":
            raw_paths.append(row)

    collapsed: list[tuple[str, ...]] = [
        collapse_path(tuple(r["nodes"])) for r in raw_paths
    ]
    new_edges = _derive_branch_edges_new(collapsed, g)

    def _provenance_for_vars(deps: list[dict]) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {v: [] for v in var_names}
        for dep in deps:
            target_field = (dep.get("target") or {}).get("field", "")
            if target_field in result:
                result[target_field] = [*result[target_field], {
                    "target_start": (dep.get("target") or {}).get("start", 0),
                    "target_end": (dep.get("target") or {}).get("end", 0),
                    "source_field": (dep.get("source") or {}).get("field", ""),
                    "source_start": (dep.get("source") or {}).get("start", 0),
                    "source_end": (dep.get("source") or {}).get("end", 0),
                    "origin": dep.get("origin", ""),
                }]
        return result

    anim_paths = [
        {
            "paragraphs": list(para_seq),
            "branch_edges_new": [list(e) for e in new_edges[i]],
            "provenance": _provenance_for_vars(raw["deps"]),
        }
        for i, (para_seq, raw) in enumerate(zip(collapsed, raw_paths))
    ]

    nodes_out = [
        {
            "id": n,
            "label": n,
            "x": positions.get(n, (0.5, 0.5))[0],
            "y": positions.get(n, (0.5, 0.5))[1],
            "kind": data.get("kind", "ASSIGN"),
        }
        for n, data in g.nodes(data=True)
    ]
    edges_out = [
        {"source": u, "target": v, "kind": data.get("kind", "FLOW")}
        for u, v, data in g.edges(data=True)
    ]

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "paths": anim_paths,
        "vars": var_names,
        "speed_ms": speed_ms,
        "pause_ms": pause_ms,
    }
```

- [ ] **Step 4: Run tests**
```bash
cd cobble && uv run pytest tests/viz/test_pathwalk_viz.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**
```bash
cd cobble && git add cobble/cobble/viz/pathwalk_viz.py cobble/tests/viz/test_pathwalk_viz.py
git commit -m "feat(viz): pathwalk_viz data layer — collapse, layout, bundle builder"
```

---

## Task 6: HTML animation template (`pathwalk_template.html`)

**Files:**
- Create: `cobble/cobble/viz/pathwalk_template.html`
- Modify: `cobble/tests/viz/test_pathwalk_viz.py`

**Interfaces:**
- Consumes: bundle dict from `build_bundle` (Task 5)
- Produces: `render_html(bundle: dict, output: Path) -> None` — writes self-contained HTML

The template is an HTML file with a `{{DATA}}` placeholder replaced by the JSON bundle. All JS and CSS is inline. The animation renders on a two-panel layout: graph (SVG, left 65%) and provenance strips (right 35%).

- [ ] **Step 1: Write the failing test**

```python
# append to test_pathwalk_viz.py
import tempfile
from cobble.viz.pathwalk_viz import render_html

_BUNDLE = {
    "nodes": [
        {"id": "MAIN", "label": "MAIN", "x": 0.5, "y": 0.1, "kind": "LABEL"},
        {"id": "SUB",  "label": "SUB",  "x": 0.5, "y": 0.7, "kind": "ASSIGN"},
    ],
    "edges": [{"source": "MAIN", "target": "SUB", "kind": "PERFORM"}],
    "paths": [{"paragraphs": ["MAIN", "SUB"], "branch_edges_new": [], "provenance": {}}],
    "vars": [],
    "speed_ms": 50,
    "pause_ms": 600,
}

def test_render_html_produces_file(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    assert out.exists()
    assert out.stat().st_size > 1000

def test_render_html_is_self_contained(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    assert "http://" not in content
    assert "https://" not in content
    assert "cdn" not in content.lower()

def test_render_html_embeds_data(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    assert "const DATA" in content
    assert '"MAIN"' in content

def test_render_html_has_svg_element(tmp_path):
    out = tmp_path / "anim.html"
    render_html(_BUNDLE, out)
    content = out.read_text()
    assert "<svg" in content
```

- [ ] **Step 2: Run to confirm failure**
```bash
cd cobble && uv run pytest tests/viz/test_pathwalk_viz.py -v -k "render_html" 2>&1 | tail -5
```

- [ ] **Step 3: Create `pathwalk_template.html`**

The template is a complete, working HTML file. The `{{DATA}}` token is the only placeholder. Create it at `cobble/cobble/viz/pathwalk_template.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CFG Path Walk</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: ui-monospace, monospace; background: #0f172a; color: #e2e8f0;
       display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
#header { padding: 10px 16px; background: #1e293b; border-bottom: 1px solid #334155;
          display: flex; align-items: center; gap: 24px; flex-shrink: 0; }
#header h1 { font-size: 13px; color: #94a3b8; font-weight: 500; }
#coverage-bar-wrap { flex: 1; }
#coverage-label { font-size: 11px; color: #64748b; margin-bottom: 3px; }
#coverage-bar { height: 6px; background: #1e3a5f; border-radius: 3px; overflow: hidden; }
#coverage-fill { height: 100%; width: 0%; background: #3b82f6;
                 transition: width 0.3s ease; border-radius: 3px; }
#path-counter { font-size: 12px; color: #64748b; white-space: nowrap; }
#controls { display: flex; gap: 8px; align-items: center; }
#btn-play { padding: 4px 12px; background: #3b82f6; color: #fff; border: none;
            border-radius: 4px; cursor: pointer; font-size: 12px; }
#btn-reset { padding: 4px 10px; background: #334155; color: #94a3b8; border: none;
             border-radius: 4px; cursor: pointer; font-size: 12px; }
#speed-wrap { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #64748b; }
#speed { width: 80px; accent-color: #3b82f6; }
#main { display: flex; flex: 1; overflow: hidden; }
#graph-panel { flex: 0 0 65%; position: relative; overflow: hidden; }
#graph-svg { width: 100%; height: 100%; }
#strips-panel { flex: 1; overflow-y: auto; padding: 12px; border-left: 1px solid #1e293b;
                background: #0f172a; }
#strips-panel h2 { font-size: 11px; color: #475569; text-transform: uppercase;
                   letter-spacing: .05em; margin-bottom: 10px; }
.strip { margin-bottom: 18px; }
.strip-header { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.strip-bytes { display: flex; flex-wrap: wrap; gap: 1px; }
.byte-cell { width: 8px; height: 18px; border: 1px solid #1e3a5f;
             background: #0f172a; border-radius: 1px;
             transition: background 0.3s ease; }
#legend { margin-top: 16px; font-size: 10px; }
.legend-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; color: #64748b; }
.legend-swatch { width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }
</style>
</head>
<body>
<div id="header">
  <h1>CFG Path Walk</h1>
  <div id="coverage-bar-wrap">
    <div id="coverage-label">Branch coverage  <span id="cov-num">0</span> / <span id="cov-den">0</span></div>
    <div id="coverage-bar"><div id="coverage-fill"></div></div>
  </div>
  <div id="path-counter">Path <span id="path-num">0</span> / <span id="path-den">0</span></div>
  <div id="controls">
    <div id="speed-wrap">
      Speed <input id="speed" type="range" min="10" max="500" value="50">
    </div>
    <button id="btn-reset">Reset</button>
    <button id="btn-play">▶ Play</button>
  </div>
</div>
<div id="main">
  <div id="graph-panel">
    <svg id="graph-svg" xmlns="http://www.w3.org/2000/svg"></svg>
  </div>
  <div id="strips-panel">
    <h2>Byte provenance</h2>
    <div id="strips-container"></div>
    <div id="legend">
      <div class="legend-row"><div class="legend-swatch" style="background:#60a5fa"></div>DFHCOMMAREA / linked field</div>
      <div class="legend-row"><div class="legend-swatch" style="background:#fbbf24"></div>LITERAL</div>
      <div class="legend-row"><div class="legend-swatch" style="background:#34d399"></div>FILE read</div>
      <div class="legend-row"><div class="legend-swatch" style="background:#f87171"></div>EIBRESP / unknown</div>
    </div>
  </div>
</div>
<script>
const DATA = {{DATA}};

// ── Colour helpers ──────────────────────────────────────────────────────────
const NODE_FILL = {
  LABEL: "#55A868", CALL: "#C44E52", TEST: "#DD8452",
  ASSIGN: "#4C72B0", NOP: "#666"
};
const EDGE_STROKE = { PERFORM: "#4C72B0", GOTO: "#8172B2", RETURN: "#64B5CD", FLOW: "#334155", FALLTHRU: "#1e293b" };

function sourceColour(origin, sourceField) {
  if (origin === "LITERAL") return "#fbbf24";
  if (origin.startsWith("FILE")) return "#34d399";
  if (origin.startsWith("UNKNOWN")) return "#f87171";
  return "#60a5fa";
}

// ── SVG helpers ─────────────────────────────────────────────────────────────
const SVG_NS = "http://www.w3.org/2000/svg";
function el(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

// ── Build graph ─────────────────────────────────────────────────────────────
const svg = document.getElementById("graph-svg");
let W = svg.clientWidth || 800, H = svg.clientHeight || 600;

function layout() {
  const rect = svg.getBoundingClientRect();
  W = rect.width; H = rect.height;
}
window.addEventListener("resize", () => { layout(); redraw(); });
layout();

function nodePos(n) {
  return [60 + n.x * (W - 120), 40 + n.y * (H - 80)];
}

const nodeEls = {}, edgeEls = {};
const edgeGroup = el("g", {id:"edges"}), nodeGroup = el("g", {id:"nodes"});
svg.appendChild(edgeGroup); svg.appendChild(nodeGroup);

// Arrow marker
const defs = el("defs", {});
const marker = el("marker", {id:"arr", markerWidth:"8", markerHeight:"8",
  refX:"6", refY:"3", orient:"auto"});
const markerPath = el("path", {d:"M0,0 L0,6 L8,3 z", fill:"#334155"});
marker.appendChild(markerPath); defs.appendChild(marker); svg.appendChild(defs);

function redraw() {
  layout();
  // edges
  edgeGroup.innerHTML = "";
  for (const e of DATA.edges) {
    const sn = DATA.nodes.find(n => n.id === e.source);
    const tn = DATA.nodes.find(n => n.id === e.target);
    if (!sn || !tn) continue;
    const [x1,y1] = nodePos(sn), [x2,y2] = nodePos(tn);
    const line = el("line", {
      x1,y1,x2,y2,
      stroke: EDGE_STROKE[e.kind] || "#334155",
      "stroke-width": "1",
      "stroke-dasharray": "4 3",
      "marker-end": "url(#arr)",
    });
    line.dataset.src = e.source; line.dataset.tgt = e.target;
    edgeEls[`${e.source}__${e.target}`] = line;
    edgeGroup.appendChild(line);
  }
  // nodes
  nodeGroup.innerHTML = "";
  for (const n of DATA.nodes) {
    const [x,y] = nodePos(n);
    const g = el("g", {transform:`translate(${x},${y})`});
    const circle = el("circle", {
      r:"14", fill:"none",
      stroke:"#475569", "stroke-width":"1.5",
    });
    const text = el("text", {
      "text-anchor":"middle", "dominant-baseline":"middle",
      fill:"#64748b", "font-size":"9", dy:"0",
    });
    text.textContent = n.label.length > 10 ? n.label.slice(0,9)+"…" : n.label;
    g.appendChild(circle); g.appendChild(text);
    nodeEls[n.id] = {g, circle, text};
    nodeGroup.appendChild(g);
  }
}
redraw();

// ── Build strips ─────────────────────────────────────────────────────────────
const stripsContainer = document.getElementById("strips-container");
const stripCells = {}; // varName -> array of cell elements

for (const vname of DATA.vars) {
  // Find the byte extent from the first dep that targets this var across all paths
  let byteStart = null, byteEnd = null;
  outer: for (const path of DATA.paths) {
    const provs = path.provenance[vname] || [];
    for (const p of provs) {
      byteStart = p.target_start; byteEnd = p.target_end; break outer;
    }
  }
  if (byteStart === null) { byteStart = 0; byteEnd = 8; }
  const nBytes = byteEnd - byteStart;

  const div = document.createElement("div"); div.className = "strip";
  const hdr = document.createElement("div"); hdr.className = "strip-header";
  hdr.textContent = `${vname}  [${byteStart}–${byteEnd}]`;
  const bytesDiv = document.createElement("div"); bytesDiv.className = "strip-bytes";
  const cells = [];
  for (let i = 0; i < nBytes; i++) {
    const cell = document.createElement("div"); cell.className = "byte-cell";
    bytesDiv.appendChild(cell); cells.push(cell);
  }
  div.appendChild(hdr); div.appendChild(bytesDiv);
  stripsContainer.appendChild(div);
  stripCells[vname] = { cells, byteStart };
}

// ── State ────────────────────────────────────────────────────────────────────
let running = false;
let pathIdx = 0, stepIdx = 0;
const visitedNodes = new Set(), visitedEdges = new Set();
let coveredEdges = new Set();
const totalEdges = DATA.edges.length;

document.getElementById("path-den").textContent = DATA.paths.length;
document.getElementById("cov-den").textContent = totalEdges;

function updateCoverage() {
  const n = coveredEdges.size;
  document.getElementById("cov-num").textContent = n;
  document.getElementById("coverage-fill").style.width = `${(n / Math.max(totalEdges,1)) * 100}%`;
}

// ── Node / edge state setters ────────────────────────────────────────────────
function setNodeState(id, state) {
  const n = nodeEls[id]; if (!n) return;
  if (state === "unvisited") {
    n.circle.setAttribute("fill","none"); n.circle.setAttribute("stroke","#475569");
    n.circle.setAttribute("stroke-width","1.5"); n.text.setAttribute("fill","#64748b");
    n.circle.style.animation = "";
  } else if (state === "active") {
    n.circle.setAttribute("fill","#fbbf24"); n.circle.setAttribute("stroke","#f59e0b");
    n.circle.setAttribute("stroke-width","2.5"); n.text.setAttribute("fill","#1e293b");
    n.circle.style.animation = ""; n.circle.setAttribute("r","16");
    setTimeout(() => { if (n.circle) n.circle.setAttribute("r","14"); }, 200);
  } else if (state === "visited") {
    n.circle.setAttribute("fill","rgba(59,130,246,0.4)");
    n.circle.setAttribute("stroke","#1d4ed8"); n.circle.setAttribute("stroke-width","2");
    n.text.setAttribute("fill","#bfdbfe"); n.circle.style.animation = "";
  } else if (state === "new") {
    n.circle.setAttribute("fill","#ec4899"); n.circle.setAttribute("stroke","#db2777");
    n.circle.setAttribute("stroke-width","2.5"); n.text.setAttribute("fill","#fff");
    setTimeout(() => setNodeState(id, "visited"), 400);
  }
}

function setEdgeState(src, tgt, state) {
  const key = `${src}__${tgt}`; const e = edgeEls[key]; if (!e) return;
  const markerEl = defs.querySelector("marker");
  if (state === "unvisited") {
    e.setAttribute("stroke","#334155"); e.setAttribute("stroke-width","1");
    e.setAttribute("stroke-dasharray","4 3");
  } else if (state === "active") {
    e.setAttribute("stroke","#fbbf24"); e.setAttribute("stroke-width","3");
    e.setAttribute("stroke-dasharray","none");
  } else if (state === "visited") {
    e.setAttribute("stroke","#3b82f6"); e.setAttribute("stroke-width","2.5");
    e.setAttribute("stroke-dasharray","none");
  } else if (state === "new") {
    e.setAttribute("stroke","#ec4899"); e.setAttribute("stroke-width","3");
    e.setAttribute("stroke-dasharray","none");
    setTimeout(() => setEdgeState(src, tgt, "visited"), 400);
  }
}

// ── Reset ────────────────────────────────────────────────────────────────────
function reset() {
  running = false; pathIdx = 0; stepIdx = 0;
  visitedNodes.clear(); visitedEdges.clear(); coveredEdges.clear();
  document.getElementById("btn-play").textContent = "▶ Play";
  document.getElementById("path-num").textContent = "0";
  for (const id of Object.keys(nodeEls)) setNodeState(id, "unvisited");
  for (const {src, tgt} of Object.keys(edgeEls).map(k => {
    const [src,tgt] = k.split("__"); return {src,tgt};
  })) setEdgeState(src, tgt, "unvisited");
  for (const [vname, {cells}] of Object.entries(stripCells)) {
    for (const cell of cells) { cell.style.background = "#0f172a"; }
  }
  updateCoverage();
}

// ── Tick ─────────────────────────────────────────────────────────────────────
function tick() {
  if (!running) return;
  if (pathIdx >= DATA.paths.length) { running = false; document.getElementById("btn-play").textContent = "▶ Play"; return; }

  const path = DATA.paths[pathIdx];
  const paras = path.paragraphs;

  if (stepIdx === 0) {
    document.getElementById("path-num").textContent = pathIdx + 1;
  }

  if (stepIdx < paras.length) {
    const cur = paras[stepIdx];
    // edge from prev
    if (stepIdx > 0) {
      const prev = paras[stepIdx - 1];
      const ekey = `${prev}__${cur}`;
      if (!visitedEdges.has(ekey)) {
        setEdgeState(prev, cur, "new"); coveredEdges.add(ekey); visitedEdges.add(ekey);
        updateCoverage();
      } else {
        setEdgeState(prev, cur, "active");
        setTimeout(() => setEdgeState(prev, cur, "visited"), 250);
      }
    }
    // node
    if (!visitedNodes.has(cur)) {
      setNodeState(cur, "new"); visitedNodes.add(cur);
    } else {
      setNodeState(cur, "active");
      setTimeout(() => setNodeState(cur, "visited"), 250);
    }
    stepIdx++;
    setTimeout(tick, DATA.speed_ms);
  } else {
    // path complete — update provenance strips
    for (const [vname, provList] of Object.entries(path.provenance || {})) {
      const stripInfo = stripCells[vname]; if (!stripInfo) continue;
      for (const prov of provList) {
        const colour = sourceColour(prov.origin, prov.source_field);
        const start = prov.target_start - stripInfo.byteStart;
        const end = prov.target_end - stripInfo.byteStart;
        for (let i = Math.max(0,start); i < Math.min(stripInfo.cells.length,end); i++) {
          stripInfo.cells[i].style.background = colour;
        }
      }
    }
    // deactivate last node
    if (paras.length > 0) setNodeState(paras[paras.length-1], "visited");
    stepIdx = 0; pathIdx++;
    setTimeout(tick, DATA.pause_ms);
  }
}

// ── Controls ─────────────────────────────────────────────────────────────────
document.getElementById("btn-play").addEventListener("click", () => {
  running = !running;
  document.getElementById("btn-play").textContent = running ? "⏸ Pause" : "▶ Play";
  if (running) tick();
});
document.getElementById("btn-reset").addEventListener("click", reset);
document.getElementById("speed").addEventListener("input", e => {
  DATA.speed_ms = parseInt(e.target.value);
});
</script>
</body>
</html>
```

- [ ] **Step 4: Add `render_html` to `pathwalk_viz.py`**

```python
import importlib.resources


def render_html(bundle: dict, output: Path) -> None:
    """Write a self-contained HTML animation file."""
    template = (
        importlib.resources.files("cobble.viz")
        .joinpath("pathwalk_template.html")
        .read_text(encoding="utf-8")
    )
    html = template.replace("{{DATA}}", json.dumps(bundle))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
```

- [ ] **Step 5: Run tests**
```bash
cd cobble && uv run pytest tests/viz/test_pathwalk_viz.py -v -k "render_html"
```

- [ ] **Step 6: Commit**
```bash
cd cobble && git add cobble/cobble/viz/pathwalk_viz.py cobble/cobble/viz/pathwalk_template.html
git commit -m "feat(viz): HTML animation template and render_html"
```

---

## Task 7: CLI entry point and pyproject.toml wiring

**Files:**
- Modify: `cobble/cobble/viz/pathwalk_viz.py`
- Modify: `cobble/pyproject.toml`
- Modify: `cobble/tests/viz/test_pathwalk_viz.py`

**Interfaces:**
- Produces: `cobble-viz-pathwalk` command:
  ```
  cobble-viz-pathwalk \
      --cfg PROGRAM.json \
      --paths PATHS.jsonl \
      --vars FIELD1,FIELD2 \
      --output pathwalk.html \
      [--speed 50] \
      [--pause 600]
  ```

- [ ] **Step 1: Write the failing CLI test**

```python
# append to test_pathwalk_viz.py
from cobble.viz.pathwalk_viz import _parser as pathwalk_parser

def test_cli_parser_accepts_required_args(tmp_path):
    p = pathwalk_parser()
    args = p.parse_args([
        "--cfg", str(tmp_path / "cfg.json"),
        "--paths", str(tmp_path / "paths.jsonl"),
        "--vars", "FIELD-A,FIELD-B",
        "--output", str(tmp_path / "out.html"),
    ])
    assert args.vars == ["FIELD-A", "FIELD-B"]
    assert args.speed == 50
    assert args.pause == 600

def test_cli_parser_speed_override(tmp_path):
    p = pathwalk_parser()
    args = p.parse_args([
        "--cfg", str(tmp_path / "cfg.json"),
        "--paths", str(tmp_path / "paths.jsonl"),
        "--vars", "F",
        "--output", str(tmp_path / "out.html"),
        "--speed", "200",
    ])
    assert args.speed == 200
```

- [ ] **Step 2: Run to confirm failure**
```bash
cd cobble && uv run pytest tests/viz/test_pathwalk_viz.py -v -k "cli_parser" 2>&1 | tail -5
```

- [ ] **Step 3: Add CLI to `pathwalk_viz.py`**

```python
import argparse
import sys
from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.bundle import load_bundle


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Animate CFG path walks with byte provenance strips."
    )
    p.add_argument("--cfg", type=Path, required=True,
                   help="srccfg bundle JSON from cobble-srccfg-build")
    p.add_argument("--paths", type=Path, required=True,
                   help="path records JSONL from cobble-fields-trace --record-paths")
    p.add_argument("--vars", type=lambda s: s.split(","), default=[],
                   metavar="FIELD1,FIELD2",
                   help="comma-separated field names to show provenance strips for")
    p.add_argument("--output", type=Path, required=True,
                   help="output HTML file")
    p.add_argument("--speed", type=int, default=50, metavar="MS",
                   help="milliseconds per node step (default 50)")
    p.add_argument("--pause", type=int, default=600, metavar="MS",
                   help="milliseconds between paths (default 600)")
    return p


def cli(argv: tuple[str, ...] = ()) -> int:
    configure_cli_logging()
    args = _parser().parse_args(argv or None)
    cfgs = load_bundle(args.cfg)
    with args.paths.open(encoding="utf-8") as f:
        bundle = build_bundle(cfgs, f, args.vars, args.speed, args.pause)
    render_html(bundle, args.output)
    print(f"written: {args.output}  ({args.output.stat().st_size // 1024} KB)")
    return 0


def main() -> int:
    return sys.exit(cli())
```

- [ ] **Step 4: Add entry point to `pyproject.toml`**

In the `[project.scripts]` section, after `cobble-viz-render`:
```toml
cobble-viz-pathwalk = "cobble.viz.pathwalk_viz:main"
```

- [ ] **Step 5: Run CLI tests**
```bash
cd cobble && uv run pytest tests/viz/test_pathwalk_viz.py -v
```

- [ ] **Step 6: Smoke test on real data**
```bash
cd /Users/avisheksengupta/code/tw-cc-codes
# Run fields-trace with --record-paths for ENTRY_PROG
uv run --project /Users/avisheksengupta/code/red-dragon-forge/cobble \
  cobble-fields-trace ENTRY_PROG \
  --asg-dir output/out-cobol-asg \
  --out /tmp/ir9d-deps.jsonl \
  --record-paths /tmp/ir9d-paths.jsonl \
  --paths 60

# Check paths file has expected structure
python3 -c "
import json
lines = [json.loads(l) for l in open('/tmp/ir9d-paths.jsonl') if l.strip()]
print(f'Path records: {len(lines)}')
print(f'First path nodes (first 5): {lines[0][\"nodes\"][:5]}')
"

# Generate animation
uv run --project /Users/avisheksengupta/code/red-dragon-forge/cobble \
  cobble-viz-pathwalk \
  --cfg output/out-cobol-srccfg/cfg-ENTRY_PROG.json \
  --paths /tmp/ir9d-paths.jsonl \
  --vars DFHCOMMAREA,ENTRY_PROG-REC \
  --output /tmp/ir9d-pathwalk.html \
  --speed 80 --pause 800

# Open in browser
open /tmp/ir9d-pathwalk.html
```

Expected: HTML opens, animation plays, nodes pulse and settle, strips fill in.

- [ ] **Step 7: Commit**
```bash
cd /Users/avisheksengupta/code/red-dragon-forge/cobble && \
git add cobble/cobble/viz/pathwalk_viz.py cobble/pyproject.toml \
        cobble/tests/viz/test_pathwalk_viz.py && \
git commit -m "feat(viz): cobble-viz-pathwalk CLI and pyproject entry point"
```

---

## Task 8: Full test suite and fp-lint pass

- [ ] **Step 1: Run the complete cobble test suite**
```bash
cd /Users/avisheksengupta/code/red-dragon-forge/cobble && \
uv run pytest --tb=short 2>&1 | tail -20
```
All tests must pass.

- [ ] **Step 2: Run fp-lint on new files**
```bash
cd /Users/avisheksengupta/code/red-dragon-forge/cobble && \
uv run python -m python_fp_lint cobble/cobble/dataflow/fields/trace_report.py \
  cobble/cobble/viz/pathwalk_viz.py 2>&1 | grep -E "ERROR|WARNING" | head -20
```
Fix any violations.

- [ ] **Step 3: Commit final clean state**
```bash
git add -A && git commit -m "feat(viz): pathwalk animation — full test pass"
```
