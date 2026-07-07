# COBOL/CICS/JCL Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect red-dragon's CALL/COPY graph, cicada's CICS transaction flow, and a new JCL step-sequencing extractor into one queryable, visualizable knowledge graph over CardDemo.

**Architecture:** A shared `GraphNode`/`GraphEdge` schema lives in red-dragon (the one package every consumer already depends on). `cobol_connections.py` (red-dragon) and `flow_map.py` (cicada) are modified to emit it; a new extractor in jackal walks its already-parsed JCL `Job` model to emit it too. A new `knowledge_graph` package in red-dragon-forge merges all three into one `networkx.MultiDiGraph`, exposes query helpers, exports to NDJSON, and renders a self-contained interactive HTML visualization.

**Tech Stack:** Python, networkx (new dependency in red-dragon-forge), vis-network (vendored JS, MIT-licensed), pytest, import-linter.

## Global Constraints

- Node identity is `(NodeKind, id)`; `id` is a **logical name** (program-id, copybook name, transaction-id, `JOBNAME.STEPNAME`, dataset name, `MAPSET.MAP`), never a file path. All ids are **uppercased** at extraction time.
- `GraphEdge` carries `source_kind`/`target_kind` explicitly (not derivable from `EdgeKind` alone — see the spec's "fix" commit `8b459ca1`).
- No new graph database server. Backend is in-memory `networkx.MultiDiGraph` + NDJSON export.
- No new COBOL/CICS/JCL parsing — every extractor reshapes data an existing, tested component already parses. The JCL extractor is the one genuinely new piece of extraction logic (it's new *graph-shaping*, not new *parsing* — `jackal/jcl/parser.py:parse_jcl` already exists).
- `knowledge_graph` depends on red-dragon, cicada, squall, jackal; none of `cics`, `squall`, `jackal` may import `knowledge_graph` (import-linter contract, Task 5).
- DISP→edge-kind heuristic: `NEW`→WRITES, `OLD`→UPDATES, `SHR`→READS, `MOD`→WRITES. Raw `DispStatus` is always kept in the edge's `attrs["disp"]`.
- `TempRef`/`BackwardRef` DDs and `sysout=True` DDs never become DATASET nodes (no stable cross-job identity).
- Visualization: one self-contained HTML file, vis-network inlined (no CDN, no server), filterable by node/edge kind, click-to-highlight-neighbors.

---

## Task 1: Shared graph schema (red-dragon)

**Files:**
- Create: `interpreter/project/graph_types.py`
- Test: `tests/unit/project/test_graph_types.py`

**Interfaces:**
- Produces: `NodeKind` (enum), `EdgeKind` (enum), `GraphNode(id, kind, file_path=None, attrs={})`, `GraphEdge(source, source_kind, target, target_kind, kind, attrs={})` — all subsequent tasks import these from `interpreter.project.graph_types`.

This repo is `~/code/red-dragon-forge`; this task's files are under `~/code/red-dragon-forge/vendor/red-dragon/` (the shared RedDragon submodule).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/project/test_graph_types.py
"""Unit tests for the shared knowledge-graph node/edge schema."""

from tests.covers import covers, NotLanguageFeature
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_node_kind_has_expected_members():
    assert {k.value for k in NodeKind} == {
        "PROGRAM",
        "COPYBOOK",
        "TRANSACTION",
        "JOB",
        "STEP",
        "DATASET",
        "BMS_MAP",
    }


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_edge_kind_has_expected_members():
    assert {k.value for k in EdgeKind} == {
        "CALL",
        "COPY",
        "XCTL",
        "LINK",
        "RETURN_TRANSID",
        "STARTS",
        "SENDS_MAP",
        "RECEIVES_MAP",
        "JCL_STEP_RUNS",
        "READS",
        "WRITES",
        "UPDATES",
    }


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_graph_node_defaults():
    node = GraphNode(id="COSGN00C", kind=NodeKind.PROGRAM)
    assert node.file_path is None
    assert node.attrs == {}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_graph_node_stores_file_path_and_attrs():
    node = GraphNode(
        id="COSGN00C",
        kind=NodeKind.PROGRAM,
        file_path="/src/COSGN00C.cbl",
        attrs={"parm": "X"},
    )
    assert node.file_path == "/src/COSGN00C.cbl"
    assert node.attrs == {"parm": "X"}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_graph_edge_defaults():
    edge = GraphEdge(
        source="MAIN",
        source_kind=NodeKind.PROGRAM,
        target="SUB",
        target_kind=NodeKind.PROGRAM,
        kind=EdgeKind.CALL,
    )
    assert edge.attrs == {}


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_graph_edge_stores_kind_source_target():
    edge = GraphEdge(
        source="MAIN",
        source_kind=NodeKind.PROGRAM,
        target="SUB",
        target_kind=NodeKind.PROGRAM,
        kind=EdgeKind.CALL,
    )
    assert edge.source == "MAIN"
    assert edge.source_kind is NodeKind.PROGRAM
    assert edge.target == "SUB"
    assert edge.target_kind is NodeKind.PROGRAM
    assert edge.kind is EdgeKind.CALL
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `~/code/red-dragon-forge`): `uv run --no-sync python -m pytest vendor/red-dragon/tests/unit/project/test_graph_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'interpreter.project.graph_types'`

- [ ] **Step 3: Write the implementation**

```python
# interpreter/project/graph_types.py
"""Shared node/edge schema for the COBOL/CICS/JCL knowledge graph.

Every source in the codebase (a COBOL program, a copybook, a CICS
transaction, a JCL job/step, a dataset, a BMS map) is a GraphNode; every
relationship between them (CALL, COPY, XCTL, JCL step sequencing, dataset
access, ...) is a GraphEdge. Node identity is (kind, id) — id is a logical
name (program-id, transaction-id, "JOBNAME.STEPNAME", ...), never a file
path, and is uppercased by every extractor at extraction time.

Consumers: interpreter.project.cobol_connections (this repo), cics.flow_map
(cicada), a new jackal JCL extractor, and red-dragon-forge's knowledge_graph
package, which merges all three into one graph. This module has no
knowledge of any of them — it is pure vocabulary, the same role
interpreter.project.coprocessor_compile plays for CoprocessorSpec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeKind(Enum):
    PROGRAM = "PROGRAM"
    COPYBOOK = "COPYBOOK"
    TRANSACTION = "TRANSACTION"
    JOB = "JOB"
    STEP = "STEP"
    DATASET = "DATASET"
    BMS_MAP = "BMS_MAP"


class EdgeKind(Enum):
    CALL = "CALL"
    COPY = "COPY"
    XCTL = "XCTL"
    LINK = "LINK"
    RETURN_TRANSID = "RETURN_TRANSID"
    STARTS = "STARTS"
    SENDS_MAP = "SENDS_MAP"
    RECEIVES_MAP = "RECEIVES_MAP"
    JCL_STEP_RUNS = "JCL_STEP_RUNS"
    READS = "READS"
    WRITES = "WRITES"
    UPDATES = "UPDATES"


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    file_path: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    source_kind: NodeKind
    target: str
    target_kind: NodeKind
    kind: EdgeKind
    attrs: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest vendor/red-dragon/tests/unit/project/test_graph_types.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd vendor/red-dragon
git add interpreter/project/graph_types.py tests/unit/project/test_graph_types.py
git commit -m "feat: add shared GraphNode/GraphEdge schema for the knowledge graph"
cd ../..
```

---

## Task 2: Refactor cobol_connections.py to emit the shared schema (red-dragon)

**Files:**
- Modify: `interpreter/project/cobol_connections.py` (full rewrite)
- Modify: `tests/integration/project/test_cobol_connections.py` (full rewrite)
- Delete: `tests/unit/project/test_cobol_connections.py` (tested `ProgramRef`/`Connection`, which no longer exist — their coverage is superseded by Task 1's `test_graph_types.py`)
- Test (unchanged, still passes): `tests/unit/project/test_cobol_connections_defaults.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind` from Task 1.
- Produces: `extract_cobol_connections(...) -> tuple[list[GraphNode], list[GraphEdge]]` (breaking change — previously returned `list[Connection]`; `ProgramRef`/`Connection` are removed). Task 9's integration test calls this function with this exact signature.

This is a breaking rewrite, not an additive change: `ProgramRef`/`Connection` are redundant with `GraphNode`/`GraphEdge` (a strict subset, one-to-one), so keeping both would be pure duplication. The one dropped feature is `Connection.to_json()` — NDJSON serialization is now `knowledge_graph/export.py`'s job (Task 7), not this module's.

- [ ] **Step 1: Delete the now-obsolete unit test file**

```bash
cd vendor/red-dragon
rm tests/unit/project/test_cobol_connections.py
```

- [ ] **Step 2: Rewrite the integration test file to use the new return shape**

```python
# tests/integration/project/test_cobol_connections.py
"""Integration tests for extract_cobol_connections().

Tests use inline COBOL source (extra_subprogram_sources) for CALL connections
and tmp_path fixture files for COPY connections (ProLeap resolves COPY on disk).

TestFixtureProject exercises the full on-disk pipeline against
tests/fixtures/projects/cobol_connections_demo/ — the durable e2e case.
"""

from pathlib import Path

import pytest

from tests.covers import covers, NotLanguageFeature
from interpreter.cobol.cobol_parser import make_cobol_parser
from interpreter.project.cobol_connections import extract_cobol_connections
from interpreter.project.graph_types import EdgeKind, NodeKind

_MAIN_CALL = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       PROCEDURE DIVISION.
           CALL 'HELPER'.
           GOBACK.
"""

_HELPER = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELPER.
       PROCEDURE DIVISION.
           GOBACK.
"""


@pytest.fixture
def cobol_parser():
    """Fixture providing a COBOL parser for all tests."""
    return make_cobol_parser()


class TestCallConnections:
    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_call_connection_detected(self, cobol_parser):
        _nodes, edges = extract_cobol_connections(
            _MAIN_CALL,
            extra_subprogram_sources={"HELPER": _HELPER},
            parser=cobol_parser,
        )
        call_edges = [e for e in edges if e.kind == EdgeKind.CALL]
        assert len(call_edges) == 1
        assert call_edges[0].source == "MAIN"
        assert call_edges[0].target == "HELPER"

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_call_target_file_path_resolved(self, cobol_parser):
        nodes, _edges = extract_cobol_connections(
            _MAIN_CALL,
            extra_subprogram_sources={"HELPER": _HELPER},
            parser=cobol_parser,
        )
        helper = next(
            n for n in nodes if n.kind == NodeKind.PROGRAM and n.id == "HELPER"
        )
        assert helper.file_path is not None
        assert Path(helper.file_path).stem.upper() == "HELPER"

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_no_connections_for_standalone_program(self, cobol_parser):
        src = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. STANDALONE.
       PROCEDURE DIVISION.
           GOBACK.
"""
        nodes, edges = extract_cobol_connections(src, parser=cobol_parser)
        assert edges == []
        assert [n.id for n in nodes] == ["STANDALONE"]

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_returns_node_and_edge_lists(self, cobol_parser):
        nodes, edges = extract_cobol_connections(
            _MAIN_CALL,
            extra_subprogram_sources={"HELPER": _HELPER},
            parser=cobol_parser,
        )
        assert isinstance(nodes, list)
        assert isinstance(edges, list)
        assert all(n.kind is NodeKind.PROGRAM for n in nodes)
        assert all(e.kind is EdgeKind.CALL for e in edges)

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_transitive_calls_included(self, cobol_parser):
        """A calls B, B calls C — all three connections returned."""
        prog_a = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGA.
       PROCEDURE DIVISION.
           CALL 'PROGB'.
           GOBACK.
"""
        prog_b = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGB.
       PROCEDURE DIVISION.
           CALL 'PROGC'.
           GOBACK.
"""
        prog_c = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROGC.
       PROCEDURE DIVISION.
           GOBACK.
"""
        nodes, edges = extract_cobol_connections(
            prog_a,
            extra_subprogram_sources={"PROGB": prog_b, "PROGC": prog_c},
            parser=cobol_parser,
        )
        call_edges = [e for e in edges if e.kind == EdgeKind.CALL]
        pairs = {(e.source, e.target) for e in call_edges}
        assert ("PROGA", "PROGB") in pairs
        assert ("PROGB", "PROGC") in pairs
        # import_graph is flat: only main→direct-callees are resolved; B→C has no path
        progc = next(
            n for n in nodes if n.kind == NodeKind.PROGRAM and n.id == "PROGC"
        )
        assert progc.file_path is None

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_main_source_file_path_is_sentinel(self, cobol_parser):
        # compile_cobol() uses Path("__main__.cbl") as the main module path;
        # callers should not rely on file_path being a real filesystem path
        # when source is passed as bytes (no source_file argument).
        nodes, _edges = extract_cobol_connections(
            _MAIN_CALL,
            extra_subprogram_sources={"HELPER": _HELPER},
            parser=cobol_parser,
        )
        main = next(n for n in nodes if n.kind == NodeKind.PROGRAM and n.id == "MAIN")
        assert main.file_path == "__main__.cbl"


_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "fixtures"
    / "projects"
    / "cobol_connections_demo"
)


class TestFixtureProject:
    """E2E test using on-disk fixture: tests/fixtures/projects/cobol_connections_demo/"""

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_fixture_produces_expected_connections(self):
        cbl = _FIXTURE / "cbl"
        cpy = _FIXTURE / "cpy"
        parser = make_cobol_parser(copybook_dirs=[cpy])
        _nodes, edges = extract_cobol_connections(
            (cbl / "MAIN.cbl").read_bytes(),
            copybook_dirs=[cpy],
            program_source_dirs=[cbl],
            parser=parser,
        )

        triples = [(e.kind.value, e.source, e.target) for e in edges]
        assert ("COPY", "MAIN", "CUSTREC") in triples
        assert ("CALL", "MAIN", "VALIDATE") in triples
        assert ("CALL", "MAIN", "RPTPROG") in triples
        assert ("COPY", "VALIDATE", "CUSTREC") in triples
        assert ("CALL", "VALIDATE", "LOGERR") in triples

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_fixture_call_file_paths_resolved(self):
        cbl = _FIXTURE / "cbl"
        cpy = _FIXTURE / "cpy"
        parser = make_cobol_parser(copybook_dirs=[cpy])
        nodes, _edges = extract_cobol_connections(
            (cbl / "MAIN.cbl").read_bytes(),
            copybook_dirs=[cpy],
            program_source_dirs=[cbl],
            parser=parser,
        )
        by_id = {n.id: n for n in nodes if n.kind == NodeKind.PROGRAM}
        assert by_id["VALIDATE"].file_path == str((cbl / "VALIDATE.cbl").resolve())
        assert by_id["RPTPROG"].file_path == str((cbl / "RPTPROG.cbl").resolve())

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_fixture_copy_target_file_path_is_none(self):
        cbl = _FIXTURE / "cbl"
        cpy = _FIXTURE / "cpy"
        parser = make_cobol_parser(copybook_dirs=[cpy])
        nodes, _edges = extract_cobol_connections(
            (cbl / "MAIN.cbl").read_bytes(),
            copybook_dirs=[cpy],
            program_source_dirs=[cbl],
            parser=parser,
        )
        copybook_nodes = [n for n in nodes if n.kind == NodeKind.COPYBOOK]
        assert copybook_nodes
        assert all(n.file_path is None for n in copybook_nodes)


class TestCopyConnections:
    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_copy_connection_detected(self, tmp_path: Path):
        cpy_file = tmp_path / "MYREC.cpy"
        cpy_file.write_text("       01 MY-FIELD PIC X(10).\n")

        src = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY MYREC.
       PROCEDURE DIVISION.
           GOBACK.
"""
        parser = make_cobol_parser(copybook_dirs=[tmp_path])
        _nodes, edges = extract_cobol_connections(
            src, copybook_dirs=[tmp_path], parser=parser
        )
        copy_edges = [e for e in edges if e.kind == EdgeKind.COPY]
        assert len(copy_edges) == 1
        assert copy_edges[0].source == "MAINPROG"
        assert copy_edges[0].target == "MYREC"

    @covers(NotLanguageFeature.INFRASTRUCTURE)
    def test_copy_target_file_path_is_none(self, tmp_path: Path):
        cpy_file = tmp_path / "MYREC.cpy"
        cpy_file.write_text("       01 MY-FIELD PIC X(10).\n")

        src = b"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY MYREC.
       PROCEDURE DIVISION.
           GOBACK.
"""
        parser = make_cobol_parser(copybook_dirs=[tmp_path])
        nodes, _edges = extract_cobol_connections(
            src, copybook_dirs=[tmp_path], parser=parser
        )
        myrec = next(
            n for n in nodes if n.kind == NodeKind.COPYBOOK and n.id == "MYREC"
        )
        assert myrec.file_path is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --no-sync python -m pytest vendor/red-dragon/tests/integration/project/test_cobol_connections.py -v`
Expected: FAIL — `extract_cobol_connections` still returns `list[Connection]`, not a `(nodes, edges)` tuple.

- [ ] **Step 4: Rewrite the implementation**

```python
# interpreter/project/cobol_connections.py
# pyright: standard
"""COBOL inter-program connection extraction.

extract_cobol_connections() — compile a COBOL project and return its
CALL/COPY relationships as the shared knowledge-graph schema (GraphNode,
GraphEdge — see interpreter.project.graph_types).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from interpreter.constants import Language
from interpreter.frontend_extension import (
    DialectParser,
    RedDragonExtensionLoweringStrategy,
)
from interpreter.frontend_observer import FrontendObserver, NullFrontendObserver
from interpreter.project.cobol_compile import compile_cobol
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from interpreter.project.imports import extract_imports
from interpreter.project.types import ImportKind, ImportRef


def extract_cobol_connections(
    source: bytes,
    *,
    copybook_dirs: list[Path] = [],
    program_source_dirs: Sequence[Path] = (),
    extra_subprogram_sources: dict[str, bytes] = {},
    parser: Any,
    extension_strategies: Sequence[RedDragonExtensionLoweringStrategy] = (),
    dialect_parsers: Sequence[DialectParser] = (),
    observer: FrontendObserver = NullFrontendObserver(),
    source_transform: Callable[[str], str] = lambda s: s,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Compile a COBOL project and return its CALL/COPY graph.

    Calls compile_cobol() with the same arguments, then post-processes the
    finished LinkedProgram — no VM execution takes place.

    CALL target file paths are resolved from LinkedProgram.import_graph.
    COPY target file paths are always None (copybooks are inlined by ProLeap
    before red-dragon sees the ASG; the name is extracted from raw source).
    Every node id is uppercased (the standard COBOL convention), so the same
    program/copybook referenced with different case always merges to one node.
    """
    main_path = Path("__main__.cbl")

    main_frontend, linked = compile_cobol(
        source,
        parser=parser,
        copybook_dirs=copybook_dirs,
        extension_strategies=extension_strategies,
        dialect_parsers=dialect_parsers,
        observer=observer,
        program_source_dirs=program_source_dirs,
        extra_subprogram_sources=extra_subprogram_sources,
        source_transform=source_transform,
    )

    # The main module is always compiled as __main__.cbl; use the frontend's
    # program_id (the COBOL PROGRAM-ID paragraph) as the canonical name.
    main_program_id: str = main_frontend.program_id

    # Build {caller_path -> {called_name_upper -> resolved_path}} from import_graph.
    call_resolution: dict[Path, dict[str, Path]] = {}
    for caller_path, callee_paths in linked.import_graph.items():
        call_resolution[caller_path] = {p.stem.upper(): p for p in callee_paths}

    def _module_name(module_path: Path) -> str:
        """Return the PROGRAM-ID for the main module; stem for subprograms."""
        if module_path == main_path:
            return main_program_id
        return module_path.stem

    # When there are no subprograms, compile_cobol returns modules={}.
    # Reconstruct the main module's import list by re-running extract_imports
    # on the raw source (identical to what compile_cobol_module does internally).
    if linked.modules:
        modules_with_imports: dict[Path, tuple[ImportRef, ...]] = {
            path: module.imports for path, module in linked.modules.items()
        }
    else:
        main_imports = tuple(extract_imports(source, main_path, Language.COBOL))
        modules_with_imports = {main_path: main_imports}

    nodes: dict[tuple[NodeKind, str], GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(kind: NodeKind, name: str, file_path: Path | None) -> str:
        node_id = name.upper()
        key = (kind, node_id)
        existing = nodes.get(key)
        if existing is None:
            nodes[key] = GraphNode(
                id=node_id,
                kind=kind,
                file_path=str(file_path) if file_path is not None else None,
            )
        elif existing.file_path is None and file_path is not None:
            nodes[key] = GraphNode(
                id=node_id, kind=kind, file_path=str(file_path)
            )
        return node_id

    for module_path, imports in modules_with_imports.items():
        source_name = _module_name(module_path)
        source_id = _add_node(NodeKind.PROGRAM, source_name, module_path)
        call_map = call_resolution.get(module_path, {})
        for ref in imports:
            if ref.kind == ImportKind.INCLUDE:
                target_id = _add_node(NodeKind.COPYBOOK, ref.module_path, None)
                edges.append(
                    GraphEdge(
                        source=source_id,
                        source_kind=NodeKind.PROGRAM,
                        target=target_id,
                        target_kind=NodeKind.COPYBOOK,
                        kind=EdgeKind.COPY,
                    )
                )
            elif ref.kind == ImportKind.REQUIRE:
                target_path = call_map.get(ref.module_path.upper())
                target_id = _add_node(NodeKind.PROGRAM, ref.module_path, target_path)
                edges.append(
                    GraphEdge(
                        source=source_id,
                        source_kind=NodeKind.PROGRAM,
                        target=target_id,
                        target_kind=NodeKind.PROGRAM,
                        kind=EdgeKind.CALL,
                    )
                )

    return list(nodes.values()), edges
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --no-sync python -m pytest vendor/red-dragon/tests/integration/project/test_cobol_connections.py vendor/red-dragon/tests/unit/project/test_cobol_connections_defaults.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd vendor/red-dragon
git add interpreter/project/cobol_connections.py tests/integration/project/test_cobol_connections.py
git rm tests/unit/project/test_cobol_connections.py
git commit -m "feat: cobol_connections.py emits the shared knowledge-graph schema"
cd ../..
```

---

## Task 3: Add extract_transaction_flow_graph() to flow_map.py (cicada)

**Files:**
- Modify: `cics/flow_map.py` (full rewrite — factors out shared compilation, adds a new function; the existing `extract_transaction_flow_map` function and its behavior are unchanged)
- Test (unchanged, must still pass): `tests/integration/cics/test_flow_map.py`
- Create: `tests/integration/cics/test_flow_graph.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind` from Task 1 (via `interpreter.project.graph_types`, already an available dependency — cicada already depends on red-dragon).
- Produces: `extract_transaction_flow_graph(csd_source, bms_mapsets, cobol_sources, *, parser=None) -> tuple[list[GraphNode], list[GraphEdge]]`. Task 9's integration test calls this function with this exact signature.

Unlike Task 2, this is additive: `extract_transaction_flow_map`'s existing JSON-dict output shape has independent value (a nested, human-readable per-transaction view) that the flat graph shape doesn't replace, and it already has 8 passing tests with no other production caller to break — no reason to delete it. The two functions share their CSD parsing and per-program compilation via a new private `_compile_all_programs` helper, factored out of the existing function's body.

This repo is `~/code/red-dragon-forge`; this task's files are under `~/code/red-dragon-forge/cicada/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/cics/test_flow_graph.py
"""Integration tests for extract_transaction_flow_graph().

Same synthetic COBOL + synthetic BmsMapSet fixtures as test_flow_map.py — the
two functions share compilation (_compile_all_programs), so this only
re-verifies the graph *shape* is right, not the CICS behaviour
test_flow_map.py already covers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bms_copybook_gen.models import BmsField, BmsMap, BmsMapSet
from cics.flow_map import extract_transaction_flow_graph
from interpreter.cobol.cobol_parser import ProLeapCobolParser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.project.graph_types import EdgeKind, NodeKind
from tests.covers import NotLanguageFeature, covers
from tests.integration.cobol_helpers import bridge_jar  # noqa: F401 — pytest fixture

_CICS_COPYBOOKS = Path(__file__).parents[3] / "cics" / "copybooks"


@pytest.fixture
def cics_parser(bridge_jar):
    return ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[_CICS_COPYBOOKS]
    )


def _make_mapset(name: str, map_name: str, fields: list[BmsField]) -> BmsMapSet:
    bms_map = BmsMap(label=map_name, fields=fields)
    return BmsMapSet(
        label=name, lang="COBOL", mode="INOUT", tioapfx=False, maps=[bms_map]
    )


_CSD = "DEFINE TRANSACTION(ACCT) GROUP(DEMO) PROGRAM(ACCTPROG)\n"

_ACCTPROG = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTPROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 DFHCOMMAREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS RECEIVE MAP('ACCMAP') MAPSET('ACCSET') END-EXEC.
           EXEC CICS SEND MAP('ACCMAP') MAPSET('ACCSET') END-EXEC.
           EXEC CICS RETURN TRANSID('ACCT') END-EXEC.
           STOP RUN.
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_starts_edge_from_transaction_to_program(cics_parser):
    nodes, edges = extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    starts = [e for e in edges if e.kind == EdgeKind.STARTS]
    assert len(starts) == 1
    assert starts[0].source == "ACCT"
    assert starts[0].target == "ACCTPROG"
    assert any(n.kind == NodeKind.TRANSACTION and n.id == "ACCT" for n in nodes)
    assert any(n.kind == NodeKind.PROGRAM and n.id == "ACCTPROG" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_return_transid_edge_back_to_transaction(cics_parser):
    _nodes, edges = extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    ret = [e for e in edges if e.kind == EdgeKind.RETURN_TRANSID]
    assert len(ret) == 1
    assert ret[0].source == "ACCTPROG"
    assert ret[0].target == "ACCT"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_send_and_receive_map_edges_with_bms_map_node(cics_parser):
    mapset = _make_mapset(
        "ACCSET",
        "ACCMAP",
        [
            BmsField(label="ACCTID", length=11, attrb=["UNPROT"]),
            BmsField(label="ACCTNAME", length=50, attrb=["PROT"]),
        ],
    )
    nodes, edges = extract_transaction_flow_graph(
        csd_source=_CSD,
        bms_mapsets={"ACCSET": mapset},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    sends = [e for e in edges if e.kind == EdgeKind.SENDS_MAP]
    receives = [e for e in edges if e.kind == EdgeKind.RECEIVES_MAP]
    assert len(sends) == 1 and len(receives) == 1
    assert sends[0].source == "ACCTPROG"
    assert sends[0].target == "ACCSET.ACCMAP"
    assert any(
        n.kind == NodeKind.BMS_MAP and n.id == "ACCSET.ACCMAP" for n in nodes
    )
    fields = {f["name"]: f["direction"] for f in sends[0].attrs["fields"]}
    assert fields["ACCTID"] == "input"
    assert fields["ACCTNAME"] == "output"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_xctl_edge_between_programs(cics_parser):
    csd = "DEFINE TRANSACTION(MENU) GROUP(DEMO) PROGRAM(MENUPROG)\n"
    src = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MENUPROG.
       PROCEDURE DIVISION.
           EXEC CICS XCTL PROGRAM('NEXTPROG') END-EXEC.
           STOP RUN.
"""
    nodes, edges = extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"MENUPROG": src},
        parser=cics_parser,
    )
    xctl = [e for e in edges if e.kind == EdgeKind.XCTL]
    assert len(xctl) == 1
    assert xctl[0].source == "MENUPROG"
    assert xctl[0].target == "NEXTPROG"
    assert any(n.kind == NodeKind.PROGRAM and n.id == "NEXTPROG" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_node_ids_are_uppercased(cics_parser):
    csd = "DEFINE TRANSACTION(acct) GROUP(DEMO) PROGRAM(ACCTPROG)\n"
    nodes, _edges = extract_transaction_flow_graph(
        csd_source=csd,
        bms_mapsets={},
        cobol_sources={"ACCTPROG": _ACCTPROG},
        parser=cics_parser,
    )
    assert any(n.kind == NodeKind.TRANSACTION and n.id == "ACCT" for n in nodes)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `~/code/red-dragon-forge`): `uv run --no-sync python -m pytest cicada/tests/integration/cics/test_flow_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_transaction_flow_graph'`

