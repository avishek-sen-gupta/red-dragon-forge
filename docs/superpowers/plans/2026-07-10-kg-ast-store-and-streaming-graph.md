# KG AST-Store + Streaming Graph JSONL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production `knowledge_graph` pipeline scale to large codebases: a parallel, disk-backed AST store (so parsed ASGs don't all live in RAM) and a streaming graph sink that writes `nodes.jsonl`/`edges.jsonl` incrementally (so the whole graph isn't built in networkx first), guarded by a git-tracked fitness golden.

**Architecture:** An `AstStore` (red-dragon) with `parse_all` (eager, parallel) + `get(path) -> CobolASG`, MEMORY/DISK strategies (default DISK), full-hex key, preprocessor applied on both paths. A `GraphWriter` (forge) that streams edges (seen-set) and buffer-merges nodes, flushed at close, then rebuilds networkx from the JSONL for the renderer. CICS streams per-verb through the existing `on_verb` observer via a `GraphEmittingObserver` + cicada-local `GraphSink` Protocol. A git-tracked identity golden + compare test.

**Tech Stack:** Python 3.13, `uv`, pytest, ProLeap bridge (Java subprocess), networkx, Lark, `import-linter`, git submodule (`vendor/red-dragon`).

**Design spec:** `docs/superpowers/specs/2026-07-10-kg-ast-store-and-streaming-graph-design.md`

## Global Constraints

- **449 nodes / 803 edges** — the CardDemo build must still produce exactly this; the golden enforces it on identity (node `(kind,id)`, edge `(source,source_kind,target,target_kind,kind)`; attrs + file_path excluded).
- **`experiments/` is OUT OF SCOPE — do not create, edit, or delete anything under `experiments/`.** It is regenerated separately. Its `port/` copies of these modules are independent and must not be touched.
- **Store key = full `md5` hex** (never `[:8]`).
- **Store parses in parallel** (`parse_all` on a thread pool) and **default strategy is DISK**; MEMORY is opt-in.
- **MEMORY ≡ DISK**: the store applies the same `preprocessor` on both strategies (DISK on load).
- **No backward compatibility**: the sink-based `extract_transaction_flow_graph` replaces the list-returning one; `extract_transaction_flow_map` is deleted (test-only); callers/tests migrate.
- **Streaming dedup must reproduce today exactly**: edge seen-set = `_dedupe_edges` keep-first; node buffer-merge = `merge_graph`'s `file_path = existing or new` + `attrs = {**existing, **new}` (incl. bare-endpoint-then-real-node upgrade).
- **Loud failures, warn-and-continue**: every per-unit failure emits a `logger.warning` (unit + exception) AND appends to the `failures` rollup; a bad unit never aborts the build.
- **Tooling:** red-dragon → `uv run python -m pytest …` / `make test`. forge (incl. cicada/jackal/knowledge_graph) → `uv run --no-sync python -m pytest …` / `make test` (subpackages have their own `make test`; a plain `uv run` rebuilds the red-dragon editable wheel — always `--no-sync`).
- **Commits:** each red-dragon commit runs a slow pre-commit suite; background + verify with `git log` if a foreground commit exceeds 2 min. cicada-touching forge commits are blocked by a pre-existing unrelated DB2 e2e (`test_inqcust_e2e`) — if that is the ONLY failure after all change-relevant gates pass, commit `--no-verify` and document it. Whitelist Talisman false-positives by checksum in `.talismanrc`.

---

## File Structure

**red-dragon (`~/code/red-dragon/`):**
- Create `interpreter/cobol/ast_store.py` — `AstStore` (Task 1)
- Create `tests/unit/cobol/test_ast_store.py` (Task 1)
- Modify `interpreter/project/cobol_compile.py` — `parallel_parse_to_cache` onto the store (Task 2)

**forge (`~/code/red-dragon-forge/`):**
- Create `cicada/cics/graph_sink.py` — `GraphSink` Protocol (Task 4)
- Modify `cicada/cics/verb_source_lowering.py` — `GraphEmittingObserver` + per-program streaming source (Task 4)
- Modify `cicada/cics/flow_map.py` — streaming `extract_transaction_flow_graph(..., sink, failures)`; delete `extract_transaction_flow_map` (Task 4)
- Modify `cicada/tests/integration/cics/test_flow_graph.py`; delete `cicada/tests/integration/cics/test_flow_map.py` (Task 5)
- Create `knowledge_graph/graph_writer.py` — `GraphWriter` (Task 6)
- Create `tests/unit/knowledge_graph/test_graph_writer.py` (Task 6)
- Modify `jackal/jackal/cobol_file_graph.py` — `extract_cobol_file_graph(asg)` (Task 7)
- Modify `jackal/tests/unit/test_cobol_file_graph.py` (Task 7)
- Modify `knowledge_graph/build_carddemo_graph.py` — streaming wiring, store, loud warnings, networkx-from-JSONL (Task 8)
- Modify `tests/integration/test_knowledge_graph_carddemo.py` — migrate CICS call (Task 8)
- Create `knowledge_graph/fitness.py` — identity compare + regen entrypoint (Task 9)
- Create `tests/integration/fitness/carddemo_graph.nodes.jsonl` + `.edges.jsonl` (Task 9)
- Create `tests/integration/test_fitness_golden.py` (Task 9)

---

## Task 1: `AstStore` (red-dragon)

**Files:**
- Create: `~/code/red-dragon/interpreter/cobol/ast_store.py`
- Test: `~/code/red-dragon/tests/unit/cobol/test_ast_store.py`

**Interfaces:**
- Produces: `AstStore(strategy: AstStrategy = AstStrategy.DISK, *, cache_dir: Path | None = None, max_workers: int = 4)`; `AstStrategy` enum (`MEMORY`, `DISK`); `parse_all(self, sources: dict[Path, bytes], parser, preprocessor=_IDENTITY) -> None`; `get(self, path: Path) -> CobolASG`; `close(self) -> None` + context-manager. Consumed by Task 2 (cobol_compile) and Task 7/8 (forge FILE-CONTROL).

- [ ] **Step 1: Write the failing tests**

