# canonical_export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new cobble output format, `canonical_export`, that converts cobble's own `nodes.jsonl`/`edges.jsonl` into CodeConcise's canonical ingestion manifest JSON (`{version, generator, nodes: [...], edges: [...]}`), streaming and thread-pool-parallel, with bounded memory throughout.

**Architecture:** Two pure per-item transform functions (`_transform_node`, `_transform_edge`) plus a thread-safe `FileSystemSynthesizer` that deduplicates FILE/DIRECTORY nodes across the whole run. `write_manifest()` streams `nodes.jsonl` then `edges.jsonl` line-by-line in bounded chunks through a `ThreadPoolExecutor`, hand-writing the output JSON incrementally so the full manifest is never held in memory at once. A thin CLI (`cobble/canonical_export.py`) wires this to the same `--config` convention `render_graph.py` already uses.

**Tech Stack:** Python 3.11+, stdlib only (`json`, `pathlib`, `concurrent.futures`, `threading`, `argparse`) — no new dependencies.

## Global Constraints

- No `jsonschema` dependency, no schema validation step — per spec, correctness rests on the pipeline logic itself.
- Never materialize the full `nodes.jsonl`/`edges.jsonl` contents as Python lists — always stream via generators, processed in bounded chunks (default `chunk_size=200`).
- Canonical node id is always `f"{kind.value}::{raw_id}"` — applies to cobble nodes, edge endpoints, and synthesized FILE/DIRECTORY nodes alike.
- Edge `attrs` (ddname/disp/SYSIN text) are dropped entirely — canonical edges are `{from_id, to_id, type}` only.
- Every canonical node must have all schema-required keys present (`id`, `display_name`, `type`, `path`, `generator`, `category`) even though nothing validates this — `path` is `""` (not omitted) when a node has no resolved file.
- Output is written to a `.tmp` path and renamed on success, matching `GraphWriter`'s existing crash-safety convention in this codebase.

---

### Task 1: Pure node/edge transform functions

**Files:**
- Create: `cobble/knowledge_graph/canonical_export.py`
- Test: `tests/knowledge_graph/test_canonical_export.py`

**Interfaces:**
- Consumes: `cobble.interpreter.project.graph_types.{GraphNode, GraphEdge, NodeKind, EdgeKind}` (existing).
- Produces: `_canonical_id(kind: NodeKind, raw_id: str) -> str`, `_category_for(kind: NodeKind) -> list[str]`, `_language_for(kind: NodeKind) -> str | None`, `_read_file_text(path: Path) -> str`, `_transform_node(node: GraphNode, project_name: str) -> dict`, `_transform_edge(edge: GraphEdge) -> dict` — all consumed by Task 4/5.

- [ ] **Step 1: Write the failing tests**