- [ ] **Step 3: Rewrite the implementation**

```python
# cics/flow_map.py
"""extract_transaction_flow_map() / extract_transaction_flow_graph() — static
analysis builder APIs.

Compile each CICS program referenced in a CSD, collect CICS verb events via
CicsFlowObserver, and return either a JSON-serialisable list of transaction
flow maps (extract_transaction_flow_map) or the CICS-flow portion of the
shared knowledge-graph schema (extract_transaction_flow_graph). Both share
the same CSD parsing and per-program compilation — see _compile_all_programs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.flow_observer import CicsVerb, field_direction
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


class _CollectingObserver:
    """Accumulates CicsVerb events for one program compilation, tagging program name."""

    def __init__(self, program_name: str) -> None:
        self._program_name = program_name
        self.verbs: list[CicsVerb] = []

    def on_verb(self, verb: CicsVerb) -> None:
        # Strategy leaves verb.program = ""; tag it here with the known program name.
        self.verbs.append(
            CicsVerb(
                verb=verb.verb,
                program=self._program_name,
                map_name=verb.map_name,
                mapset_name=verb.mapset_name,
                xctl_target=verb.xctl_target,
                transid=verb.transid,
            )
        )


def _compile_all_programs(
    csd_source: str,
    cobol_sources: dict[str, bytes],
    parser: Any,
) -> tuple[dict[str, str], dict[str, list[CicsVerb]]]:
    """Parse the CSD and compile each distinct referenced program once.

    Returns (transid_to_program, {program_name: [CicsVerb, ...]}) — shared by
    both extract_transaction_flow_map and extract_transaction_flow_graph.
    """
    from cics.dispatcher import parse_csd  # noqa: PLC0415
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.coprocessor import build_cics_spec  # noqa: PLC0415

    # parse_csd expects a Path; write CSD text to a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    transid_to_program = parse_csd(csd_path)
    csd_path.unlink(missing_ok=True)

    compiled_verbs: dict[str, list[CicsVerb]] = {}
    for prog_name in transid_to_program.values():
        if prog_name in compiled_verbs:
            continue
        raw = cobol_sources.get(prog_name)
        if raw is None:
            compiled_verbs[prog_name] = []
            continue
        observer = _CollectingObserver(prog_name)
        spec = build_cics_spec(
            context_holder=[None],
            result_holder=[None],
            observer=observer,
        )
        # Positional args: source, parser, spec
        compile_cics_program(raw, parser, spec)
        compiled_verbs[prog_name] = observer.verbs

    return transid_to_program, compiled_verbs


def _bms_fields(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> list[dict]:  # type: ignore[type-arg]
    """Field direction metadata for a SEND_MAP/RECEIVE_MAP verb, or [] if unavailable."""
    if not (
        verb.mapset_name
        and verb.map_name
        and verb.verb in ("SEND_MAP", "RECEIVE_MAP")
    ):
        return []
    mapset = bms_mapsets.get(verb.mapset_name)
    if mapset is None:
        return []
    bms_map = next((m for m in mapset.maps if m.label == verb.map_name), None)
    if bms_map is None:
        return []
    return [{"name": f.label, "direction": field_direction(f)} for f in bms_map.fields]


def _enrich_verb(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> dict:  # type: ignore[type-arg]
    """Convert CicsVerb → JSON-serialisable dict with BMS field metadata."""
    return {
        "verb": verb.verb,
        "program": verb.program,
        "map": verb.map_name,
        "mapset": verb.mapset_name,
        "xctl_target": verb.xctl_target,
        "transid": verb.transid,
        "fields": _bms_fields(verb, bms_mapsets),
    }


def extract_transaction_flow_map(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
) -> list[dict]:  # type: ignore[type-arg]
    """Static analysis: extract a JSON transaction flow map from a CICS project.

    Args:
        csd_source: CSD text with DEFINE TRANSACTION(...) PROGRAM(...) entries.
        bms_mapsets: parsed BmsMapSet models keyed by mapset name.
        cobol_sources: program name → raw (un-prepassed) COBOL bytes.
        parser: ProLeap parser instance.

    Returns:
        List of dicts, one per transaction, in CSD order.
    """
    transid_to_program, compiled_verbs = _compile_all_programs(
        csd_source, cobol_sources, parser
    )

    results: list[dict] = []  # type: ignore[type-arg]
    for transid, prog_name in transid_to_program.items():
        verbs = compiled_verbs.get(prog_name, [])
        results.append(
            {
                "transid": transid,
                "entry_program": prog_name,
                "flow": [_enrich_verb(v, bms_mapsets) for v in verbs],
            }
        )
    return results


def _verb_edge(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> GraphEdge | None:
    """Convert one CicsVerb event into a GraphEdge, or None for verbs with no
    graph-relevant target (e.g. a plain RETURN with no TRANSID)."""
    program_id = verb.program.upper()
    if verb.verb == "XCTL" and verb.xctl_target:
        return GraphEdge(
            source=program_id,
            source_kind=NodeKind.PROGRAM,
            target=verb.xctl_target.upper(),
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.XCTL,
        )
    if verb.verb == "LINK" and verb.xctl_target:
        return GraphEdge(
            source=program_id,
            source_kind=NodeKind.PROGRAM,
            target=verb.xctl_target.upper(),
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.LINK,
        )
    if verb.verb == "RETURN_TRANSID" and verb.transid:
        return GraphEdge(
            source=program_id,
            source_kind=NodeKind.PROGRAM,
            target=verb.transid.upper(),
            target_kind=NodeKind.TRANSACTION,
            kind=EdgeKind.RETURN_TRANSID,
        )
    if verb.verb in ("SEND_MAP", "RECEIVE_MAP") and verb.mapset_name and verb.map_name:
        bms_id = f"{verb.mapset_name.upper()}.{verb.map_name.upper()}"
        kind = EdgeKind.SENDS_MAP if verb.verb == "SEND_MAP" else EdgeKind.RECEIVES_MAP
        fields = _bms_fields(verb, bms_mapsets)
        return GraphEdge(
            source=program_id,
            source_kind=NodeKind.PROGRAM,
            target=bms_id,
            target_kind=NodeKind.BMS_MAP,
            kind=kind,
            attrs={"fields": fields} if fields else {},
        )
    return None


def extract_transaction_flow_graph(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Static analysis: extract the CICS-flow portion of the shared knowledge
    graph (TRANSACTION/PROGRAM/BMS_MAP nodes; STARTS/XCTL/LINK/RETURN_TRANSID/
    SENDS_MAP/RECEIVES_MAP edges).

    Same inputs and compilation as extract_transaction_flow_map — see
    _compile_all_programs — a different output shape, not new extraction.
    Every node id is uppercased (the standard CICS/COBOL convention).
    """
    transid_to_program, compiled_verbs = _compile_all_programs(
        csd_source, cobol_sources, parser
    )

    nodes: dict[tuple[NodeKind, str], GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(kind: NodeKind, node_id: str) -> str:
        nodes.setdefault((kind, node_id), GraphNode(id=node_id, kind=kind))
        return node_id

    for transid, prog_name in transid_to_program.items():
        transid_id = _add_node(NodeKind.TRANSACTION, transid.upper())
        prog_id = _add_node(NodeKind.PROGRAM, prog_name.upper())
        edges.append(
            GraphEdge(
                source=transid_id,
                source_kind=NodeKind.TRANSACTION,
                target=prog_id,
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.STARTS,
            )
        )

        for verb in compiled_verbs.get(prog_name, []):
            edge = _verb_edge(verb, bms_mapsets)
            if edge is None:
                continue
            _add_node(edge.source_kind, edge.source)
            _add_node(edge.target_kind, edge.target)
            edges.append(edge)

    return list(nodes.values()), edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --no-sync python -m pytest cicada/tests/integration/cics/test_flow_graph.py cicada/tests/integration/cics/test_flow_map.py -v`