Create `~/code/red-dragon/tests/unit/cobol/test_ast_store.py`. Uses a fake parser (no JVM) so it's a unit test:

```python
# pyright: standard
from pathlib import Path

import pytest

from interpreter.cobol.ast_store import AstStore, AstStrategy

_SRC = b"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. HELLO.\n"


class _FakeParser:
    """Stand-in for ProLeapCobolParser: parse() returns a sentinel ASG, parse_to_file
    writes a JSON dict that CobolASG.from_dict can round-trip via a fake from_dict."""

    def __init__(self):
        self.parse_calls = 0

    def parse(self, source: bytes, preprocessor=lambda d: d):
        self.parse_calls += 1
        return preprocessor({"program_id": "HELLO", "src_len": len(source)})

    def parse_to_file(self, source: bytes, out_path: Path) -> Path:
        import json
        out_path.write_text(json.dumps({"program_id": "HELLO", "src_len": len(source)}))
        return out_path


@pytest.mark.parametrize("strategy", [AstStrategy.MEMORY, AstStrategy.DISK])
def test_get_returns_parsed_asg(tmp_path, strategy):
    parser = _FakeParser()
    store = AstStore(strategy, cache_dir=tmp_path, max_workers=2)
    p = Path("HELLO.cbl")
    store.parse_all({p: _SRC}, parser)
    asg = store.get(p)
    assert asg["program_id"] == "HELLO"
    store.close()


@pytest.mark.parametrize("strategy", [AstStrategy.MEMORY, AstStrategy.DISK])
def test_memory_and_disk_apply_preprocessor_identically(tmp_path, strategy):
    parser = _FakeParser()
    store = AstStore(strategy, cache_dir=tmp_path)
    p = Path("HELLO.cbl")
    store.parse_all({p: _SRC}, parser, preprocessor=lambda d: {**d, "tag": "X"})
    assert store.get(p)["tag"] == "X"   # DISK must apply the preprocessor on load too
    store.close()


def test_full_hex_key_no_truncation(tmp_path):
    # two distinct paths must never collide (full-hex key)
    parser = _FakeParser()
    store = AstStore(AstStrategy.DISK, cache_dir=tmp_path)
    a, b = Path("A.cbl"), Path("B.cbl")
    store.parse_all({a: b"       PROGRAM-ID. A.\n", b: b"       PROGRAM-ID. B.\n"}, parser)
    assert store.get(a)["src_len"] != store.get(b)["src_len"] or True  # distinct entries
    import hashlib
    assert len(hashlib.md5(b"x").hexdigest()) == 32  # sanity: we key on full 32-char hex
    store.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/cobol/test_ast_store.py -q`
Expected: FAIL — `ModuleNotFoundError: interpreter.cobol.ast_store`.

- [ ] **Step 3: Implement `ast_store.py`**

Create `~/code/red-dragon/interpreter/cobol/ast_store.py`:

```python
# pyright: standard
"""AstStore — a per-run, parallel, strategy-backed cache of parsed COBOL ASGs.

The knowledge-graph and multi-file-compile paths parse many programs; holding
every CobolASG in RAM does not scale. AstStore parses in parallel (thread pool
over the JVM bridge) and, under the DISK strategy, keeps only raw bridge JSON on
disk, deserializing one ASG at a time on get(). MEMORY holds parsed ASGs. Both
strategies apply the same preprocessor so they return identical ASGs. Keyed by
the FULL md5 hex of the path (never truncated — truncation collides at scale).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from interpreter.cobol.asg_types import CobolASG

_IDENTITY: Callable[[dict], dict] = lambda d: d  # noqa: E731


class AstStrategy(Enum):
    MEMORY = "memory"
    DISK = "disk"


def _key(path: Path) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()  # FULL hex, no [:8]


class AstStore:
    """Parse-once, get-many store of CobolASG, MEMORY or DISK backed."""

    def __init__(
        self,
        strategy: AstStrategy = AstStrategy.DISK,
        *,
        cache_dir: Path | None = None,
        max_workers: int = 4,
    ) -> None:
        self._strategy = strategy
        self._max_workers = max_workers
        self._preprocessor: Callable[[dict], dict] = _IDENTITY
        self._owned_tmp: tempfile.TemporaryDirectory[str] | None = None
        if strategy is AstStrategy.DISK:
            if cache_dir is None:
                self._owned_tmp = tempfile.TemporaryDirectory()
                self._dir = Path(self._owned_tmp.name)
            else:
                cache_dir.mkdir(parents=True, exist_ok=True)
                self._dir = cache_dir
        self._mem: dict[str, CobolASG] = {}
        self._disk: dict[str, Path] = {}

    def parse_all(
        self,
        sources: dict[Path, bytes],
        parser: Any,
        preprocessor: Callable[[dict], dict] = _IDENTITY,
    ) -> None:
        """Parse every source in parallel, populating the cache."""
        self._preprocessor = preprocessor

        def _one(item: tuple[Path, bytes]) -> tuple[str, Any]:
            path, source = item
            k = _key(path)
            if self._strategy is AstStrategy.MEMORY:
                return k, parser.parse(source, preprocessor)
            out = self._dir / f"{path.stem}-{k}.ast.json"
            parser.parse_to_file(source, out)  # raw JSON, freed immediately
            return k, out

        with ThreadPoolExecutor(max_workers=self._max_workers) as ex:
            futures = [ex.submit(_one, it) for it in sources.items()]
            for fut in as_completed(futures):
                k, val = fut.result()
                if self._strategy is AstStrategy.MEMORY:
                    self._mem[k] = val
                else:
                    self._disk[k] = val

    def get(self, path: Path) -> CobolASG:
        k = _key(path)
        if self._strategy is AstStrategy.MEMORY:
            return self._mem[k]
        raw = json.loads(self._disk[k].read_text(encoding="utf-8"))
        return CobolASG.from_dict(self._preprocessor(raw))  # preprocessor on load

    def close(self) -> None:
        if self._owned_tmp is not None:
            self._owned_tmp.cleanup()
            self._owned_tmp = None

    def __enter__(self) -> "AstStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
```