```python
# tests/knowledge_graph/test_canonical_export.py
from pathlib import Path

from cobble.interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from cobble.knowledge_graph.canonical_export import (
    _canonical_id,
    _category_for,
    _language_for,
    _read_file_text,
    _transform_edge,
    _transform_node,
)


def test_canonical_id_prefixes_with_kind() -> None:
    assert _canonical_id(NodeKind.PROGRAM, "CBEXPORT") == "PROGRAM::CBEXPORT"
    assert _canonical_id(NodeKind.JOB, "CBEXPORT") == "JOB::CBEXPORT"


def test_category_for_code_chunk_kinds() -> None:
    for kind in (
        NodeKind.PROGRAM, NodeKind.COBOL_FILE, NodeKind.COPYBOOK, NodeKind.BMS_MAP,
        NodeKind.JOB, NodeKind.STEP, NodeKind.TRANSACTION, NodeKind.INSTREAM_DATA,
    ):
        assert _category_for(kind) == ["CODE_CHUNK"]


def test_category_for_database_kinds() -> None:
    assert _category_for(NodeKind.DATASET) == ["DATABASE"]
    assert _category_for(NodeKind.CICS_FILE) == ["DATABASE"]


def test_language_for_cobol_and_jcl_kinds() -> None:
    assert _language_for(NodeKind.PROGRAM) == "COBOL"
    assert _language_for(NodeKind.COBOL_FILE) == "COBOL"
    assert _language_for(NodeKind.COPYBOOK) == "COBOL"
    assert _language_for(NodeKind.BMS_MAP) == "COBOL"
    assert _language_for(NodeKind.JOB) == "JCL"
    assert _language_for(NodeKind.STEP) == "JCL"
    assert _language_for(NodeKind.INSTREAM_DATA) == "JCL"
    assert _language_for(NodeKind.DATASET) is None
    assert _language_for(NodeKind.TRANSACTION) is None
    assert _language_for(NodeKind.CICS_FILE) is None


def test_read_file_text_returns_contents(tmp_path: Path) -> None:
    p = tmp_path / "PROG.cbl"
    p.write_text("       IDENTIFICATION DIVISION.\n")
    assert _read_file_text(p) == "       IDENTIFICATION DIVISION.\n"


def test_read_file_text_missing_file_returns_empty_and_does_not_raise(tmp_path: Path) -> None:
    assert _read_file_text(tmp_path / "does-not-exist.cbl") == ""


def test_transform_node_with_resolved_file_path(tmp_path: Path) -> None:
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CBACT01C.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, file_path=str(src))

    result = _transform_node(node, project_name="carddemo")

    assert result["id"] == "PROGRAM::CBACT01C"
    assert result["display_name"] == "CBACT01C"
    assert result["type"] == "PROGRAM"
    assert result["path"] == str(src)
    assert result["generator"] == "cobble"
    assert result["language"] == "COBOL"
    assert result["category"] == ["CODE_CHUNK"]
    assert result["code"] == "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CBACT01C.\n"
    assert result["loc"] == 2
    assert result["cyclomatic_complexity"] == 0
    assert result["additional_properties"]["project_name"] == "carddemo"
    assert result["additional_properties"]["kind"] == "PROGRAM"


def test_transform_node_without_resolved_file_path() -> None:
    node = GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, file_path=None)

    result = _transform_node(node, project_name="carddemo")

    assert result["id"] == "DATASET::ACCT.MASTER"
    assert result["path"] == ""
    assert result["code"] == ""
    assert result["loc"] == 0
    assert result["category"] == ["DATABASE"]
    assert result["language"] is None


def test_transform_edge_prefixes_both_endpoints() -> None:
    edge = GraphEdge(
        source="CBACT01C", source_kind=NodeKind.PROGRAM,
        target="CVACT01Y", target_kind=NodeKind.COPYBOOK,
        kind=EdgeKind.COPY, attrs={"line": 42},
    )

    result = _transform_edge(edge)

    assert result == {
        "from_id": "PROGRAM::CBACT01C",
        "to_id": "COPYBOOK::CVACT01Y",
        "type": "COPY",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cobble.knowledge_graph.canonical_export'`

- [ ] **Step 3: Write the implementation**

```python
# cobble/knowledge_graph/canonical_export.py
"""canonical_export — convert cobble's own nodes.jsonl/edges.jsonl into
CodeConcise's canonical ingestion manifest JSON, alongside cobble's existing
nodes.jsonl/edges.jsonl/graph.html outputs.

Streaming and thread-pool-parallel throughout, with bounded memory — see
docs/superpowers/specs/2026-07-11-canonical-export-design.md for the full
design rationale, including the deliberate lack of schema validation.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Iterator

from cobble.interpreter.project.graph_types import GraphEdge, GraphNode, NodeKind

logger = logging.getLogger(__name__)

GENERATOR = "cobble"

_CODE_CHUNK_KINDS = frozenset({
    NodeKind.PROGRAM, NodeKind.COBOL_FILE, NodeKind.COPYBOOK, NodeKind.BMS_MAP,
    NodeKind.JOB, NodeKind.STEP, NodeKind.TRANSACTION, NodeKind.INSTREAM_DATA,
})
_DATABASE_KINDS = frozenset({NodeKind.DATASET, NodeKind.CICS_FILE})

_LANGUAGE_FOR_KIND: dict[NodeKind, str] = {
    NodeKind.PROGRAM: "COBOL",
    NodeKind.COBOL_FILE: "COBOL",
    NodeKind.COPYBOOK: "COBOL",
    NodeKind.BMS_MAP: "COBOL",
    NodeKind.JOB: "JCL",
    NodeKind.STEP: "JCL",
    NodeKind.INSTREAM_DATA: "JCL",
}


def _canonical_id(kind: NodeKind, raw_id: str) -> str:
    return f"{kind.value}::{raw_id}"


def _category_for(kind: NodeKind) -> list[str]:
    if kind in _CODE_CHUNK_KINDS:
        return ["CODE_CHUNK"]
    if kind in _DATABASE_KINDS:
        return ["DATABASE"]
    raise ValueError(f"no category mapping for {kind!r}")


def _language_for(kind: NodeKind) -> str | None:
    return _LANGUAGE_FOR_KIND.get(kind)


def _read_file_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError as exc:
        logger.warning("canonical_export: could not read %s: %s", path, exc)
        return ""


def _loc(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _transform_node(node: GraphNode, project_name: str) -> dict:
    code = _read_file_text(Path(node.file_path)) if node.file_path else ""
    return {
        "id": _canonical_id(node.kind, node.id),
        "display_name": node.id,
        "type": node.kind.value,
        "code": code,
        "path": node.file_path or "",
        "language": _language_for(node.kind),
        "generator": GENERATOR,
        "loc": _loc(code),
        "cyclomatic_complexity": 0,
        "category": _category_for(node.kind),
        "additional_properties": {
            **node.attrs,
            "kind": node.kind.value,
            "project_name": project_name,
        },
    }


def _transform_edge(edge: GraphEdge) -> dict:
    return {
        "from_id": _canonical_id(edge.source_kind, edge.source),
        "to_id": _canonical_id(edge.target_kind, edge.target),
        "type": edge.kind.value,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/code/cobble
git add cobble/knowledge_graph/canonical_export.py tests/knowledge_graph/test_canonical_export.py
git commit -m "cobble: add canonical_export node/edge transform functions"
```