Expected: all pass (5 new + 7 existing)

- [ ] **Step 5: Commit**

```bash
cd cicada
git add cics/flow_map.py tests/integration/cics/test_flow_graph.py
git commit -m "feat: add extract_transaction_flow_graph() alongside the existing JSON map"
cd ..
```

---

## Task 4: New JCL step-sequencing extractor (jackal)

**Files:**
- Create: `jackal/jcl_graph.py`
- Test: `tests/unit/test_jcl_graph.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind` from Task 1; `Job`, `Step`, `DD`, `DispStatus` from `jackal.model`; `DirectDSN` from `jackal.dsn`; `parse_jcl` from `jackal.jcl.parser` (already depends on red-dragon and this module — no new coupling).
- Produces: `extract_jcl_graph(jcl_source: str) -> tuple[list[GraphNode], list[GraphEdge]]`. Task 9's integration test calls this function with this exact signature.

This is the one genuinely new piece of extraction logic in the whole plan — everything else is a reshape of an existing extractor's output. It is new *graph-shaping*, not new *parsing*: `parse_jcl` already exists and does all the actual JCL parsing.

This repo is `~/code/red-dragon-forge`; this task's files are under `~/code/red-dragon-forge/jackal/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_jcl_graph.py
"""Unit tests for extract_jcl_graph()."""