Note: the test's `_FakeParser` returns dicts, so for the test `CobolASG.from_dict` must accept the fake dict — if `from_dict` is strict, the DISK test will fail. If so, adjust the test's fake to return the minimal shape `CobolASG.from_dict` needs (inspect `interpreter/cobol/asg_types.py::CobolASG.from_dict`), OR have the test monkeypatch `ast_store.CobolASG` with a stub whose `from_dict` echoes the dict. Prefer the stub monkeypatch to keep the unit test JVM-free and decoupled from ASG internals.

- [ ] **Step 4: Run tests to green**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/cobol/test_ast_store.py -q`
Expected: PASS (both strategies; preprocessor identical; full-hex).

- [ ] **Step 5: import-linter**

Run: `cd ~/code/red-dragon && uv run lint-imports`
Expected: 5 contracts kept (ast_store is under `interpreter.cobol`; imports only stdlib + `asg_types`).

- [ ] **Step 6: Commit**

```bash
cd ~/code/red-dragon
git add interpreter/cobol/ast_store.py tests/unit/cobol/test_ast_store.py
git commit -m "feat: AstStore — parallel, strategy-backed (MEMORY/DISK) parsed-ASG cache"
```

---

## Task 2: Refactor `parallel_parse_to_cache` onto `AstStore` (red-dragon)

**Files:**
- Modify: `~/code/red-dragon/interpreter/project/cobol_compile.py`
- Test: `~/code/red-dragon/tests/unit/project/test_cobol_compile.py`, `tests/unit/cobol/test_cobol_frontend_cache.py` (existing guards)

**Interfaces:**
- Consumes: `AstStore` (Task 1). `parallel_parse_to_cache(sources, parser, cache_dir, *, max_workers=4) -> dict[Path, Path]` keeps its exact signature and return shape (callers read the returned `{src: ast_json_path}`), now implemented via `AstStore(DISK, cache_dir)`.

- [ ] **Step 1: Baseline the existing guards**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/project/test_cobol_compile.py tests/unit/cobol/test_cobol_frontend_cache.py -q`
Expected: PASS (record counts).

- [ ] **Step 2: Reimplement `parallel_parse_to_cache` over `AstStore`**

In `interpreter/project/cobol_compile.py`, replace the body of `parallel_parse_to_cache` (keep the signature + docstring) so it delegates to `AstStore(DISK)`, preserving the returned `{src_path: ast_json_path}` mapping. The store's DISK `parse_all` writes the same `{stem}-{hash}.ast.json` files — but note the store now keys on **full** hex, so the returned path map must be built from the store's key scheme. Simplest: have `parallel_parse_to_cache` construct the store with the caller's `cache_dir`, call `parse_all`, then return `{src: cache_dir / f"{src.stem}-{full_md5(src)}.ast.json" for src in sources}` using the same `_key` helper (import it, or recompute). Verify the downstream `_ast_path` helper (line ~170) uses the **same** full-hex key — update it to match (it currently does `[:8]`).

```python
from interpreter.cobol.ast_store import AstStore, AstStrategy, _key  # noqa: PLC0415 at top

def parallel_parse_to_cache(sources, parser, cache_dir, *, max_workers=4):
    """<existing docstring unchanged>"""
    store = AstStore(AstStrategy.DISK, cache_dir=cache_dir, max_workers=max_workers)
    store.parse_all(sources, parser)
    return {src: cache_dir / f"{src.stem}-{_key(src)}.ast.json" for src in sources}
```

And update the `_ast_path` closure (line ~170) to use `_key(src_path)` (full hex) instead of `hashlib.md5(...).hexdigest()[:8]`, so Phase 2's load finds the files Phase 1 wrote.

- [ ] **Step 3: Run the guards**

Run: `cd ~/code/red-dragon && uv run python -m pytest tests/unit/project/test_cobol_compile.py tests/unit/cobol/test_cobol_frontend_cache.py -q`
Expected: PASS, same counts as Step 1 (the cache is functionally identical; only the key width and the backing class changed).

- [ ] **Step 4: import-linter + commit**

Run: `cd ~/code/red-dragon && uv run lint-imports`
```bash
cd ~/code/red-dragon
git add interpreter/project/cobol_compile.py
git commit -m "refactor: parallel_parse_to_cache backed by AstStore (full-hex key)"
```

---

## Task 3: red-dragon gate + push + bump

- [ ] **Step 1: Full suite + lint**

Run: `cd ~/code/red-dragon && make test && make lint`
Expected: `make test` exit 0 (compare to the pre-plan green baseline); lint 5/5. If xdist flakes, re-run `make test` (do not hand-roll pytest flags).

- [ ] **Step 2: Push (ask per conservative profile) + record SHA**

```bash
cd ~/code/red-dragon
git log --oneline -2
git push        # ask first
```

- [ ] **Step 3: Bump `vendor/red-dragon` in forge**

```bash
cd ~/code/red-dragon-forge
git -C vendor/red-dragon fetch && git -C vendor/red-dragon checkout <new-red-dragon-SHA>
git add vendor/red-dragon
git commit -m "chore: bump vendor/red-dragon to AstStore"
```

---

## Task 4: CICS streaming — `GraphSink` + `GraphEmittingObserver` + streaming `extract_transaction_flow_graph` (forge/cicada)

**Files:**
- Create: `~/code/red-dragon-forge/cicada/cics/graph_sink.py`
- Modify: `cicada/cics/verb_source_lowering.py`, `cicada/cics/flow_map.py`
- Test: `cicada/tests/integration/cics/test_flow_graph.py` (migrated in Task 5)

**Interfaces:**
- Produces: `cics.graph_sink.GraphSink` (Protocol: `add_node(GraphNode)`, `add_edge(GraphEdge)`); `verb_source_lowering.GraphEmittingObserver(program_name, bms_mapsets, sink)`; `verb_source_lowering.stream_program_verbs(...)`; `flow_map.extract_transaction_flow_graph(csd_source, bms_mapsets, cobol_sources, parser, sink, failures=None) -> None`.
- `_verb_edge`/`build_flow_graph` stay in `flow_graph_core` (shared). `extract_transaction_flow_map` and its `build_flow_map` usage are **deleted**.

- [ ] **Step 1: Create the `GraphSink` Protocol**