---

### Task 2: Streaming JSONL readers

**Files:**
- Modify: `cobble/knowledge_graph/canonical_export.py`
- Test: `tests/knowledge_graph/test_canonical_export.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind` (existing); the `nodes.jsonl`/`edges.jsonl` line shape already written by `GraphWriter` (`{id, kind, file_path, attrs}` / `{source, source_kind, target, target_kind, kind, attrs}`).
- Produces: `_stream_nodes(path: Path) -> Iterator[GraphNode]`, `_stream_edges(path: Path) -> Iterator[GraphEdge]` — consumed by Task 5 (`write_manifest`).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/knowledge_graph/test_canonical_export.py
import json

from cobble.knowledge_graph.canonical_export import _stream_edges, _stream_nodes


def test_stream_nodes_yields_graphnode_per_line(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    nodes_path.write_text(
        json.dumps({"id": "CBACT01C", "kind": "PROGRAM", "file_path": "a/CBACT01C.cbl", "attrs": {}}) + "\n"
        + json.dumps({"id": "ACCT.MASTER", "kind": "DATASET", "file_path": None, "attrs": {}}) + "\n"
    )

    nodes = list(_stream_nodes(nodes_path))

    assert nodes == [
        GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, file_path="a/CBACT01C.cbl"),
        GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, file_path=None),
    ]