import pytest

from tests.covers import NotLanguageFeature, covers
from jackal.jcl_graph import extract_jcl_graph
from interpreter.project.graph_types import EdgeKind, NodeKind


@pytest.fixture(autouse=True)
def _require_jcl_bridge(jcl_bridge_jar):
    """extract_jcl_graph shells to the JCL bridge via parse_jcl; ensure JCL_BRIDGE_JAR is set."""


_JCL = """//PIPE JOB 'demo'
//STEP1 EXEC PGM=UPCASE
//INDD DD DSN=J.IN,DISP=SHR
//WORKDD DD DSN=J.WORK,DISP=(NEW,PASS,DELETE)
//STEP2 EXEC PGM=STARRER
//WORKDD DD DSN=J.WORK,DISP=SHR
//OUTDD DD DSN=J.OUT,DISP=(NEW,CATLG,DELETE)
"""


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_and_step_nodes_created():
    nodes, _edges = extract_jcl_graph(_JCL)
    assert any(n.kind == NodeKind.JOB and n.id == "PIPE" for n in nodes)
    assert any(n.kind == NodeKind.STEP and n.id == "PIPE.STEP1" for n in nodes)
    assert any(n.kind == NodeKind.STEP and n.id == "PIPE.STEP2" for n in nodes)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_job_step_runs_edges_reflect_step_order():
    _nodes, edges = extract_jcl_graph(_JCL)
    job_to_step = [
        e for e in edges if e.kind == EdgeKind.JCL_STEP_RUNS and e.source == "PIPE"
    ]
    assert [e.target for e in job_to_step] == ["PIPE.STEP1", "PIPE.STEP2"]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_step_runs_program_edge():
    _nodes, edges = extract_jcl_graph(_JCL)
    step_to_prog = {
        e.source: e.target
        for e in edges
        if e.kind == EdgeKind.JCL_STEP_RUNS and e.source.startswith("PIPE.")
    }
    assert step_to_prog["PIPE.STEP1"] == "UPCASE"
    assert step_to_prog["PIPE.STEP2"] == "STARRER"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_shr_becomes_reads():
    _nodes, edges = extract_jcl_graph(_JCL)
    reads = [e for e in edges if e.kind == EdgeKind.READS and e.source == "PIPE.STEP1"]
    assert len(reads) == 1
    assert reads[0].target == "J.IN"
    assert reads[0].attrs["disp"] == "SHR"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_disp_new_becomes_writes():
    _nodes, edges = extract_jcl_graph(_JCL)
    writes = [
        e for e in edges if e.kind == EdgeKind.WRITES and e.source == "PIPE.STEP1"
    ]
    assert len(writes) == 1
    assert writes[0].target == "J.WORK"
    assert writes[0].attrs["disp"] == "NEW"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_dataset_node_shared_across_steps():
    nodes, edges = extract_jcl_graph(_JCL)
    work_nodes = [n for n in nodes if n.kind == NodeKind.DATASET and n.id == "J.WORK"]
    assert len(work_nodes) == 1  # one node, even though both steps reference it
    step2_reads = [
        e for e in edges if e.kind == EdgeKind.READS and e.source == "PIPE.STEP2"
    ]
    assert step2_reads[0].target == "J.WORK"


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_sysout_dd_is_not_a_dataset_node():
    jcl = """//SOUT JOB 'demo'
//STEP1 EXEC PGM=PRINTER
//SYSOUT DD SYSOUT=*
"""
    nodes, edges = extract_jcl_graph(jcl)
    assert not any(n.kind == NodeKind.DATASET for n in nodes)
    assert not any(
        e.kind in (EdgeKind.READS, EdgeKind.WRITES, EdgeKind.UPDATES) for e in edges
    )


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_temp_dataset_is_not_a_dataset_node():
    jcl = """//TMPJ JOB 'demo'
//STEP1 EXEC PGM=SORTER
//WORKDD DD DSN=&&TEMP,DISP=(NEW,PASS,DELETE)
"""
    nodes, edges = extract_jcl_graph(jcl)
    assert not any(n.kind == NodeKind.DATASET for n in nodes)
    assert not any(
        e.kind in (EdgeKind.READS, EdgeKind.WRITES, EdgeKind.UPDATES) for e in edges
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `~/code/red-dragon-forge`): `uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jackal.jcl_graph'`

- [ ] **Step 3: Write the implementation**