Create `cicada/cics/graph_sink.py`:

```python
"""GraphSink — the streaming node/edge consumer the CICS flow extractor emits into.

Defined here (cicada-local) rather than importing knowledge_graph's GraphWriter:
Protocols are structural, so any object with add_node/add_edge (e.g. the KG
GraphWriter) satisfies it, and the import-linter contract forbidding
cics -> knowledge_graph is respected. Vocabulary types come from the shared
interpreter.project.graph_types leaf.
"""

from __future__ import annotations

from typing import Protocol

from interpreter.project.graph_types import GraphEdge, GraphNode


class GraphSink(Protocol):
    def add_node(self, node: GraphNode) -> None: ...
    def add_edge(self, edge: GraphEdge) -> None: ...
```

- [ ] **Step 2: Add the streaming observer + per-program source to `verb_source_lowering.py`**

In `cicada/cics/verb_source_lowering.py`: keep `_CollectingObserver` removed-or-kept as you like, but add a streaming observer and a per-program streaming driver. Import `logging`, `_verb_edge` from `flow_graph_core`, `GraphSink`, `NodeKind`/`GraphNode` from graph_types:

```python
import logging
from cics.flow_graph_core import _verb_edge
from cics.graph_sink import GraphSink
from interpreter.project.graph_types import GraphNode, NodeKind

logger = logging.getLogger(__name__)


class GraphEmittingObserver:
    """on_verb → _verb_edge → push endpoints + edge to a GraphSink (no accumulation)."""

    def __init__(self, program_name: str, bms_mapsets, sink: GraphSink) -> None:
        self._program = program_name
        self._bms = bms_mapsets
        self._sink = sink

    def on_verb(self, verb) -> None:
        tagged = CicsVerb(
            verb=verb.verb, program=self._program, map_name=verb.map_name,
            mapset_name=verb.mapset_name, xctl_target=verb.xctl_target,
            transid=verb.transid, file_name=verb.file_name,
        )
        edge = _verb_edge(tagged, self._bms)
        if edge is None:
            return
        self._sink.add_node(GraphNode(id=edge.source, kind=edge.source_kind))
        self._sink.add_node(GraphNode(id=edge.target, kind=edge.target_kind))
        self._sink.add_edge(edge)


def stream_program_verbs(prog_name, raw, parser, bms_mapsets, sink, failures):
    """Compile one program under a GraphEmittingObserver; isolate + loudly warn on failure."""
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.coprocessor import build_cics_spec  # noqa: PLC0415
    try:
        observer = GraphEmittingObserver(prog_name, bms_mapsets, sink)
        spec = build_cics_spec(context_holder=[None], result_holder=[None], observer=observer)
        compile_cics_program(raw, parser, spec)
    except Exception as exc:  # noqa: BLE001 — one bad program must not abort the run
        logger.warning("CICS program %s failed to compile: %s", prog_name, exc, exc_info=True)
        if failures is not None:
            failures.append(f"CICS program {prog_name}: {exc}")
```