def test_stream_nodes_is_a_generator_not_a_list(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    nodes_path.write_text(json.dumps({"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}) + "\n")

    result = _stream_nodes(nodes_path)

    assert not isinstance(result, list)
    assert isinstance(result, Iterator)


def test_stream_edges_yields_graphedge_per_line(tmp_path: Path) -> None:
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text(
        json.dumps({
            "source": "CBACT01C", "source_kind": "PROGRAM",
            "target": "CVACT01Y", "target_kind": "COPYBOOK",
            "kind": "COPY", "attrs": {"line": 42},
        }) + "\n"
    )

    edges = list(_stream_edges(edges_path))

    assert edges == [
        GraphEdge(
            source="CBACT01C", source_kind=NodeKind.PROGRAM,
            target="CVACT01Y", target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY, attrs={"line": 42},
        )
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v -k stream`
Expected: FAIL with `ImportError: cannot import name '_stream_nodes'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/knowledge_graph/canonical_export.py` (add `EdgeKind` to the existing `graph_types` import):

```python
from cobble.interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def _stream_nodes(path: Path) -> Iterator[GraphNode]:
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            yield GraphNode(
                id=row["id"], kind=NodeKind(row["kind"]),
                file_path=row.get("file_path"), attrs=row.get("attrs", {}),
            )


def _stream_edges(path: Path) -> Iterator[GraphEdge]:
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            yield GraphEdge(
                source=row["source"], source_kind=NodeKind(row["source_kind"]),
                target=row["target"], target_kind=NodeKind(row["target_kind"]),
                kind=EdgeKind(row["kind"]), attrs=row.get("attrs", {}),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/code/cobble
git add cobble/knowledge_graph/canonical_export.py tests/knowledge_graph/test_canonical_export.py
git commit -m "cobble: add streaming JSONL readers to canonical_export"
```

---

### Task 3: FileSystemSynthesizer (thread-safe FILE/DIRECTORY dedup)

**Files:**
- Modify: `cobble/knowledge_graph/canonical_export.py`
- Test: `tests/knowledge_graph/test_canonical_export.py`

**Interfaces:**
- Consumes: `_canonical_id` (Task 1).
- Produces: `class FileSystemSynthesizer` with `synthesize_for_node(canonical_node_id: str, file_path: str) -> list[dict]` (returns newly-created FILE/DIRECTORY node dicts; appends MADE_OF edges internally) and `drain_edges() -> list[dict]` (returns and clears all accumulated MADE_OF edges) — both consumed by Task 4 (`_process_node`) and Task 5 (`write_manifest`).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/knowledge_graph/test_canonical_export.py
import threading

from cobble.knowledge_graph.canonical_export import FileSystemSynthesizer


def test_synthesize_for_node_creates_file_and_directory_chain() -> None:
    fs = FileSystemSynthesizer()

    new_nodes = fs.synthesize_for_node("PROGRAM::CBACT01C", "vendor/carddemo/app/cbl/CBACT01C.cbl")

    ids = {n["id"] for n in new_nodes}
    assert ids == {
        "DIRECTORY::vendor",
        "DIRECTORY::vendor/carddemo",
        "DIRECTORY::vendor/carddemo/app",
        "DIRECTORY::vendor/carddemo/app/cbl",
        "FILE::vendor/carddemo/app/cbl/CBACT01C.cbl",
    }
    for n in new_nodes:
        assert n["category"] == ["FILE_SYSTEM"]
        assert n["generator"] == "cobble"

    edges = fs.drain_edges()
    edge_pairs = {(e["from_id"], e["to_id"]) for e in edges}
    assert edge_pairs == {
        ("DIRECTORY::vendor", "DIRECTORY::vendor/carddemo"),
        ("DIRECTORY::vendor/carddemo", "DIRECTORY::vendor/carddemo/app"),
        ("DIRECTORY::vendor/carddemo/app", "DIRECTORY::vendor/carddemo/app/cbl"),
        ("DIRECTORY::vendor/carddemo/app/cbl", "FILE::vendor/carddemo/app/cbl/CBACT01C.cbl"),
        ("FILE::vendor/carddemo/app/cbl/CBACT01C.cbl", "PROGRAM::CBACT01C"),
    }
    assert all(e["type"] == "MADE_OF" for e in edges)


def test_synthesize_for_node_dedups_shared_directories_and_file() -> None:
    fs = FileSystemSynthesizer()
    fs.synthesize_for_node("JOB::ACCTFILE", "vendor/carddemo/app/jcl/ACCTFILE.jcl")

    # A second node in the same file: only the new FILE->node edge and node
    # itself are new; the FILE/DIRECTORY chain is not re-emitted.
    new_nodes = fs.synthesize_for_node("STEP::ACCTFILE.STEP05", "vendor/carddemo/app/jcl/ACCTFILE.jcl")

    assert new_nodes == []
    edges = fs.drain_edges()
    assert edges == [{
        "from_id": "FILE::vendor/carddemo/app/jcl/ACCTFILE.jcl",
        "to_id": "STEP::ACCTFILE.STEP05",
        "type": "MADE_OF",
    }]


def test_drain_edges_clears_accumulated_edges() -> None:
    fs = FileSystemSynthesizer()
    fs.synthesize_for_node("PROGRAM::A", "a.cbl")
    assert len(fs.drain_edges()) > 0
    assert fs.drain_edges() == []


def test_synthesize_for_node_is_thread_safe_no_duplicate_nodes() -> None:
    fs = FileSystemSynthesizer()
    results: list[list[dict]] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        new_nodes = fs.synthesize_for_node(f"PROGRAM::P{i}", "shared/dir/PROG.cbl")
        with lock:
            results.append(new_nodes)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_new_node_ids = [n["id"] for batch in results for n in batch]
    file_node_emissions = [i for i in all_new_node_ids if i == "FILE::shared/dir/PROG.cbl"]
    assert len(file_node_emissions) == 1  # emitted exactly once across all 20 threads
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v -k synthesize_for_node or drain_edges`
Expected: FAIL with `ImportError: cannot import name 'FileSystemSynthesizer'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/knowledge_graph/canonical_export.py`:

```python
class FileSystemSynthesizer:
    """Thread-safe FILE/DIRECTORY node+edge synthesis, deduplicated across
    the whole export run. Bounded by unique file/directory count, not node
    count — see design spec's "Pipeline architecture" section."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen_node_ids: set[str] = set()
        self._edges: list[dict] = []

    def synthesize_for_node(self, canonical_node_id: str, file_path: str) -> list[dict]:
        parts = Path(file_path).parts
        new_nodes: list[dict] = []
        prefix = ""
        prev_id: str | None = None
        with self._lock:
            for i, part in enumerate(parts):
                prefix = f"{prefix}/{part}" if prefix else part
                is_file = i == len(parts) - 1
                node_type = "FILE" if is_file else "DIRECTORY"
                node_id = f"{node_type}::{prefix}"
                if node_id not in self._seen_node_ids:
                    self._seen_node_ids.add(node_id)
                    new_nodes.append({
                        "id": node_id,
                        "display_name": part,
                        "type": node_type,
                        "code": "",
                        "path": prefix,
                        "language": None,
                        "generator": GENERATOR,
                        "loc": 0,
                        "cyclomatic_complexity": 0,
                        "category": ["FILE_SYSTEM"],
                        "additional_properties": {},
                    })
                    if prev_id is not None:
                        self._edges.append({"from_id": prev_id, "to_id": node_id, "type": "MADE_OF"})
                prev_id = node_id
            # FILE -> owning node: always new (canonical_node_id is unique per node).
            self._edges.append({"from_id": prev_id, "to_id": canonical_node_id, "type": "MADE_OF"})
        return new_nodes

    def drain_edges(self) -> list[dict]:
        with self._lock:
            edges, self._edges = self._edges, []
        return edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/code/cobble
git add cobble/knowledge_graph/canonical_export.py tests/knowledge_graph/test_canonical_export.py
git commit -m "cobble: add thread-safe FileSystemSynthesizer to canonical_export"
```

---

### Task 4: Per-node processing (transform + FILE_SYSTEM synthesis glue)

**Files:**
- Modify: `cobble/knowledge_graph/canonical_export.py`
- Test: `tests/knowledge_graph/test_canonical_export.py`

**Interfaces:**
- Consumes: `_transform_node` (Task 1), `FileSystemSynthesizer.synthesize_for_node` (Task 3).
- Produces: `_process_node(node: GraphNode, project_name: str, fs: FileSystemSynthesizer) -> list[dict]` — consumed by Task 5 (`write_manifest`).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/knowledge_graph/test_canonical_export.py
from cobble.knowledge_graph.canonical_export import _process_node


def test_process_node_with_file_path_returns_node_plus_filesystem_nodes(tmp_path: Path) -> None:
    src = tmp_path / "CBACT01C.cbl"
    src.write_text("       IDENTIFICATION DIVISION.\n")
    node = GraphNode(id="CBACT01C", kind=NodeKind.PROGRAM, file_path=str(src))
    fs = FileSystemSynthesizer()

    results = _process_node(node, "carddemo", fs)

    ids = {r["id"] for r in results}
    assert "PROGRAM::CBACT01C" in ids
    assert any(r["type"] == "FILE" for r in results)
    own_node = next(r for r in results if r["id"] == "PROGRAM::CBACT01C")
    assert own_node["code"] == "       IDENTIFICATION DIVISION.\n"
    # The FILE -> node MADE_OF edge is now buffered on the synthesizer.
    edge_targets = {e["to_id"] for e in fs.drain_edges()}
    assert "PROGRAM::CBACT01C" in edge_targets


def test_process_node_without_file_path_returns_only_the_node() -> None:
    node = GraphNode(id="ACCT.MASTER", kind=NodeKind.DATASET, file_path=None)
    fs = FileSystemSynthesizer()

    results = _process_node(node, "carddemo", fs)

    assert len(results) == 1
    assert results[0]["id"] == "DATASET::ACCT.MASTER"
    assert fs.drain_edges() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v -k process_node`
Expected: FAIL with `ImportError: cannot import name '_process_node'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/knowledge_graph/canonical_export.py`:

```python
def _process_node(node: GraphNode, project_name: str, fs: FileSystemSynthesizer) -> list[dict]:
    canonical_node = _transform_node(node, project_name)
    results = [canonical_node]
    if node.file_path:
        results.extend(fs.synthesize_for_node(canonical_node["id"], node.file_path))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/code/cobble
git add cobble/knowledge_graph/canonical_export.py tests/knowledge_graph/test_canonical_export.py
git commit -m "cobble: add _process_node glue to canonical_export"
```

---

### Task 5: write_manifest — streaming, parallel, bounded-memory orchestration

**Files:**
- Modify: `cobble/knowledge_graph/canonical_export.py`
- Test: `tests/knowledge_graph/test_canonical_export.py`

**Interfaces:**
- Consumes: `_stream_nodes`, `_stream_edges` (Task 2), `_process_node` (Task 4), `_transform_edge` (Task 1), `FileSystemSynthesizer` (Task 3).
- Produces: `write_manifest(nodes_path: Path, edges_path: Path, output_path: Path, project_name: str, *, chunk_size: int = 200, max_workers: int = 8) -> None` — consumed by Task 6 (CLI entrypoint).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/knowledge_graph/test_canonical_export.py
from cobble.knowledge_graph.canonical_export import write_manifest


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_write_manifest_produces_valid_json_with_expected_shape(tmp_path: Path) -> None:
    cbl = tmp_path / "CBACT01C.cbl"
    cbl.write_text("       IDENTIFICATION DIVISION.\n")
    cpy = tmp_path / "CVACT01Y.cpy"
    cpy.write_text("       01 ACCT-RECORD.\n")

    nodes_path = tmp_path / "nodes.jsonl"
    _write_jsonl(nodes_path, [
        {"id": "CBACT01C", "kind": "PROGRAM", "file_path": str(cbl), "attrs": {}},
        {"id": "CVACT01Y", "kind": "COPYBOOK", "file_path": str(cpy), "attrs": {}},
        {"id": "ACCT.MASTER", "kind": "DATASET", "file_path": None, "attrs": {}},
    ])
    edges_path = tmp_path / "edges.jsonl"
    _write_jsonl(edges_path, [
        {"source": "CBACT01C", "source_kind": "PROGRAM",
         "target": "CVACT01Y", "target_kind": "COPYBOOK",
         "kind": "COPY", "attrs": {}},
    ])
    output_path = tmp_path / "manifest.json"

    write_manifest(nodes_path, edges_path, output_path, "carddemo", chunk_size=2, max_workers=2)

    manifest = json.loads(output_path.read_text())
    assert manifest["version"] == "1.0"
    assert manifest["generator"] == "cobble"

    node_ids = {n["id"] for n in manifest["nodes"]}
    assert "PROGRAM::CBACT01C" in node_ids
    assert "COPYBOOK::CVACT01Y" in node_ids
    assert "DATASET::ACCT.MASTER" in node_ids
    assert any(n["type"] == "FILE" for n in manifest["nodes"])

    edge_pairs = {(e["from_id"], e["to_id"], e["type"]) for e in manifest["edges"]}
    assert ("PROGRAM::CBACT01C", "COPYBOOK::CVACT01Y", "COPY") in edge_pairs
    # FILE -> node MADE_OF edges are present for both file-backed nodes.
    assert any(e["type"] == "MADE_OF" and e["to_id"] == "PROGRAM::CBACT01C" for e in manifest["edges"])
    assert any(e["type"] == "MADE_OF" and e["to_id"] == "COPYBOOK::CVACT01Y" for e in manifest["edges"])


def test_write_manifest_no_duplicate_node_ids(tmp_path: Path) -> None:
    cbl = tmp_path / "sub" / "CBACT01C.cbl"
    cbl.parent.mkdir()
    cbl.write_text("x\n")
    nodes_path = tmp_path / "nodes.jsonl"
    _write_jsonl(nodes_path, [
        {"id": "CBACT01C", "kind": "PROGRAM", "file_path": str(cbl), "attrs": {}},
        {"id": "CBACT01C.STEP", "kind": "STEP", "file_path": str(cbl), "attrs": {}},
    ])
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text("")
    output_path = tmp_path / "manifest.json"

    write_manifest(nodes_path, edges_path, output_path, "carddemo", chunk_size=1, max_workers=4)

    manifest = json.loads(output_path.read_text())
    node_ids = [n["id"] for n in manifest["nodes"]]
    assert len(node_ids) == len(set(node_ids))  # no duplicates despite shared file


def test_write_manifest_writes_to_tmp_then_renames(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.jsonl"
    _write_jsonl(nodes_path, [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    edges_path = tmp_path / "edges.jsonl"
    edges_path.write_text("")
    output_path = tmp_path / "manifest.json"

    write_manifest(nodes_path, edges_path, output_path, "carddemo")

    assert output_path.exists()
    assert not output_path.with_suffix(".json.tmp").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v -k write_manifest`
Expected: FAIL with `ImportError: cannot import name 'write_manifest'`

- [ ] **Step 3: Write the implementation**

Add to `cobble/knowledge_graph/canonical_export.py` (add `from concurrent.futures import ThreadPoolExecutor`, `from functools import partial`, and `Iterable` to the existing `from typing import Iterator` line):

```python
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Iterable, Iterator  # replaces the Task 1 `from typing import Iterator` line


def _chunked(iterable: Iterable, size: int) -> Iterator[list]:
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def write_manifest(
    nodes_path: Path,
    edges_path: Path,
    output_path: Path,
    project_name: str,
    *,
    chunk_size: int = 200,
    max_workers: int = 8,
) -> None:
    fs = FileSystemSynthesizer()
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with tmp_path.open("w") as f:
        f.write(f'{{"version": "1.0", "generator": "{GENERATOR}", "nodes": [')
        first = True
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            process = partial(_process_node, project_name=project_name, fs=fs)
            for chunk in _chunked(_stream_nodes(nodes_path), chunk_size):
                for node_results in pool.map(process, chunk):
                    for node_dict in node_results:
                        if not first:
                            f.write(",")
                        f.write(json.dumps(node_dict))
                        first = False

        f.write('], "edges": [')
        first = True
        for edge_dict in fs.drain_edges():
            if not first:
                f.write(",")
            f.write(json.dumps(edge_dict))
            first = False
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for chunk in _chunked(_stream_edges(edges_path), chunk_size):
                for edge_dict in pool.map(_transform_edge, chunk):
                    if not first:
                        f.write(",")
                    f.write(json.dumps(edge_dict))
                    first = False
        f.write("]}")

    tmp_path.rename(output_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/code/cobble && uv run pytest tests/knowledge_graph/test_canonical_export.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/code/cobble
git add cobble/knowledge_graph/canonical_export.py tests/knowledge_graph/test_canonical_export.py
git commit -m "cobble: add write_manifest streaming orchestration to canonical_export"
```

---

### Task 6: CLI entrypoint

**Files:**
- Create: `cobble/canonical_export.py`
- Test: `tests/test_canonical_export_cli.py`

**Interfaces:**
- Consumes: `cobble.corpus_config.load_corpus_config` (existing), `cobble.knowledge_graph.canonical_export.write_manifest` (Task 5).
- Produces: `_parse_args() -> argparse.Namespace`, `main() -> int` — the `uv run python -m cobble.canonical_export` entrypoint.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_canonical_export_cli.py
import json
import sys
from pathlib import Path

import pytest

from cobble import canonical_export


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n" if rows else "")


def _write_config(tmp_path: Path, out_dir: Path) -> Path:
    config_path = tmp_path / "carddemo.yaml"
    config_path.write_text(
        "corpus:\n"
        f"  cobol_dir: {tmp_path}\n"
        '  cobol_globs: ["*.cbl"]\n'
        f"  jcl_dir: {tmp_path}\n"
        '  jcl_globs: ["*.jcl"]\n'
        '  copybook_dirs: []\n'
        f"  out_dir: {out_dir}\n"
    )
    return config_path


def test_main_reads_config_out_dir_and_writes_manifest_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(sys, "argv", ["canonical_export", "--config", str(config_path)])
    exit_code = canonical_export.main()

    assert exit_code == 0
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["nodes"][0]["id"] == "PROGRAM::A"


def test_main_defaults_project_name_to_config_stem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(sys, "argv", ["canonical_export", "--config", str(config_path)])
    canonical_export.main()

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["nodes"][0]["additional_properties"]["project_name"] == "carddemo"


def test_main_accepts_explicit_project_name_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _write_jsonl(out_dir / "nodes.jsonl", [{"id": "A", "kind": "PROGRAM", "file_path": None, "attrs": {}}])
    _write_jsonl(out_dir / "edges.jsonl", [])
    config_path = _write_config(tmp_path, out_dir)

    monkeypatch.setattr(
        sys, "argv",
        ["canonical_export", "--config", str(config_path), "--project-name", "custom-name"],
    )
    canonical_export.main()

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["nodes"][0]["additional_properties"]["project_name"] == "custom-name"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/code/cobble && uv run pytest tests/test_canonical_export_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cobble.canonical_export'`

- [ ] **Step 3: Write the implementation**

```python
# cobble/canonical_export.py
"""canonical_export — render <out_dir>/nodes.jsonl + <out_dir>/edges.jsonl
(produced by cobble.build_graph) as CodeConcise's canonical ingestion
manifest at <out_dir>/manifest.json.

out_dir comes from the same --config YAML build_graph.py/render_graph.py
use (its `corpus.out_dir` field) -- nothing about a specific corpus is
hardcoded here.

Invoke as: uv run python -m cobble.canonical_export --config <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cobble.corpus_config import load_corpus_config
from cobble.knowledge_graph.canonical_export import write_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, type=Path,
        help="Path to a corpus YAML config (see cobble/corpus_config.py / config/carddemo.yaml)",
    )
    parser.add_argument(
        "--project-name", default=None,
        help="Defaults to the --config file's stem, e.g. 'carddemo' for config/carddemo.yaml",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_corpus_config(args.config)
    project_name = args.project_name or args.config.stem

    nodes_jsonl = config.out_dir / "nodes.jsonl"
    edges_jsonl = config.out_dir / "edges.jsonl"
    output_path = config.out_dir / "manifest.json"

    write_manifest(nodes_jsonl, edges_jsonl, output_path, project_name)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/code/cobble && uv run pytest tests/test_canonical_export_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/code/cobble
git add cobble/canonical_export.py tests/test_canonical_export_cli.py
git commit -m "cobble: add canonical_export CLI entrypoint"
```

---

### Task 7: End-to-end verification against the real CardDemo corpus

**Files:** none created — verification only, run from `~/code/cobble`.

**Interfaces:**
- Consumes: `cobble/canonical_export.py` (Task 6), the existing `out/nodes.jsonl`/`out/edges.jsonl` produced by `make build CONFIG=config/carddemo.yaml`.
- Produces: nothing new — this task is a verification checkpoint before considering the feature done.

- [ ] **Step 1: Run the full test suite**

Run: `cd ~/code/cobble && uv run pytest tests/ -q`
Expected: all tests pass, including the ~26 new tests from Tasks 1-6.

- [ ] **Step 2: Regenerate nodes.jsonl/edges.jsonl from the real corpus** (skip if `out/nodes.jsonl` is already current)

Run:
```bash
cd ~/code/cobble
PROLEAP_BRIDGE_JAR=$(pwd)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run python -m cobble.build_graph --config config/carddemo.yaml
```
Expected: `Merged graph: 449 nodes, 803 edges` (matches `reference/`).

- [ ] **Step 3: Run canonical_export against the real corpus**

Run: `cd ~/code/cobble && uv run python -m cobble.canonical_export --config config/carddemo.yaml`
Expected: `Wrote out/manifest.json`, completes without exceptions.

- [ ] **Step 4: Sanity-check the output**

Run:
```bash
cd ~/code/cobble
uv run python3 -c "
import json
m = json.load(open('out/manifest.json'))
print('version:', m['version'], 'generator:', m['generator'])
print('nodes:', len(m['nodes']), 'edges:', len(m['edges']))
node_ids = [n['id'] for n in m['nodes']]
print('duplicate node ids:', len(node_ids) - len(set(node_ids)))
by_type = {}
for n in m['nodes']:
    by_type[n['type']] = by_type.get(n['type'], 0) + 1
print('nodes by type:', by_type)
made_of = sum(1 for e in m['edges'] if e['type'] == 'MADE_OF')
print('MADE_OF edges (FILE_SYSTEM structure):', made_of)
"
```
Expected: `duplicate node ids: 0`; `nodes by type` includes `FILE`, `DIRECTORY`, and all the original cobble kinds; `MADE_OF edges` count is well above the original cobble edge count (directory chains + FILE->node edges layered on top).

- [ ] **Step 5: Commit** (only if Steps 1-4 required code fixes; otherwise this task produces no diff)

```bash
cd ~/code/cobble
git add -A
git commit -m "cobble: fix issues found during canonical_export end-to-end verification"
```