```python
# jackal/jcl_graph.py
"""extract_jcl_graph() — static analysis: the JCL step-sequencing portion of
the shared knowledge graph, built by walking an already-parsed Job (via the
existing parse_jcl — this module adds no new JCL parsing).
"""

from __future__ import annotations

from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind

from jackal.dsn import DirectDSN
from jackal.jcl.parser import parse_jcl
from jackal.model import DispStatus, Job

_DISP_TO_EDGE_KIND: dict[DispStatus, EdgeKind] = {
    DispStatus.NEW: EdgeKind.WRITES,
    DispStatus.OLD: EdgeKind.UPDATES,
    DispStatus.SHR: EdgeKind.READS,
    DispStatus.MOD: EdgeKind.WRITES,
}


def _job_to_graph(job: Job) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: dict[tuple[NodeKind, str], GraphNode] = {}
    edges: list[GraphEdge] = []

    def _add_node(kind: NodeKind, node_id: str) -> str:
        nodes.setdefault((kind, node_id), GraphNode(id=node_id, kind=kind))
        return node_id

    job_id = _add_node(NodeKind.JOB, job.name.upper())

    for step in job.steps:
        step_id = _add_node(NodeKind.STEP, f"{job.name.upper()}.{step.name.upper()}")
        edges.append(
            GraphEdge(
                source=job_id,
                source_kind=NodeKind.JOB,
                target=step_id,
                target_kind=NodeKind.STEP,
                kind=EdgeKind.JCL_STEP_RUNS,
            )
        )

        prog_id = _add_node(NodeKind.PROGRAM, step.pgm.upper())
        edges.append(
            GraphEdge(
                source=step_id,
                source_kind=NodeKind.STEP,
                target=prog_id,
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.JCL_STEP_RUNS,
            )
        )

        for dd in step.dds:
            if dd.sysout or not isinstance(dd.dsn, DirectDSN):
                continue
            dataset_id = _add_node(NodeKind.DATASET, dd.dsn.name.upper())
            edges.append(
                GraphEdge(
                    source=step_id,
                    source_kind=NodeKind.STEP,
                    target=dataset_id,
                    target_kind=NodeKind.DATASET,
                    kind=_DISP_TO_EDGE_KIND[dd.disp.status],
                    attrs={"ddname": dd.ddname, "disp": dd.disp.status.value},
                )
            )

    return list(nodes.values()), edges


def extract_jcl_graph(jcl_source: str) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Parse JCL text and return its step-sequencing portion of the shared
    knowledge graph: JOB/STEP/PROGRAM/DATASET nodes; JCL_STEP_RUNS edges
    (job->step, in step order, and step->program) and READS/WRITES/UPDATES
    edges (step->dataset, derived from DD disposition — NEW/MOD->WRITES,
    OLD->UPDATES, SHR->READS; the raw DispStatus is kept in attrs["disp"]).

    TempRef (&&NAME) and BackwardRef (*.STEP.DD) datasets, and SYSOUT DDs,
    are not stable cross-job identities and are not represented as DATASET
    nodes.
    """
    job = parse_jcl(jcl_source)
    return _job_to_graph(job)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest jackal/tests/unit/test_jcl_graph.py -v`