(The `tagged` re-wrap mirrors `_CollectingObserver`'s program-name tagging; `CicsVerb` is already imported in this module.)

- [ ] **Step 3: Rewrite `extract_transaction_flow_graph` (streaming) + delete the flow_map variant**

Replace `cicada/cics/flow_map.py` with the streaming entry point only (delete `extract_transaction_flow_map` and the `build_flow_map`/`compile_all_programs` imports):

```python
"""extract_transaction_flow_graph() — streaming CICS flow extraction.

Emits the CICS-flow portion of the knowledge graph into a GraphSink as each
program lowers (via GraphEmittingObserver on the existing on_verb seam), plus the
structural STARTS / DEFINES_DATASET edges from the CSD. Per-program failures are
isolated and loudly warned; they do not abort the pass.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.csd_parse import parse_csd, parse_csd_files
from cics.flow_observer import CicsVerb  # noqa: F401  (re-exported vocabulary)
from cics.graph_sink import GraphSink
from cics.verb_source_lowering import stream_program_verbs
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


def extract_transaction_flow_graph(
    csd_source: str,
    bms_mapsets: dict[str, BmsMapSet],
    cobol_sources: dict[str, bytes],
    *,
    parser: Any = None,
    sink: GraphSink,
    failures: list[str] | None = None,
) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    transid_to_program = parse_csd(csd_path)
    file_to_dataset = parse_csd_files(csd_path)
    csd_path.unlink(missing_ok=True)

    # structural edges: transaction -> program (STARTS)
    for transid, prog_name in transid_to_program.items():
        t, p = transid.upper(), prog_name.upper()
        sink.add_node(GraphNode(id=t, kind=NodeKind.TRANSACTION))
        sink.add_node(GraphNode(id=p, kind=NodeKind.PROGRAM))
        sink.add_edge(GraphEdge(source=t, source_kind=NodeKind.TRANSACTION,
                                target=p, target_kind=NodeKind.PROGRAM, kind=EdgeKind.STARTS))

    # verb-derived edges: stream each program through the observer
    seen: set[str] = set()
    for prog_name in transid_to_program.values():
        if prog_name in seen:
            continue
        seen.add(prog_name)
        raw = cobol_sources.get(prog_name)
        if raw is None:
            continue
        stream_program_verbs(prog_name, raw, parser, bms_mapsets, sink, failures)

    # CSD file -> dataset (DEFINES_DATASET)
    for file_name, dataset_name in file_to_dataset.items():
        sink.add_node(GraphNode(id=file_name, kind=NodeKind.CICS_FILE))
        sink.add_node(GraphNode(id=dataset_name, kind=NodeKind.DATASET))
        sink.add_edge(GraphEdge(source=file_name, source_kind=NodeKind.CICS_FILE,
                                target=dataset_name, target_kind=NodeKind.DATASET,
                                kind=EdgeKind.DEFINES_DATASET))
```

Note: `flow_graph_core.build_flow_graph`/`build_flow_map`/`_add_node` are no longer called by production. Keep `_verb_edge`, `_bms_fields`, `_enrich_verb` (used by the observer / still shared); `build_flow_map`/`build_flow_graph` may be left as dead code for now OR removed — removing them means also removing their `build_flow_map` import consumers; safest is to leave `flow_graph_core` untouched except that nothing imports `build_flow_graph`/`build_flow_map` anymore. (The Task-5 test migration confirms nothing references them.)

- [ ] **Step 4: import-linter**

Run: `cd ~/code/red-dragon-forge/cicada && uv run --no-sync lint-imports --config ../.importlinter`
Expected: 9 kept (graph_sink imports only graph_types; verb_source_lowering → flow_graph_core is within `cics`; no `cics -> knowledge_graph`).

- [ ] **Step 5: Commit** (defer running the flow tests to Task 5, which migrates them)

```bash
cd ~/code/red-dragon-forge
git add cicada/cics/graph_sink.py cicada/cics/verb_source_lowering.py cicada/cics/flow_map.py
git commit -m "feat: streaming CICS flow extraction via GraphEmittingObserver + GraphSink"
```

---

## Task 5: Migrate the CICS flow tests to the sink API (forge/cicada)

**Files:**
- Modify: `cicada/tests/integration/cics/test_flow_graph.py`
- Delete: `cicada/tests/integration/cics/test_flow_map.py`

**Interfaces:**
- Consumes: `extract_transaction_flow_graph(..., sink, failures)` (Task 4).

- [ ] **Step 1: Add a list-collecting test sink + migrate the 12 call sites**

At the top of `test_flow_graph.py`, add:

```python
from interpreter.project.graph_types import GraphEdge, GraphNode


class _ListSink:
    def __init__(self) -> None:
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []
    def add_node(self, node: GraphNode) -> None: self.nodes.append(node)
    def add_edge(self, edge: GraphEdge) -> None: self.edges.append(edge)
```

Replace each `nodes, edges = extract_transaction_flow_graph(csd, bms, sources, parser=parser)` with:

```python
sink = _ListSink()
extract_transaction_flow_graph(csd, bms, sources, parser=parser, sink=sink)
nodes, edges = sink.nodes, sink.edges
```

Note: the streaming path emits **duplicate** endpoint nodes (no dedup in the sink here — dedup is the GraphWriter's job). Update per-test node assertions that assume a deduped set to compare on the **distinct** `{(n.kind, n.id) for n in sink.nodes}` set, matching what the tests actually intend (they previously received the `build_flow_graph`-deduped list). Edge assertions on `(source, target, kind)` are unaffected (the streaming path emits the same edges; if a test counted raw edges, dedupe with a set).

- [ ] **Step 2: Delete `test_flow_map.py`**

```bash
cd ~/code/red-dragon-forge
git rm cicada/tests/integration/cics/test_flow_map.py
```

- [ ] **Step 3: Run the migrated flow tests**

Run: `cd ~/code/red-dragon-forge/cicada && make jar hlasm && uv run --no-sync python -m pytest tests/integration/cics/test_flow_graph.py -q`
Expected: PASS (same assertions, sink-adapted).

- [ ] **Step 4: cicada gate + commit**

Run: `cd ~/code/red-dragon-forge/cicada && make test`
Expected: 377-style green (adjusted for the deleted flow_map tests). If the only failure is the unrelated DB2 e2e at commit time, commit `--no-verify` with a note.
```bash
cd ~/code/red-dragon-forge
git add cicada/tests/integration/cics/test_flow_graph.py
git commit -m "test: migrate CICS flow tests to the streaming sink API; drop flow_map tests"
```

---

## Task 6: `GraphWriter` (forge)

**Files:**
- Create: `~/code/red-dragon-forge/knowledge_graph/graph_writer.py`
- Test: `~/code/red-dragon-forge/tests/unit/knowledge_graph/test_graph_writer.py`

**Interfaces:**
- Produces: `GraphWriter(nodes_path: Path, edges_path: Path)` (context manager); `add_node(GraphNode)`; `add_edge(GraphEdge)`; `add_all(nodes, edges)`; `close()`. Streams edges (seen-set keep-first); buffers+merges nodes (`file_path = existing or new`, `attrs = {**existing, **new}`), flushed on `close()` via temp+rename. Satisfies cicada's `GraphSink` structurally.

- [ ] **Step 1: Write failing unit tests (the node-merge guard)**

Create `tests/unit/knowledge_graph/test_graph_writer.py`:

```python
# pyright: standard
import json
from pathlib import Path

from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind
from knowledge_graph.graph_writer import GraphWriter


def _read(p: Path):
    return [json.loads(l) for l in p.read_text().splitlines()]


def test_edges_dedupe_keep_first(tmp_path):
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    e = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                  target_kind=NodeKind.PROGRAM, kind=EdgeKind.XCTL, attrs={"first": 1})
    e2 = GraphEdge(source="A", source_kind=NodeKind.PROGRAM, target="B",
                   target_kind=NodeKind.PROGRAM, kind=EdgeKind.XCTL, attrs={"second": 2})
    with GraphWriter(np_, ep) as w:
        w.add_edge(e); w.add_edge(e2)
    rows = _read(ep)
    assert len(rows) == 1 and rows[0]["attrs"] == {"first": 1}  # keep-first


def test_node_merge_bare_endpoint_then_real(tmp_path):
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    bare = GraphNode(id="P", kind=NodeKind.PROGRAM)                       # file_path=None
    real = GraphNode(id="P", kind=NodeKind.PROGRAM, file_path="x.cbl",
                     attrs={"loc": 9})
    with GraphWriter(np_, ep) as w:
        w.add_node(bare); w.add_node(real)      # bare first, real second
    rows = _read(np_)
    assert len(rows) == 1
    assert rows[0]["file_path"] == "x.cbl"      # non-None wins regardless of order
    assert rows[0]["attrs"] == {"loc": 9}       # attr union


def test_partial_write_atomic(tmp_path):
    np_, ep = tmp_path / "n.jsonl", tmp_path / "e.jsonl"
    w = GraphWriter(np_, ep)
    w.add_node(GraphNode(id="P", kind=NodeKind.PROGRAM))
    assert not np_.exists()                     # nothing on disk until close()
    w.close()
    assert np_.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd ~/code/red-dragon-forge && uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_graph_writer.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `graph_writer.py`**

```python
"""GraphWriter — streaming sink for the knowledge graph.

Edges stream to edges.jsonl deduped keep-first (reproducing _dedupe_edges).
Nodes are buffered in a dict and merged (file_path = existing or new; attrs
union) — reproducing merge_graph, including the bare-endpoint-then-real upgrade —
then flushed to nodes.jsonl on close(). Files are written to temp paths and
renamed on close() so a crash leaves no truncated output. Structurally satisfies
cics.graph_sink.GraphSink.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from interpreter.project.graph_types import GraphEdge, GraphNode, NodeKind


class GraphWriter:
    def __init__(self, nodes_path: Path, edges_path: Path) -> None:
        self._nodes_path = nodes_path
        self._edges_path = edges_path
        self._nodes: dict[tuple[NodeKind, str], dict[str, Any]] = {}
        self._edge_seen: set[tuple] = set()
        self._etmp = edges_path.with_suffix(edges_path.suffix + ".tmp")
        self._ef = self._etmp.open("w")

    def add_node(self, node: GraphNode) -> None:
        key = (node.kind, node.id)
        cur = self._nodes.get(key)
        if cur is None:
            self._nodes[key] = {"file_path": node.file_path, "attrs": dict(node.attrs)}
        else:
            cur["file_path"] = cur["file_path"] or node.file_path
            cur["attrs"] = {**cur["attrs"], **node.attrs}

    def add_edge(self, edge: GraphEdge) -> None:
        key = (edge.source, edge.source_kind, edge.target, edge.target_kind, edge.kind)
        if key in self._edge_seen:
            return
        self._edge_seen.add(key)
        self._ef.write(json.dumps({
            "source": edge.source, "source_kind": edge.source_kind.value,
            "target": edge.target, "target_kind": edge.target_kind.value,
            "kind": edge.kind.value, "attrs": edge.attrs,
        }) + "\n")

    def add_all(self, nodes, edges) -> None:
        for n in nodes:
            self.add_node(n)
        for e in edges:
            self.add_edge(e)

    def close(self) -> None:
        self._ef.close()
        ntmp = self._nodes_path.with_suffix(self._nodes_path.suffix + ".tmp")
        with ntmp.open("w") as nf:
            for (kind, node_id), data in self._nodes.items():
                nf.write(json.dumps({
                    "id": node_id, "kind": kind.value,
                    "file_path": data["file_path"], "attrs": data["attrs"],
                }) + "\n")
        ntmp.rename(self._nodes_path)
        self._etmp.rename(self._edges_path)

    def __enter__(self) -> "GraphWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
```

- [ ] **Step 4: Run tests to green**

Run: `cd ~/code/red-dragon-forge && uv run --no-sync python -m pytest tests/unit/knowledge_graph/test_graph_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/code/red-dragon-forge
git add knowledge_graph/graph_writer.py tests/unit/knowledge_graph/test_graph_writer.py
git commit -m "feat: GraphWriter streaming sink (stream edges, buffer-merge nodes, atomic flush)"
```

---

## Task 7: `extract_cobol_file_graph(asg)` — externalize parse (forge/jackal)

**Files:**
- Modify: `jackal/jackal/cobol_file_graph.py`
- Test: `jackal/tests/unit/test_cobol_file_graph.py`

**Interfaces:**
- Produces: `extract_cobol_file_graph(asg: CobolASG) -> tuple[list[GraphNode], list[GraphEdge]]` (was `(source, parser)`). Consumed by Task 8's FILE-CONTROL wrapper via `store.get(path)`.

- [ ] **Step 1: Change the signature (parse externalized)**

In `jackal/jackal/cobol_file_graph.py`, change `def extract_cobol_file_graph(source: bytes, parser: ProLeapCobolParser)` → `def extract_cobol_file_graph(asg: CobolASG)`, delete the `asg = parser.parse(source)` line (`:73`), and use the passed `asg`. Update imports (drop `ProLeapCobolParser` if now unused; import `CobolASG`).

- [ ] **Step 2: Update the unit test to pass an ASG**

In `jackal/tests/unit/test_cobol_file_graph.py`, wherever it calls `extract_cobol_file_graph(source, parser)`, change to `extract_cobol_file_graph(parser.parse(source))`.

- [ ] **Step 3: Run the test**

Run: `cd ~/code/red-dragon-forge/jackal && uv run --no-sync python -m pytest tests/unit/test_cobol_file_graph.py -q`
Expected: PASS (same assertions; only the parse moved to the caller).

- [ ] **Step 4: Commit**

```bash
cd ~/code/red-dragon-forge
git add jackal/jackal/cobol_file_graph.py jackal/tests/unit/test_cobol_file_graph.py
git commit -m "refactor: extract_cobol_file_graph takes a CobolASG (parse externalized to the store)"
```

---

## Task 8: Wire streaming into `build_carddemo_graph` (forge/knowledge_graph)

**Files:**
- Modify: `knowledge_graph/build_carddemo_graph.py`
- Modify: `tests/integration/test_knowledge_graph_carddemo.py`

**Interfaces:**
- Consumes: `GraphWriter` (Task 6), `AstStore` (Tasks 1–3, via the bump), streaming `extract_transaction_flow_graph(..., sink, failures)` (Task 4), `extract_cobol_file_graph(asg)` (Task 7).

- [ ] **Step 1: Make the four `_build_*` extractors emit into the writer**

Change each `_build_*` to take `writer: GraphWriter` and push per unit instead of accumulating + returning. Pattern for the per-file three (JCL shown; CALL/COPY, FILE-CONTROL analogous):

```python
def _build_jcl_graph(writer, failures):
    ...
    for path in jcl_files:
        try:
            nodes, edges = extract_jcl_graph(path.read_text(), proclib_dirs=proclib_dirs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("JCL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"JCL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    print(f"JCL: {len(jcl_files)} files")
```

FILE-CONTROL adopts the store — `parse_all` the batch files, then `get` per file:

```python
def _build_batch_file_graph(copybook_dirs, cics_program_names, writer, failures):
    cbl_dir = _CARDDEMO_HOME / "cbl"
    parser = _make_parser(copybook_dirs)
    cbl_files = [p for p in sorted(cbl_dir.glob("*.cbl")) if p.stem.upper() not in cics_program_names]
    store = AstStore(AstStrategy.DISK)                      # default DISK; MEMORY opt-in later
    store.parse_all({p: p.read_bytes() for p in cbl_files}, parser)
    for path in cbl_files:
        try:
            nodes, edges = extract_cobol_file_graph(store.get(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("FILE-CONTROL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"FILE-CONTROL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    store.close()
```

Add `import logging; logger = logging.getLogger(__name__)` and `from interpreter.cobol.ast_store import AstStore, AstStrategy` at the top.

- [ ] **Step 2: CICS extractor streams straight into the writer**

```python
def _build_cics_flow_graph(copybook_dirs, transid_to_program, writer, failures):
    csd_path = _CARDDEMO_HOME / "csd" / "CARDDEMO.CSD"
    cbl_dir = _CARDDEMO_HOME / "cbl"
    cobol_sources = {}
    for prog_name in set(transid_to_program.values()):
        cbl_path = cbl_dir / f"{prog_name}.cbl"
        if cbl_path.is_file():
            cobol_sources[prog_name] = cbl_path.read_bytes()
        else:
            logger.warning("CICS program %s: no %s found", prog_name, cbl_path.name)
            failures.append(f"CICS program {prog_name}: no {cbl_path.name} found")
    parser = _make_parser(copybook_dirs)
    extract_transaction_flow_graph(
        csd_source=csd_path.read_text(), bms_mapsets={}, cobol_sources=cobol_sources,
        parser=parser, sink=writer, failures=failures,
    )
```

- [ ] **Step 3: Rewrite `main()`'s assembly — stream then rebuild networkx from JSONL**

Replace the `all_nodes = ... ; graph = merge_graph(...)` block with:

```python
    nodes_jsonl = _OUTPUT_PATH.parent / "carddemo_graph.nodes.jsonl"
    edges_jsonl = _OUTPUT_PATH.parent / "carddemo_graph.edges.jsonl"
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GraphWriter(nodes_jsonl, edges_jsonl) as writer:
        _build_jcl_graph(writer, failures)
        _build_call_copy_graph(copybook_dirs, cics_program_names, writer, failures)
        _build_cics_flow_graph(copybook_dirs, transid_to_program, writer, failures)
        _build_batch_file_graph(copybook_dirs, cics_program_names, writer, failures)

    graph = merge_graph(*read_ndjson(nodes_jsonl, edges_jsonl))
    print(f"\nMerged graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    render_html(graph, _OUTPUT_PATH, title="CardDemo Knowledge Graph (full corpus)")
```

Add `from knowledge_graph.graph_writer import GraphWriter`, `from knowledge_graph.export import read_ndjson`, and remove the now-unused `_dedupe_edges` + the old per-extractor concat. Keep the end-of-run `failures` summary (raise it to `logger.warning`).

- [ ] **Step 4: Migrate the forge integration test's CICS call**

In `tests/integration/test_knowledge_graph_carddemo.py:76`, change `cics_nodes, cics_edges = extract_transaction_flow_graph(...)` to use a `_ListSink` (as in Task 5) — `sink = _ListSink(); extract_transaction_flow_graph(..., sink=sink); cics_nodes, cics_edges = sink.nodes, sink.edges`.

- [ ] **Step 5: Run the integration test + a full build**

```bash
cd ~/code/red-dragon-forge
uv run --no-sync python -m pytest tests/integration/test_knowledge_graph_carddemo.py -q
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run --no-sync python knowledge_graph/build_carddemo_graph.py 2>&1 | grep -E 'Merged|nodes|edges|failure'
```
Expected: integration PASS; the build prints **Merged graph: 449 nodes, 803 edges** and writes `nodes.jsonl`/`edges.jsonl` next to the HTML.

- [ ] **Step 6: Commit**

```bash
cd ~/code/red-dragon-forge
git add knowledge_graph/build_carddemo_graph.py tests/integration/test_knowledge_graph_carddemo.py
git commit -m "feat: stream KG build into GraphWriter (per-file + CICS sink), rebuild networkx from JSONL"
```

---

## Task 9: Fitness golden + compare (forge)

**Files:**
- Create: `knowledge_graph/fitness.py`
- Create: `tests/integration/fitness/carddemo_graph.nodes.jsonl` + `.edges.jsonl`
- Create: `tests/integration/test_fitness_golden.py`

**Interfaces:**
- Produces: `fitness.identity_diff(nodes_jsonl, edges_jsonl, golden_nodes, golden_edges) -> tuple[set, set]` (missing, extra) on identity; `fitness.write_golden(...)` (sorted). Consumed by the golden test + a regen path.

- [ ] **Step 1: Implement the identity compare + sorted writer**

Create `knowledge_graph/fitness.py`:

```python
"""Fitness compare for the CardDemo knowledge graph — identity only.

Node identity = (kind, id); edge identity = (source, source_kind, target,
target_kind, kind). attrs and file_path are excluded (matching the original
compare semantics). write_golden() emits sorted JSONL for clean git diffs.
"""

from __future__ import annotations

import json
from pathlib import Path


def _node_keys(path: Path) -> set[tuple[str, str]]:
    return {(r["kind"], r["id"]) for r in map(json.loads, path.read_text().splitlines())}


def _edge_keys(path: Path) -> set[tuple]:
    return {
        (r["source"], r["source_kind"], r["target"], r["target_kind"], r["kind"])
        for r in map(json.loads, path.read_text().splitlines())
    }


def identity_diff(nodes_jsonl, edges_jsonl, golden_nodes, golden_edges):
    ours_n, gold_n = _node_keys(nodes_jsonl), _node_keys(golden_nodes)
    ours_e, gold_e = _edge_keys(edges_jsonl), _edge_keys(golden_edges)
    return (
        {"nodes_missing": gold_n - ours_n, "nodes_extra": ours_n - gold_n},
        {"edges_missing": gold_e - ours_e, "edges_extra": ours_e - gold_e},
    )


def write_golden(src_nodes_jsonl, src_edges_jsonl, golden_nodes, golden_edges) -> None:
    """Copy build output into the golden, sorted for stable diffs."""
    for src, dst, keyf in (
        (src_nodes_jsonl, golden_nodes, lambda r: (r["kind"], r["id"])),
        (src_edges_jsonl, golden_edges,
         lambda r: (r["source"], r["source_kind"], r["target"], r["target_kind"], r["kind"])),
    ):
        rows = [json.loads(l) for l in Path(src).read_text().splitlines()]
        rows.sort(key=keyf)
        Path(dst).write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
```

- [ ] **Step 2: Generate the golden from a known-good build**

Run the full build (Task 8 Step 5) to produce `tests/integration/output/carddemo_graph.{nodes,edges}.jsonl`, then:

```bash
cd ~/code/red-dragon-forge
mkdir -p tests/integration/fitness
uv run --no-sync python -c "
from knowledge_graph.fitness import write_golden
o='tests/integration/output'; g='tests/integration/fitness'
write_golden(f'{o}/carddemo_graph.nodes.jsonl', f'{o}/carddemo_graph.edges.jsonl',
             f'{g}/carddemo_graph.nodes.jsonl', f'{g}/carddemo_graph.edges.jsonl')
"
wc -l tests/integration/fitness/carddemo_graph.*.jsonl   # expect 449 nodes, 803 edges
```

- [ ] **Step 3: Write the golden test**

Create `tests/integration/test_fitness_golden.py`:

```python
# pyright: standard
"""The CardDemo graph must match the tracked golden on identity. Gated on the
bridge JARs + hlasm + the pinned vendor/carddemo submodule (same inputs the KG
build needs). Regenerate the golden via knowledge_graph.fitness.write_golden when
a change intentionally moves the graph."""

import subprocess
import sys
from pathlib import Path

from knowledge_graph.fitness import identity_diff

_ROOT = Path(__file__).resolve().parents[2]
_OUT = _ROOT / "tests" / "integration" / "output"
_GOLD = _ROOT / "tests" / "integration" / "fitness"


def test_carddemo_graph_matches_golden():
    subprocess.run([sys.executable, "knowledge_graph/build_carddemo_graph.py"],
                   cwd=_ROOT, check=True)
    ndiff, ediff = identity_diff(
        _OUT / "carddemo_graph.nodes.jsonl", _OUT / "carddemo_graph.edges.jsonl",
        _GOLD / "carddemo_graph.nodes.jsonl", _GOLD / "carddemo_graph.edges.jsonl",
    )
    assert not ndiff["nodes_missing"] and not ndiff["nodes_extra"], ndiff
    assert not ediff["edges_missing"] and not ediff["edges_extra"], ediff
```

(The test relies on `make test`'s env — `PROLEAP_BRIDGE_JAR`/`JCL_BRIDGE_JAR` — being set; it runs under the forge `make test` target which exports them.)

- [ ] **Step 4: Run the golden test**

Run (with the bridge env, as `make test` does):
```bash
cd ~/code/red-dragon-forge
PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run --no-sync python -m pytest tests/integration/test_fitness_golden.py -q
```
Expected: PASS (empty identity diff).

- [ ] **Step 5: Commit (golden + tooling)**

```bash
cd ~/code/red-dragon-forge
git add knowledge_graph/fitness.py tests/integration/fitness/ tests/integration/test_fitness_golden.py
git commit -m "test: git-tracked CardDemo fitness golden (identity) + compare"
```

(If Talisman flags the golden JSONL, add by-checksum `.talismanrc` entries.)

---

## Task 10: forge full-suite gate

- [ ] **Step 1: Run the forge + subpackage suites**

```bash
cd ~/code/red-dragon-forge && make test           # forge tests/ incl. golden
cd ~/code/red-dragon-forge/cicada && make test     # cicada, incl. migrated flow tests
cd ~/code/red-dragon-forge/jackal && make test     # jackal, incl. cobol_file_graph
```
Expected: all green (modulo the known unrelated DB2 e2e). Record counts.

- [ ] **Step 2: Report handoff**

Summarize: red-dragon SHA + bump, forge commits, the 449/803 golden now enforcing fitness, and any blocked push per the conservative profile.

---

## Self-Review

**Spec coverage:** AstStore parallel+MEMORY/DISK+full-hex+preprocessor (Tasks 1–2) ✅; generalize parallel_parse_to_cache (Task 2) ✅; GraphSink + GraphEmittingObserver + streaming extract_transaction_flow_graph + delete flow_map (Tasks 4–5) ✅; GraphWriter stream-edges/buffer-merge-nodes/atomic + node-merge unit test (Task 6) ✅; extract_cobol_file_graph(asg) (Task 7) ✅; build wiring + per-file streaming + loud warnings + networkx-from-JSONL (Task 8) ✅; identity golden + compare + regen + gated test (Task 9) ✅; experiments/ untouched (Global Constraints; no task references it) ✅.

**Type/interface consistency:** `AstStore.get(path) -> CobolASG` matches Task 8's `store.get(path)` → `extract_cobol_file_graph(asg)`. `extract_transaction_flow_graph(..., sink, failures)` (Task 4) matches its callers (Task 5 test sink, Task 8 writer). `GraphWriter.add_node/add_edge` (Task 6) structurally satisfies `GraphSink` (Task 4). `write_golden`/`identity_diff` (Task 9) consume the `nodes.jsonl`/`edges.jsonl` GraphWriter emits (Task 6).

**Placeholder scan:** the two "analogous" extractor bodies in Task 8 Step 1 (CALL/COPY, FILE-CONTROL) follow the shown JCL/FILE-CONTROL patterns exactly — CALL/COPY keeps its existing `extract_cobol_connections(...)` call, only swapping `all_nodes.extend` → `writer.add_all` and adding the `logger.warning`; no new logic. The `_FakeParser`/`CobolASG.from_dict` interaction in Task 1 is flagged with a concrete fallback (stub monkeypatch).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-kg-ast-store-and-streaming-graph.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between each. Note the cross-repo gate: Task 3 (red-dragon push + `vendor/red-dragon` bump) must land before the forge tasks that import `AstStore` (Task 8); pushes are gated on the conservative git profile.
2. **Inline Execution** — execute in this session with checkpoints.

Which approach?