Expected: 8 passed (skipped instead if `JCL_BRIDGE_JAR` is unset — the fixture fails loud, matching `test_jcl_parser.py`'s own established pattern)

- [ ] **Step 5: Commit**

```bash
cd jackal
git add jackal/jcl_graph.py tests/unit/test_jcl_graph.py
git commit -m "feat: add extract_jcl_graph() — JCL step-sequencing knowledge-graph extractor"
cd ..
```

---

## Task 5: knowledge_graph package skeleton + merge.py + import-linter contract (red-dragon-forge)

**Files:**
- Create: `knowledge_graph/__init__.py`
- Create: `knowledge_graph/merge.py`
- Modify: `pyproject.toml` (add `knowledge_graph` as a workspace member + add `networkx` dependency)
- Modify: `.importlinter` (add `knowledge_graph` to `root_packages` + a forbidden-import contract)
- Test: `tests/unit/knowledge_graph/test_merge.py`
- Create: `tests/unit/knowledge_graph/__init__.py`
- Create: `tests/unit/__init__.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge`, `NodeKind`, `EdgeKind` from `interpreter.project.graph_types` (Task 1).
- Produces: `merge_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> networkx.MultiDiGraph`. Every node in the returned graph is keyed by `(NodeKind, id)`; node data carries `kind`, `id`, `file_path`, `attrs`; edge data carries `kind`, `attrs`. Tasks 6, 8, 9 consume this return type.

This repo is `~/code/red-dragon-forge` itself (not a vendored submodule).

- [ ] **Step 1: Add knowledge_graph as a workspace member and add networkx**

In the root `pyproject.toml`, change:

```toml
[tool.uv.workspace]
members = ["cicada", "squall", "jackal"]
```

to:

```toml
[tool.uv.workspace]
members = ["cicada", "squall", "jackal", "knowledge_graph"]
```

Create `knowledge_graph/pyproject.toml`, mirroring `jackal/pyproject.toml`'s shape:

```toml
[project]
name = "knowledge_graph"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["networkx>=3.0", "red-dragon"]

[tool.uv.sources]
red-dragon = { path = "../vendor/red-dragon", editable = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["knowledge_graph"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.black]
target-version = ["py313"]
```

Then sync the workspace so `uv.lock` picks up the new member and dependency:

```bash
uv sync --all-packages
```

- [ ] **Step 2: Create the package skeleton**

```python
# knowledge_graph/__init__.py
```

```bash
mkdir -p tests/unit/knowledge_graph
touch tests/unit/__init__.py tests/unit/knowledge_graph/__init__.py
```

- [ ] **Step 3: Write the failing test**

```python
# tests/unit/knowledge_graph/test_merge.py
"""Unit tests for merge_graph()."""

from knowledge_graph.merge import merge_graph
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def test_nodes_are_keyed_by_kind_and_id():
    nodes = [GraphNode(id="MAIN", kind=NodeKind.PROGRAM)]
    graph = merge_graph(nodes, [])
    assert graph.has_node((NodeKind.PROGRAM, "MAIN"))
    assert graph.nodes[(NodeKind.PROGRAM, "MAIN")]["id"] == "MAIN"
    assert graph.nodes[(NodeKind.PROGRAM, "MAIN")]["kind"] is NodeKind.PROGRAM


def test_program_and_dataset_with_same_id_do_not_collide():
    nodes = [
        GraphNode(id="ACCTFILE", kind=NodeKind.PROGRAM),
        GraphNode(id="ACCTFILE", kind=NodeKind.DATASET),
    ]
    graph = merge_graph(nodes, [])
    assert graph.has_node((NodeKind.PROGRAM, "ACCTFILE"))
    assert graph.has_node((NodeKind.DATASET, "ACCTFILE"))
    assert graph.number_of_nodes() == 2


def test_duplicate_node_registration_merges_attrs_not_overwrites():
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM, attrs={"a": 1}),
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM, attrs={"b": 2}),
    ]
    graph = merge_graph(nodes, [])
    assert graph.nodes[(NodeKind.PROGRAM, "MAIN")]["attrs"] == {"a": 1, "b": 2}


def test_duplicate_node_registration_prefers_non_none_file_path():
    nodes = [
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM, file_path=None),
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM, file_path="/src/HELPER.cbl"),
    ]
    graph = merge_graph(nodes, [])
    assert graph.nodes[(NodeKind.PROGRAM, "HELPER")]["file_path"] == "/src/HELPER.cbl"


def test_edge_added_between_existing_nodes():
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM),
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        )
    ]
    graph = merge_graph(nodes, edges)
    assert graph.has_edge((NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "HELPER"))
    edge_data = graph.get_edge_data(
        (NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "HELPER")
    )
    assert edge_data[0]["kind"] is EdgeKind.CALL


def test_two_edges_of_different_kinds_between_same_nodes_both_kept():
    """MultiDiGraph, not DiGraph: a program that both CALLs another program
    and also runs it as a JCL step's PGM= keeps both edges."""
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM),
        GraphNode(id="HELPER", kind=NodeKind.PROGRAM),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        ),
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.XCTL,
        ),
    ]
    graph = merge_graph(nodes, edges)
    edge_data = graph.get_edge_data(
        (NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "HELPER")
    )
    kinds = {d["kind"] for d in edge_data.values()}
    assert kinds == {EdgeKind.CALL, EdgeKind.XCTL}


def test_edge_endpoint_missing_from_nodes_list_is_created_defensively():
    """An edge whose endpoint wasn't separately listed in nodes still merges
    cleanly — data from three independent extractors is not guaranteed to
    perfectly enumerate every node an edge references."""
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="HELPER",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        )
    ]
    graph = merge_graph([], edges)
    assert graph.has_node((NodeKind.PROGRAM, "MAIN"))
    assert graph.has_node((NodeKind.PROGRAM, "HELPER"))
```

- [ ] **Step 4: Run test to verify it fails**

Run (from `~/code/red-dragon-forge`): `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_graph'`

- [ ] **Step 5: Write the implementation**

```python
# knowledge_graph/merge.py
"""merge_graph() — combine GraphNode/GraphEdge sequences from every
extractor (red-dragon's CALL/COPY graph, cicada's CICS flow graph, jackal's
JCL graph) into one networkx.MultiDiGraph, keyed by (kind, id).
"""

from __future__ import annotations

import networkx as nx

from interpreter.project.graph_types import GraphEdge, GraphNode


def merge_graph(nodes: list[GraphNode], edges: list[GraphEdge]) -> nx.MultiDiGraph:
    """Build one MultiDiGraph from GraphNode/GraphEdge sequences.

    Nodes are keyed by (kind, id) — two GraphNode instances with the same
    key merge their attrs (new attrs win per key on conflict) rather than
    one overwriting the other; file_path prefers whichever value is
    non-None. MultiDiGraph (not DiGraph): two nodes can be legitimately
    connected by more than one edge kind. Edges reference their endpoints'
    (kind, id) directly via GraphEdge.source_kind/target_kind — endpoints
    not separately present in `nodes` are added defensively so a merge from
    three independent extractors never KeyErrors on an under-enumerated
    node list.
    """
    graph = nx.MultiDiGraph()

    for node in nodes:
        key = (node.kind, node.id)
        if graph.has_node(key):
            data = graph.nodes[key]
            data["attrs"] = {**data["attrs"], **node.attrs}
            data["file_path"] = data["file_path"] or node.file_path
        else:
            graph.add_node(
                key,
                kind=node.kind,
                id=node.id,
                file_path=node.file_path,
                attrs=dict(node.attrs),
            )

    for edge in edges:
        source_key = (edge.source_kind, edge.source)
        target_key = (edge.target_kind, edge.target)
        if not graph.has_node(source_key):
            graph.add_node(
                source_key,
                kind=edge.source_kind,
                id=edge.source,
                file_path=None,
                attrs={},
            )
        if not graph.has_node(target_key):
            graph.add_node(
                target_key,
                kind=edge.target_kind,
                id=edge.target,
                file_path=None,
                attrs={},
            )
        graph.add_edge(source_key, target_key, kind=edge.kind, attrs=dict(edge.attrs))

    return graph
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_merge.py -v`
Expected: 7 passed

- [ ] **Step 7: Add the import-linter contract**

Read `.importlinter` (repo root) and add `knowledge_graph` to the
`root_packages` list under `[importlinter]`, then add this new contract
section:

```ini
[importlinter:contract:knowledge-graph-composition-only]
name = Cicada, Squall, and Jackal must not import knowledge_graph
type = forbidden
source_modules =
    cics
    squall
    jackal
forbidden_modules =
    knowledge_graph
```

- [ ] **Step 8: Run import-linter to verify the contract holds**

Run: `uv run --no-sync lint-imports`
Expected: all contracts pass (this is a new, currently-trivially-satisfied contract — nothing yet imports `knowledge_graph`)

- [ ] **Step 9: Commit**

```bash
git add knowledge_graph/ tests/unit/ pyproject.toml .importlinter uv.lock
git commit -m "feat: add knowledge_graph package with merge_graph() + import-linter contract"
```

---

## Task 6: query.py (red-dragon-forge)

**Files:**
- Create: `knowledge_graph/query.py`
- Test: `tests/unit/knowledge_graph/test_query.py`

**Interfaces:**
- Consumes: `NodeKind`, `EdgeKind` from `interpreter.project.graph_types`; a `networkx.MultiDiGraph` from Task 5's `merge_graph`.
- Produces: `reachable_from(graph, start, *, edge_kinds=None) -> set[NodeId]`, `callers_of(graph, target, *, edge_kinds=None) -> set[NodeId]`, `paths_between(graph, source, target, *, edge_kinds=None) -> list[list[NodeId]]`, where `NodeId = tuple[NodeKind, str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/knowledge_graph/test_query.py
"""Unit tests for the query helpers over a merged graph."""

from knowledge_graph.merge import merge_graph
from knowledge_graph.query import callers_of, paths_between, reachable_from
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def _chain_graph():
    """MAIN -CALL-> MID -CALL-> LEAF, plus MAIN -COPY-> RECRD (a dead end)."""
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM),
        GraphNode(id="MID", kind=NodeKind.PROGRAM),
        GraphNode(id="LEAF", kind=NodeKind.PROGRAM),
        GraphNode(id="RECRD", kind=NodeKind.COPYBOOK),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="MID",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        ),
        GraphEdge(
            source="MID",
            source_kind=NodeKind.PROGRAM,
            target="LEAF",
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.CALL,
        ),
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="RECRD",
            target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY,
        ),
    ]
    return merge_graph(nodes, edges)


def test_reachable_from_finds_the_whole_downstream_chain():
    graph = _chain_graph()
    result = reachable_from(graph, (NodeKind.PROGRAM, "MAIN"))
    assert result == {
        (NodeKind.PROGRAM, "MID"),
        (NodeKind.PROGRAM, "LEAF"),
        (NodeKind.COPYBOOK, "RECRD"),
    }


def test_reachable_from_can_be_restricted_by_edge_kind():
    graph = _chain_graph()
    result = reachable_from(
        graph, (NodeKind.PROGRAM, "MAIN"), edge_kinds={EdgeKind.CALL}
    )
    assert result == {(NodeKind.PROGRAM, "MID"), (NodeKind.PROGRAM, "LEAF")}


def test_reachable_from_unknown_start_is_empty():
    graph = _chain_graph()
    result = reachable_from(graph, (NodeKind.PROGRAM, "GHOST"))
    assert result == set()


def test_callers_of_finds_direct_predecessors():
    graph = _chain_graph()
    result = callers_of(graph, (NodeKind.PROGRAM, "LEAF"))
    assert result == {(NodeKind.PROGRAM, "MID")}


def test_callers_of_can_be_restricted_by_edge_kind():
    graph = _chain_graph()
    result = callers_of(
        graph, (NodeKind.COPYBOOK, "RECRD"), edge_kinds={EdgeKind.CALL}
    )
    assert result == set()


def test_paths_between_returns_the_full_chain():
    graph = _chain_graph()
    paths = paths_between(graph, (NodeKind.PROGRAM, "MAIN"), (NodeKind.PROGRAM, "LEAF"))
    assert paths == [
        [
            (NodeKind.PROGRAM, "MAIN"),
            (NodeKind.PROGRAM, "MID"),
            (NodeKind.PROGRAM, "LEAF"),
        ]
    ]


def test_paths_between_unreachable_nodes_is_empty():
    graph = _chain_graph()
    paths = paths_between(graph, (NodeKind.PROGRAM, "LEAF"), (NodeKind.PROGRAM, "MAIN"))
    assert paths == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_graph.query'`

- [ ] **Step 3: Write the implementation**

```python
# knowledge_graph/query.py
"""Thin query helpers over a merged knowledge graph (networkx.MultiDiGraph)."""

from __future__ import annotations

import networkx as nx

from interpreter.project.graph_types import EdgeKind, NodeKind

NodeId = tuple[NodeKind, str]


def _filtered_view(graph: nx.MultiDiGraph, edge_kinds: set[EdgeKind] | None) -> nx.MultiDiGraph:
    if edge_kinds is None:
        return graph
    view = nx.MultiDiGraph()
    view.add_nodes_from(graph.nodes(data=True))
    for u, v, data in graph.edges(data=True):
        if data["kind"] in edge_kinds:
            view.add_edge(u, v, **data)
    return view


def reachable_from(
    graph: nx.MultiDiGraph,
    start: NodeId,
    *,
    edge_kinds: set[EdgeKind] | None = None,
) -> set[NodeId]:
    """Every node reachable from start, optionally restricted to edge_kinds.
    start itself is not included."""
    view = _filtered_view(graph, edge_kinds)
    if start not in view:
        return set()
    return set(nx.descendants(view, start))


def callers_of(
    graph: nx.MultiDiGraph,
    target: NodeId,
    *,
    edge_kinds: set[EdgeKind] | None = None,
) -> set[NodeId]:
    """Every node with a direct edge into target, optionally restricted to edge_kinds."""
    if target not in graph:
        return set()
    callers: set[NodeId] = set()
    for source, _target, data in graph.in_edges(target, data=True):
        if edge_kinds is None or data["kind"] in edge_kinds:
            callers.add(source)
    return callers


def paths_between(
    graph: nx.MultiDiGraph,
    source: NodeId,
    target: NodeId,
    *,
    edge_kinds: set[EdgeKind] | None = None,
) -> list[list[NodeId]]:
    """All simple paths from source to target, optionally restricted to edge_kinds."""
    view = _filtered_view(graph, edge_kinds)
    if source not in view or target not in view:
        return []
    return list(nx.all_simple_paths(view, source, target))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_query.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add knowledge_graph/query.py tests/unit/knowledge_graph/test_query.py
git commit -m "feat: add reachable_from/callers_of/paths_between query helpers"
```

---

## Task 7: export.py — NDJSON round-trip (red-dragon-forge)

**Files:**
- Create: `knowledge_graph/export.py`
- Test: `tests/unit/knowledge_graph/test_export.py`

**Interfaces:**
- Consumes: a `networkx.MultiDiGraph` from Task 5; `GraphNode`/`GraphEdge`/`NodeKind`/`EdgeKind` from `interpreter.project.graph_types`.
- Produces: `write_ndjson(graph, nodes_path, edges_path) -> None`, `read_ndjson(nodes_path, edges_path) -> tuple[list[GraphNode], list[GraphEdge]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/knowledge_graph/test_export.py
"""Unit tests for NDJSON export/import round-tripping."""

from pathlib import Path

from knowledge_graph.export import read_ndjson, write_ndjson
from knowledge_graph.merge import merge_graph
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def _sample_graph():
    nodes = [
        GraphNode(id="MAIN", kind=NodeKind.PROGRAM, file_path="/src/MAIN.cbl"),
        GraphNode(id="RECRD", kind=NodeKind.COPYBOOK, attrs={"note": "shared"}),
    ]
    edges = [
        GraphEdge(
            source="MAIN",
            source_kind=NodeKind.PROGRAM,
            target="RECRD",
            target_kind=NodeKind.COPYBOOK,
            kind=EdgeKind.COPY,
            attrs={"line": 42},
        )
    ]
    return merge_graph(nodes, edges)


def test_write_ndjson_creates_both_files(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    assert nodes_path.is_file()
    assert edges_path.is_file()


def test_write_ndjson_one_line_per_node_and_edge(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    assert len(nodes_path.read_text().strip().splitlines()) == 2
    assert len(edges_path.read_text().strip().splitlines()) == 1


def test_read_ndjson_round_trips_nodes(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    nodes, _edges = read_ndjson(nodes_path, edges_path)
    by_id = {n.id: n for n in nodes}
    assert by_id["MAIN"].kind is NodeKind.PROGRAM
    assert by_id["MAIN"].file_path == "/src/MAIN.cbl"
    assert by_id["RECRD"].attrs == {"note": "shared"}


def test_read_ndjson_round_trips_edges(tmp_path: Path):
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    _nodes, edges = read_ndjson(nodes_path, edges_path)
    assert len(edges) == 1
    assert edges[0].source == "MAIN"
    assert edges[0].source_kind is NodeKind.PROGRAM
    assert edges[0].target == "RECRD"
    assert edges[0].target_kind is NodeKind.COPYBOOK
    assert edges[0].kind is EdgeKind.COPY
    assert edges[0].attrs == {"line": 42}


def test_round_trip_through_merge_graph_again_is_stable(tmp_path: Path):
    """read_ndjson's output feeds merge_graph() cleanly — the NDJSON seam
    the spec describes for a future graph-DB/visualization consumer."""
    graph = _sample_graph()
    nodes_path = tmp_path / "nodes.ndjson"
    edges_path = tmp_path / "edges.ndjson"
    write_ndjson(graph, nodes_path, edges_path)
    nodes, edges = read_ndjson(nodes_path, edges_path)
    rebuilt = merge_graph(nodes, edges)
    assert rebuilt.number_of_nodes() == graph.number_of_nodes()
    assert rebuilt.number_of_edges() == graph.number_of_edges()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_graph.export'`

- [ ] **Step 3: Write the implementation**

```python
# knowledge_graph/export.py
"""NDJSON export/import for the merged knowledge graph — one line per node,
one line per edge, following the same analysis-only NDJSON precedent
interpreter.project.cobol_connections already established.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def write_ndjson(graph: nx.MultiDiGraph, nodes_path: Path, edges_path: Path) -> None:
    """Write graph's nodes and edges as two NDJSON files."""
    with nodes_path.open("w") as f:
        for _key, data in graph.nodes(data=True):
            f.write(
                json.dumps(
                    {
                        "id": data["id"],
                        "kind": data["kind"].value,
                        "file_path": data["file_path"],
                        "attrs": data["attrs"],
                    }
                )
                + "\n"
            )

    with edges_path.open("w") as f:
        for source, target, data in graph.edges(data=True):
            f.write(
                json.dumps(
                    {
                        "source": source[1],
                        "source_kind": source[0].value,
                        "target": target[1],
                        "target_kind": target[0].value,
                        "kind": data["kind"].value,
                        "attrs": data["attrs"],
                    }
                )
                + "\n"
            )


def read_ndjson(
    nodes_path: Path, edges_path: Path
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Read (nodes, edges) back from NDJSON files written by write_ndjson."""
    nodes: list[GraphNode] = []
    with nodes_path.open() as f:
        for line in f:
            row = json.loads(line)
            nodes.append(
                GraphNode(
                    id=row["id"],
                    kind=NodeKind(row["kind"]),
                    file_path=row["file_path"],
                    attrs=row["attrs"],
                )
            )

    edges: list[GraphEdge] = []
    with edges_path.open() as f:
        for line in f:
            row = json.loads(line)
            edges.append(
                GraphEdge(
                    source=row["source"],
                    source_kind=NodeKind(row["source_kind"]),
                    target=row["target"],
                    target_kind=NodeKind(row["target_kind"]),
                    kind=EdgeKind(row["kind"]),
                    attrs=row["attrs"],
                )
            )

    return nodes, edges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_export.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add knowledge_graph/export.py tests/unit/knowledge_graph/test_export.py
git commit -m "feat: add NDJSON export/import for the merged knowledge graph"
```

---

## Task 8: Vendor vis-network + render.py (red-dragon-forge)

**Files:**
- Create: `knowledge_graph/vendor/vis-network.min.js` (fetched, not hand-written — see Step 1)
- Create: `knowledge_graph/vendor/VIS_NETWORK_LICENSE.md`
- Create: `knowledge_graph/render.py`
- Test: `tests/unit/knowledge_graph/test_render.py`

**Interfaces:**
- Consumes: a `networkx.MultiDiGraph` from Task 5.
- Produces: `render_html(graph, output_path: Path, *, title: str = "Knowledge Graph") -> None`. Task 9 calls this with this exact signature.

- [ ] **Step 1: Vendor vis-network**

vis-network's standalone UMD build bundles everything needed (including
vis-data) into one file — the right shape for inlining into a single
generated HTML file with no other script dependencies. Fetch a pinned
version:

```bash
mkdir -p knowledge_graph/vendor
curl -sL "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js" \
  -o knowledge_graph/vendor/vis-network.min.js
```

Verify the download succeeded and is a real, complete file:

```bash
wc -c knowledge_graph/vendor/vis-network.min.js
grep -q "vis-network" knowledge_graph/vendor/vis-network.min.js && echo OK
```

Expected: file size in the hundreds of KB (not 0, not a truncated HTML error
page from a failed fetch); `OK` printed.

Add a short license note (vis-network is MIT-licensed):

```markdown
# knowledge_graph/vendor/VIS_NETWORK_LICENSE.md
vis-network 9.1.9, standalone UMD build — https://github.com/visjs/vis-network
MIT License. Vendored (not a package dependency) so render_html() produces a
single self-contained HTML file with no CDN or server required at view time.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/knowledge_graph/test_render.py
"""Unit tests for render_html() — checks the generated file is well-formed
and self-contained; does not render in a browser."""

from pathlib import Path

import networkx as nx
import pytest

from knowledge_graph.render import render_html
from interpreter.project.graph_types import EdgeKind, NodeKind


def _tiny_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(
        (NodeKind.PROGRAM, "MAIN"),
        kind=NodeKind.PROGRAM,
        id="MAIN",
        file_path=None,
        attrs={},
    )
    graph.add_node(
        (NodeKind.PROGRAM, "HELPER"),
        kind=NodeKind.PROGRAM,
        id="HELPER",
        file_path=None,
        attrs={},
    )
    graph.add_edge(
        (NodeKind.PROGRAM, "MAIN"),
        (NodeKind.PROGRAM, "HELPER"),
        kind=EdgeKind.CALL,
        attrs={},
    )
    return graph


def test_render_html_writes_a_file(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    assert output.is_file()


def test_render_html_is_self_contained_no_cdn(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    content = output.read_text()
    assert "cdn." not in content.lower()
    assert "unpkg.com" not in content
    assert "<script src=" not in content


def test_render_html_embeds_node_and_edge_data(tmp_path: Path):
    output = tmp_path / "graph.html"
    render_html(_tiny_graph(), output)
    content = output.read_text()
    assert '"MAIN"' in content
    assert '"HELPER"' in content
    assert '"CALL"' in content


def test_render_html_raises_if_vis_network_not_vendored(tmp_path: Path, monkeypatch):
    import knowledge_graph.render as render_module

    monkeypatch.setattr(render_module, "_VENDOR_JS_PATH", tmp_path / "missing.js")
    with pytest.raises(FileNotFoundError):
        render_html(_tiny_graph(), tmp_path / "graph.html")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'knowledge_graph.render'`

- [ ] **Step 4: Write the implementation**

```python
# knowledge_graph/render.py
"""render_html() — a self-contained, interactive HTML visualization of a
merged knowledge graph. No server, no CDN: vis-network is vendored (see
knowledge_graph/vendor/) and inlined directly into the generated file.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

_VENDOR_JS_PATH = Path(__file__).parent / "vendor" / "vis-network.min.js"

_NODE_COLORS = {
    "PROGRAM": "#4C72B0",
    "COPYBOOK": "#55A868",
    "TRANSACTION": "#C44E52",
    "JOB": "#8172B2",
    "STEP": "#CCB974",
    "DATASET": "#64B5CD",
    "BMS_MAP": "#DD8452",
}

_EDGE_COLORS = {
    "CALL": "#4C72B0",
    "COPY": "#55A868",
    "XCTL": "#C44E52",
    "LINK": "#C44E52",
    "RETURN_TRANSID": "#C44E52",
    "STARTS": "#8172B2",
    "SENDS_MAP": "#DD8452",
    "RECEIVES_MAP": "#DD8452",
    "JCL_STEP_RUNS": "#8172B2",
    "READS": "#64B5CD",
    "WRITES": "#64B5CD",
    "UPDATES": "#64B5CD",
}

_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; font-family: sans-serif; }}
  #graph {{ width: 100%; height: 80vh; border: 1px solid #ccc; }}
  #controls {{ padding: 8px; }}
  #controls fieldset {{ display: inline-block; vertical-align: top; margin-right: 16px; }}
  label {{ display: block; font-size: 13px; }}
</style>
</head>
<body>
<div id="controls">
  <fieldset id="node-filters"><legend>Node kinds</legend></fieldset>
  <fieldset id="edge-filters"><legend>Edge kinds</legend></fieldset>
</div>
<div id="graph"></div>
<script>{vis_js}</script>
<script>
const allNodes = new vis.DataSet({nodes_json});
const allEdges = new vis.DataSet({edges_json});
const container = document.getElementById("graph");
const data = {{ nodes: allNodes, edges: allEdges }};
const options = {{
  nodes: {{ shape: "dot", size: 12 }},
  edges: {{ arrows: "to", font: {{ size: 10, align: "middle" }} }},
  physics: {{ stabilization: true }},
}};
const network = new vis.Network(container, data, options);

function uniqueValues(dataset, field) {{
  return [...new Set(dataset.get().map(item => item[field]))].sort();
}}

function buildFilterCheckboxes(fieldsetId, values, onChange) {{
  const fieldset = document.getElementById(fieldsetId);
  values.forEach(value => {{
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", onChange);
    checkbox.dataset.value = value;
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(" " + value));
    fieldset.appendChild(label);
  }});
}}

function checkedValues(fieldsetId) {{
  return [...document.querySelectorAll("#" + fieldsetId + " input:checked")].map(cb => cb.dataset.value);
}}

function applyFilters() {{
  const visibleNodeKinds = new Set(checkedValues("node-filters"));
  const visibleEdgeKinds = new Set(checkedValues("edge-filters"));
  allNodes.forEach(node => {{
    allNodes.update({{ id: node.id, hidden: !visibleNodeKinds.has(node.kind) }});
  }});
  allEdges.forEach(edge => {{
    allEdges.update({{ id: edge.id, hidden: !visibleEdgeKinds.has(edge.kind) }});
  }});
}}

buildFilterCheckboxes("node-filters", uniqueValues(allNodes, "kind"), applyFilters);
buildFilterCheckboxes("edge-filters", uniqueValues(allEdges, "kind"), applyFilters);

network.on("selectNode", params => {{
  const selected = params.nodes[0];
  const neighbors = new Set([selected]);
  allEdges.get().forEach(edge => {{
    if (edge.from === selected) neighbors.add(edge.to);
    if (edge.to === selected) neighbors.add(edge.from);
  }});
  allNodes.forEach(node => {{
    allNodes.update({{ id: node.id, opacity: neighbors.has(node.id) ? 1.0 : 0.15 }});
  }});
}});

network.on("deselectNode", () => {{
  allNodes.forEach(node => {{
    allNodes.update({{ id: node.id, opacity: 1.0 }});
  }});
}});
</script>
</body>
</html>
"""


def _node_id_str(key: tuple) -> str:
    kind, node_id = key
    return f"{kind.value}:{node_id}"


def render_html(
    graph: nx.MultiDiGraph, output_path: Path, *, title: str = "Knowledge Graph"
) -> None:
    """Render graph as one self-contained interactive HTML file at output_path.

    Requires the vendored vis-network build at
    knowledge_graph/vendor/vis-network.min.js (Task 8's vendoring step) —
    raises FileNotFoundError with a clear message if it's missing, rather
    than silently producing a broken page.
    """
    if not _VENDOR_JS_PATH.is_file():
        raise FileNotFoundError(
            f"vis-network not vendored at {_VENDOR_JS_PATH} — see "
            "docs/superpowers/plans/2026-07-07-cobol-knowledge-graph.md Task 8"
        )
    vis_js = _VENDOR_JS_PATH.read_text()

    vis_nodes = []
    for key, data in graph.nodes(data=True):
        vis_nodes.append(
            {
                "id": _node_id_str(key),
                "label": data["id"],
                "kind": data["kind"].value,
                "color": _NODE_COLORS.get(data["kind"].value, "#999999"),
                "title": f"{data['kind'].value}: {data['id']}",
            }
        )

    vis_edges = []
    for i, (source, target, data) in enumerate(graph.edges(data=True)):
        vis_edges.append(
            {
                "id": i,
                "from": _node_id_str(source),
                "to": _node_id_str(target),
                "kind": data["kind"].value,
                "label": data["kind"].value,
                "color": _EDGE_COLORS.get(data["kind"].value, "#999999"),
            }
        )

    html = _HTML_TEMPLATE.format(
        title=title,
        vis_js=vis_js,
        nodes_json=json.dumps(vis_nodes),
        edges_json=json.dumps(vis_edges),
    )
    output_path.write_text(html)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_render.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add knowledge_graph/render.py knowledge_graph/vendor/ tests/unit/knowledge_graph/test_render.py
git commit -m "feat: add render_html() — self-contained interactive graph visualization"
```

---

## Task 9: CardDemo end-to-end integration + visualization artifact (red-dragon-forge)

**Files:**
- Modify: `tests/integration/conftest.py` (add `jcl_bridge_jar` and `carddemo_home` fixtures)
- Create: `tests/integration/test_knowledge_graph_carddemo.py`
- Modify: `.gitignore` (ignore generated visualization output)

**Interfaces:**
- Consumes: `extract_cobol_connections` (Task 2), `extract_transaction_flow_graph` (Task 3), `extract_jcl_graph` (Task 4), `merge_graph` (Task 5), `reachable_from` (Task 6), `render_html` (Task 8).
- Produces: `tests/integration/output/carddemo_knowledge_graph.html` — the first-cut visualization deliverable, generated by running this test.

This is the proof the whole design actually connects: a real, verified
cross-source link in CardDemo (not synthesized for the test) —
`jackal/third-party/carddemo/app/jcl/READACCT.jcl`'s `STEP05` runs
`CBACT01C`, which `COPY`s `CVACT01Y`. This test's CICS side is a small
synthetic COBOL program that also `COPY`s `CVACT01Y`, giving one shared
`COPYBOOK` node reachable from both the real JCL job and a CICS
transaction — proving cross-source connectivity through a real, shared
copybook. The CICS side is synthetic (not a real CardDemo online program)
specifically to avoid requiring the separate bms-tools/`BMS_TOOLS_HOME`
toolchain that real CardDemo CICS programs using `SEND MAP`/`RECEIVE MAP`
need (see `cicada/tests/integration/cics/test_carddemo_signon_real.py`)
— the JCL and CALL/COPY sides use real, unmodified CardDemo source, which
is what this test is actually verifying.

- [ ] **Step 1: Add jcl_bridge_jar and carddemo_home fixtures**

```python
# tests/integration/conftest.py
"""Shared fixtures for red-dragon-forge integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def bridge_jar() -> str:
    """The ProLeap bridge JAR path — required, no default, no skip."""
    return os.environ["PROLEAP_BRIDGE_JAR"]


@pytest.fixture
def jcl_bridge_jar() -> str:
    """The jcl-bridge JAR path — required, no default, no skip."""
    return os.environ["JCL_BRIDGE_JAR"]


@pytest.fixture
def carddemo_home() -> Path:
    """Root of the CardDemo checkout. Uses jackal's own vendored copy by
    default (it has cbl/, cpy/, csd/, and jcl/ all present, avoiding any
    cross-checkout inconsistency); CARDDEMO_HOME overrides."""
    env = os.environ.get("CARDDEMO_HOME")
    if env:
        return Path(env)
    default = Path(__file__).parents[2] / "jackal" / "third-party" / "carddemo" / "app"
    if not default.is_dir():
        pytest.skip(f"CardDemo checkout not found at {default}; set CARDDEMO_HOME")
    return default
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_knowledge_graph_carddemo.py
"""End-to-end test: merge red-dragon's CALL/COPY graph, cicada's CICS flow
graph, and jackal's JCL graph over a small, real, cross-linked slice of
CardDemo, proving the three sources actually connect through a shared
node — not just that each extractor works in isolation. See this module's
plan task (docs/superpowers/plans/2026-07-07-cobol-knowledge-graph.md,
Task 9) for why the CICS side is a synthetic program while JCL/CALL/COPY
use real, unmodified CardDemo source.

Also generates this design's first-cut visualization deliverable:
tests/integration/output/carddemo_knowledge_graph.html.
"""

from __future__ import annotations

from pathlib import Path

from interpreter.cobol.cobol_parser import ProLeapCobolParser, make_cobol_parser
from interpreter.cobol.subprocess_runner import RealSubprocessRunner
from interpreter.project.cobol_connections import extract_cobol_connections
from interpreter.project.graph_types import NodeKind

from cics.flow_map import extract_transaction_flow_graph

from jackal.jcl_graph import extract_jcl_graph

from knowledge_graph.merge import merge_graph
from knowledge_graph.query import reachable_from
from knowledge_graph.render import render_html

_SYNTHETIC_CICS_PROGRAM = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SYNACCT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CVACT01Y.
       01 DFHCOMMAREA PIC X(100).
       PROCEDURE DIVISION.
           EXEC CICS RETURN TRANSID('CAVW') END-EXEC.
           STOP RUN.
"""

_SYNTHETIC_CSD = "DEFINE TRANSACTION(CAVW) GROUP(CARDDEMO) PROGRAM(SYNACCT)\n"


def test_readaccount_job_and_synthetic_cics_program_share_a_copybook_node(
    carddemo_home: Path, bridge_jar: str, jcl_bridge_jar: str
):
    cpy_dir = carddemo_home / "cpy"
    cbl_dir = carddemo_home / "cbl"

    # 1. JCL graph: real READACCT.jcl (STEP05 runs CBACT01C).
    jcl_text = (carddemo_home / "jcl" / "READACCT.jcl").read_text()
    jcl_nodes, jcl_edges = extract_jcl_graph(jcl_text)

    # 2. CALL/COPY graph: real CBACT01C.cbl (COPYs CVACT01Y, CODATECN;
    #    CALLs COBDATFT, CEE3ABD).
    cobol_parser = make_cobol_parser(copybook_dirs=[cpy_dir])
    call_nodes, call_edges = extract_cobol_connections(
        (cbl_dir / "CBACT01C.cbl").read_bytes(),
        copybook_dirs=[cpy_dir],
        program_source_dirs=[cbl_dir],
        parser=cobol_parser,
    )

    # 3. CICS flow graph: a synthetic program that also COPYs CVACT01Y — the
    #    deliberate cross-source link (see module docstring).
    cics_parser = ProLeapCobolParser(
        RealSubprocessRunner(), bridge_jar, copybook_dirs=[cpy_dir]
    )
    cics_nodes, cics_edges = extract_transaction_flow_graph(
        csd_source=_SYNTHETIC_CSD,
        bms_mapsets={},
        cobol_sources={"SYNACCT": _SYNTHETIC_CICS_PROGRAM},
        parser=cics_parser,
    )

    all_nodes = jcl_nodes + call_nodes + cics_nodes
    all_edges = jcl_edges + call_edges + cics_edges
    graph = merge_graph(all_nodes, all_edges)

    # The JCL job's batch program and the CICS transaction's program both
    # COPY the same real copybook — one shared node, not two.
    copybook_key = (NodeKind.COPYBOOK, "CVACT01Y")
    assert graph.has_node(copybook_key)

    from_job = reachable_from(graph, (NodeKind.JOB, "READACCT"))
    from_transaction = reachable_from(graph, (NodeKind.TRANSACTION, "CAVW"))
    assert copybook_key in from_job
    assert copybook_key in from_transaction

    # Deliverable: one interactive HTML visualization of this slice.
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "carddemo_knowledge_graph.html"
    render_html(
        graph, output_path, title="CardDemo Knowledge Graph (READACCT slice)"
    )
    assert output_path.is_file()
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `~/code/red-dragon-forge`, with `PROLEAP_BRIDGE_JAR` and `JCL_BRIDGE_JAR` set):

```bash
uv run --no-sync python -m pytest tests/integration/test_knowledge_graph_carddemo.py -v
```

Expected: FAIL — `extract_jcl_graph`/`extract_transaction_flow_graph`/`extract_cobol_connections` all exist by this point (Tasks 2-4 are done), so this should actually be close to passing already if Tasks 1-8 are correctly implemented; if it fails, the failure should point at a real integration gap (a node-id mismatch, an unexpected DD, etc.), not a missing symbol. Investigate and fix before proceeding — do not adjust the test to match broken behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync python -m pytest tests/integration/test_knowledge_graph_carddemo.py -v`
Expected: 1 passed

- [ ] **Step 5: Manually confirm the visualization is real**

Open `tests/integration/output/carddemo_knowledge_graph.html` in a browser.
Confirm: nodes are visible and colored by kind, a `JOB` node labeled
`READACCT` exists, a `TRANSACTION` node labeled `CAVW` exists, both connect
(via intermediate nodes) to a `COPYBOOK` node labeled `CVACT01Y`, the node-
kind and edge-kind filter checkboxes hide/show elements when unchecked, and
clicking a node dims non-neighbors.

- [ ] **Step 6: Ignore the generated artifact**

```bash
echo "tests/integration/output/" >> .gitignore
```

- [ ] **Step 7: Run the full test suite to confirm no regressions**

```bash
uv run --no-sync python -m pytest cicada/tests jackal/tests tests/ -q
```

Expected: all pass.

Tasks 1-2 also touched `vendor/red-dragon` directly — run its own suite too:

```bash
cd vendor/red-dragon
PROLEAP_BRIDGE_JAR=$(pwd)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
  uv run --no-sync python -m pytest tests/ -q
cd ../..
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_knowledge_graph_carddemo.py .gitignore
git commit -m "feat: end-to-end CardDemo knowledge graph test + first-cut HTML visualization"
```

---

## Post-plan notes

- This plan does not attempt full CardDemo coverage (all 29+ programs, every JCL job, the complete real CSD) — Task 9 validates cross-source connectivity on one real, verified slice. Extending `extract_jcl_graph`/`extract_cobol_connections`/`extract_transaction_flow_graph` calls across the rest of CardDemo's JCL/COBOL/CSD files, and re-rendering, is straightforward once this plan lands, but is deliberately out of scope here (see the spec's Non-goals).
- Dynamic CALL/XCTL/LINK targets and symbolic JCL `PGM=` parameters remain invisible to every extractor (spec's Open Risks) — unchanged by this plan.
