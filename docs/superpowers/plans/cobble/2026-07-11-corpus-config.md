# Config-Driven Corpus Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let cobble extract a knowledge graph from any COBOL/CICS/JCL corpus by pointing `build_graph.py`/`generate_sym.py` at a YAML config file, instead of hardcoding the CardDemo corpus location in Python.

**Architecture:** A new `corpus_config.py` (repo root) defines frozen `CorpusConfig`/`BmsConfig` dataclasses plus pure dict→dataclass parsing and imperative YAML-file loading. `build_port.py` is renamed to `build_graph.py` and refactored to take a required `--config <path>` CLI flag instead of hardcoded `_CARDDEMO_HOME`-derived constants; `generate_sym.py` gets the same treatment. A new tracked `config/carddemo.yaml` captures today's CardDemo layout exactly, and the `Makefile`'s `build`/`sym` targets pass it — so existing behavior (449/803 golden graph) is unchanged, but a user can now write their own YAML config and run `python build_graph.py --config their-config.yaml` against a different corpus.

**Tech Stack:** Python 3.11+, PyYAML (new dependency), pytest, `uv`.

**Reference spec:** `docs/superpowers/specs/2026-07-11-corpus-config-design.md`

## Global Constraints

- Frozen dataclasses only (`@dataclass(frozen=True)`), no exceptions.
- No `None` as a default parameter — list-shaped fields default to an empty tuple `()`, never `None`.
- Fully qualified imports (`cobble.*`), no relative imports — matches cobble's existing convention.
- Every required config key is read without a fallback default — a missing key raises (`KeyError`) rather than silently guessing a CardDemo path.
- `csd_files: []` (or omitted) is a *valid* config meaning "no CICS in this corpus" — must not raise, and `build_graph.py` must skip the CICS-flow-graph stage cleanly (printed note, not a crash).
- Relative paths inside the YAML resolve against the current working directory (matching today's implicit behavior) — NOT against the config file's own location. Do not add path-resolution logic beyond `Path(str)`.
- PyYAML is added as a **runtime** dependency (`dependencies = [...]` in `pyproject.toml`, not `dependency-groups.dev`) since `build_graph.py`/`generate_sym.py` need it at runtime, not just in tests.
- Talisman: if it flags a false positive, only **append** a new entry to `.talismanrc` — never modify or remove an existing entry. Ask the user before adding a new entry (per this session's established pattern).
- The bridge JAR env vars (`PROLEAP_BRIDGE_JAR`, `JCL_BRIDGE_JAR`) are explicitly **out of scope** — they stay exactly as they are today.
- `compare.py`'s golden-file check is explicitly **out of scope** — it stays CardDemo-specific.

---

### Task 1: `corpus_config.py` — dataclasses, pure parsing, YAML loading

**Files:**
- Create: `corpus_config.py` (repo root)
- Test: `tests/test_corpus_config.py` (repo root of `tests/`, mirrors `corpus_config.py` living at repo root)
- Modify: `pyproject.toml` (add `pyyaml` to `dependencies`)

**Interfaces:**
- Produces: `CorpusConfig` (frozen dataclass: `cobol_dir: Path`, `cobol_globs: tuple[str, ...]`, `jcl_dir: Path`, `jcl_globs: tuple[str, ...]`, `proclib_dirs: tuple[Path, ...]`, `csd_files: tuple[Path, ...]`, `copybook_dirs: tuple[Path, ...]`, `out_dir: Path`), `BmsConfig` (frozen dataclass: `bms_dir: Path`, `macros_dir: Path`, `sym_dir: Path`), `load_corpus_config(path: Path) -> CorpusConfig`, `load_bms_config(path: Path) -> BmsConfig`. Task 3 and Task 4 consume these.

- [ ] **Step 1: Add PyYAML dependency**

Run: `uv add pyyaml`

Expected: `pyproject.toml`'s `[project].dependencies` list gains `"pyyaml>=6.0"` (or whatever version `uv` resolves), and `uv.lock` updates.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_corpus_config.py`:

```python
from pathlib import Path

import pytest

from corpus_config import (
    BmsConfig,
    CorpusConfig,
    _bms_config_from_dict,
    _corpus_config_from_dict,
    load_bms_config,
    load_corpus_config,
)


def test_corpus_config_from_dict_full() -> None:
    data = {
        "cobol_dir": "vendor/carddemo/app/cbl",
        "cobol_globs": ["*.cbl"],
        "jcl_dir": "vendor/carddemo/app/jcl",
        "jcl_globs": ["*.jcl", "*.JCL"],
        "proclib_dirs": ["vendor/carddemo/app/proc"],
        "csd_files": ["vendor/carddemo/app/csd/CARDDEMO.CSD"],
        "copybook_dirs": ["sym", "vendor/carddemo/app/cpy"],
        "out_dir": "out",
    }
    config = _corpus_config_from_dict(data)
    assert config == CorpusConfig(
        cobol_dir=Path("vendor/carddemo/app/cbl"),
        cobol_globs=("*.cbl",),
        jcl_dir=Path("vendor/carddemo/app/jcl"),
        jcl_globs=("*.jcl", "*.JCL"),
        proclib_dirs=(Path("vendor/carddemo/app/proc"),),
        csd_files=(Path("vendor/carddemo/app/csd/CARDDEMO.CSD"),),
        copybook_dirs=(Path("sym"), Path("vendor/carddemo/app/cpy")),
        out_dir=Path("out"),
    )


def test_corpus_config_from_dict_missing_optional_fields_default_to_empty_tuple() -> None:
    data = {
        "cobol_dir": "cbl", "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl", "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "out_dir": "out",
    }
    config = _corpus_config_from_dict(data)
    assert config.csd_files == ()
    assert config.proclib_dirs == ()


def test_corpus_config_from_dict_empty_csd_files_is_valid() -> None:
    data = {
        "cobol_dir": "cbl", "cobol_globs": ["*.cbl"],
        "jcl_dir": "jcl", "jcl_globs": ["*.jcl"],
        "copybook_dirs": ["cpy"],
        "out_dir": "out",
        "csd_files": [],
    }
    assert _corpus_config_from_dict(data).csd_files == ()


def test_corpus_config_from_dict_missing_required_key_raises() -> None:
    with pytest.raises(KeyError, match="cobol_dir"):
        _corpus_config_from_dict({})


def test_bms_config_from_dict() -> None:
    data = {"bms_dir": "app/bms", "macros_dir": "bms-macros", "sym_dir": "sym"}
    assert _bms_config_from_dict(data) == BmsConfig(
        bms_dir=Path("app/bms"), macros_dir=Path("bms-macros"), sym_dir=Path("sym")
    )


def test_bms_config_from_dict_missing_required_key_raises() -> None:
    with pytest.raises(KeyError, match="bms_dir"):
        _bms_config_from_dict({})


def test_load_corpus_config_reads_yaml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.yaml"
    config_path.write_text(
        "corpus:\n"
        "  cobol_dir: cbl\n"
        '  cobol_globs: ["*.cbl"]\n'
        "  jcl_dir: jcl\n"
        '  jcl_globs: ["*.jcl"]\n'
        '  copybook_dirs: ["cpy"]\n'
        "  out_dir: out\n"
    )
    config = load_corpus_config(config_path)
    assert config.cobol_dir == Path("cbl")
    assert config.csd_files == ()


def test_load_bms_config_reads_yaml_file(tmp_path: Path) -> None:
    config_path = tmp_path / "test.yaml"
    config_path.write_text(
        "bms:\n"
        "  bms_dir: app/bms\n"
        "  macros_dir: bms-macros\n"
        "  sym_dir: sym\n"
    )
    config = load_bms_config(config_path)
    assert config.bms_dir == Path("app/bms")


def test_load_corpus_config_missing_corpus_section_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "test.yaml"
    config_path.write_text("bms:\n  bms_dir: x\n  macros_dir: y\n  sym_dir: z\n")
    with pytest.raises(KeyError, match="corpus"):
        load_corpus_config(config_path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_corpus_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'corpus_config'` (the file doesn't exist yet).

- [ ] **Step 4: Write `corpus_config.py`**

Create `corpus_config.py`:

```python
"""corpus_config.py — YAML-driven corpus configuration for build_graph.py and
generate_sym.py, so cobble can extract a knowledge graph / generate BMS
copybooks from any COBOL/CICS/JCL corpus without editing Python source.

Split into a pure core (dict -> dataclass, no I/O) and an imperative shell
(reads the YAML file off disk). Every required field is read without a
fallback default -- a missing key raises rather than silently guessing a
path. List-shaped fields are never None; an absent/empty key means an empty
tuple. Relative paths are NOT resolved here -- they stay relative to
whatever the caller's current working directory is (matching today's
implicit behavior of running scripts from the repo root).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CorpusConfig:
    cobol_dir: Path
    cobol_globs: tuple[str, ...]
    jcl_dir: Path
    jcl_globs: tuple[str, ...]
    proclib_dirs: tuple[Path, ...]
    csd_files: tuple[Path, ...]
    copybook_dirs: tuple[Path, ...]
    out_dir: Path


@dataclass(frozen=True)
class BmsConfig:
    bms_dir: Path
    macros_dir: Path
    sym_dir: Path


def _require(data: Mapping, key: str) -> object:
    if key not in data:
        raise KeyError(f"config missing required key: {key!r}")
    return data[key]


def _corpus_config_from_dict(data: Mapping) -> CorpusConfig:
    return CorpusConfig(
        cobol_dir=Path(_require(data, "cobol_dir")),
        cobol_globs=tuple(_require(data, "cobol_globs")),
        jcl_dir=Path(_require(data, "jcl_dir")),
        jcl_globs=tuple(_require(data, "jcl_globs")),
        proclib_dirs=tuple(Path(p) for p in data.get("proclib_dirs", ())),
        csd_files=tuple(Path(p) for p in data.get("csd_files", ())),
        copybook_dirs=tuple(Path(p) for p in _require(data, "copybook_dirs")),
        out_dir=Path(_require(data, "out_dir")),
    )


def _bms_config_from_dict(data: Mapping) -> BmsConfig:
    return BmsConfig(
        bms_dir=Path(_require(data, "bms_dir")),
        macros_dir=Path(_require(data, "macros_dir")),
        sym_dir=Path(_require(data, "sym_dir")),
    )


def load_corpus_config(path: Path) -> CorpusConfig:
    data = yaml.safe_load(path.read_text())
    return _corpus_config_from_dict(_require(data, "corpus"))


def load_bms_config(path: Path) -> BmsConfig:
    data = yaml.safe_load(path.read_text())
    return _bms_config_from_dict(_require(data, "bms"))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_corpus_config.py -v`
Expected: 9 passed.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `make test`
Expected: all tests pass (66 existing + 9 new = 75).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock corpus_config.py tests/test_corpus_config.py
git commit -m "cobble: add corpus_config.py for YAML-driven corpus configuration"
```

If Talisman flags a false positive (e.g. on `uv.lock`'s hashes, as it has every time this session), stop and ask the user before appending a `.talismanrc` entry — do not modify/remove existing entries.

---

### Task 2: `config/carddemo.yaml` — tracked config matching today's CardDemo layout

**Files:**
- Create: `config/carddemo.yaml`

**Interfaces:**
- Consumes: the YAML schema defined by `CorpusConfig`/`BmsConfig` in Task 1 (`corpus:` / `bms:` top-level keys).
- Produces: the config path `config/carddemo.yaml` that Task 3's `build_graph.py` and Task 4's `generate_sym.py`, and Task 5's `Makefile`, all reference.

- [ ] **Step 1: Create the config file**

Create `config/carddemo.yaml`:

```yaml
corpus:
  cobol_dir: vendor/carddemo/app/cbl
  cobol_globs: ["*.cbl"]
  jcl_dir: vendor/carddemo/app/jcl
  jcl_globs: ["*.jcl", "*.JCL"]
  proclib_dirs:
    - vendor/carddemo/app/proc
  csd_files:
    - vendor/carddemo/app/csd/CARDDEMO.CSD
  copybook_dirs:
    - sym
    - vendor/carddemo/app/cpy
    - vendor/carddemo/app/cpy-bms
    - cics-copybooks
  out_dir: out

bms:
  bms_dir: vendor/carddemo/app/bms
  macros_dir: bms-macros
  sym_dir: sym
```

- [ ] **Step 2: Verify it loads correctly**

Run:
```bash
uv run python -c "
from pathlib import Path
from corpus_config import load_corpus_config, load_bms_config
corpus = load_corpus_config(Path('config/carddemo.yaml'))
bms = load_bms_config(Path('config/carddemo.yaml'))
print(corpus)
print(bms)
"
```
Expected: prints a `CorpusConfig(...)` and `BmsConfig(...)` with the paths above, no errors.

- [ ] **Step 3: Commit**

```bash
git add config/carddemo.yaml
git commit -m "cobble: add tracked config/carddemo.yaml corpus config"
```

---

### Task 3: Rename `build_port.py` → `build_graph.py`, refactor to use `--config`

**Files:**
- Create: `build_graph.py` (via `git mv build_port.py build_graph.py`, then edit)
- Delete: `build_port.py` (via the `git mv` above — do not leave both files)

**Interfaces:**
- Consumes: `CorpusConfig`, `load_corpus_config` from Task 1's `corpus_config.py`.
- Produces: no new interfaces consumed by later tasks — `build_graph.py`'s `main()` is the entry point invoked by `make build` (Task 5).

- [ ] **Step 1: Rename the file**

Run: `git mv build_port.py build_graph.py`

- [ ] **Step 2: Replace the full contents of `build_graph.py`**

Replace the entire contents of `build_graph.py` with:

```python
"""build_graph.py — config-driven knowledge-graph extraction over a
COBOL/CICS/JCL corpus.

Runs the same four extractors as production (JCL, CALL/COPY, CICS flow, batch
FILE-CONTROL) entirely through the ``cobble.*`` package tree (a byte-for-byte +
import-rewrite port of the production extractors, with ONE seam: VM-free CICS
verb sourcing in cobble/cics/verb_source_asg.py). No VM, no compile/lower
pipeline.

Corpus location and layout come from a YAML config file (see
corpus_config.py) passed via --config -- nothing about the corpus is
hardcoded here. Writes <out_dir>/{nodes,edges}.jsonl and prints per-extractor
+ merged counts.

Env:
    PROLEAP_BRIDGE_JAR=$(pwd)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
    JCL_BRIDGE_JAR=$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # make `cobble`/`corpus_config` importable

from corpus_config import CorpusConfig, load_corpus_config

from cobble.interpreter.cobol.ast_store import AstStore, AstStrategy
from cobble.interpreter.cobol.cobol_parser import ProLeapCobolParser
from cobble.interpreter.cobol.subprocess_runner import RealSubprocessRunner
from cobble.interpreter.project.cobol_imports import extract_cobol_imports
from cobble.interpreter.project.import_types import ImportKind
from cobble.interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind

from cobble.cics.csd_parse import parse_csd
from cobble.cics.flow_map import extract_transaction_flow_graph

from cobble.jackal.cobol_file_graph import extract_cobol_file_graph
from cobble.jackal.jcl_graph import extract_jcl_graph

from cobble.knowledge_graph.graph_writer import GraphWriter
from cobble.knowledge_graph.merge import merge_graph

logger = logging.getLogger(__name__)


def _bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


def _make_parser(config: CorpusConfig) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(), _bridge_jar(), copybook_dirs=list(config.copybook_dirs)
    )


def _matching_files(directory: Path, globs: tuple[str, ...]) -> list[Path]:
    return sorted({p for pattern in globs for p in directory.glob(pattern)})


def _load_transid_to_program(config: CorpusConfig) -> dict[str, str]:
    merged: dict[str, str] = {}
    for csd_file in config.csd_files:
        merged.update(parse_csd(csd_file))
    return merged


def _build_jcl_graph(config: CorpusConfig, writer: GraphWriter, failures: list[str]) -> None:
    jcl_files = _matching_files(config.jcl_dir, config.jcl_globs)
    for path in jcl_files:
        try:
            nodes, edges = extract_jcl_graph(path.read_text(), proclib_dirs=config.proclib_dirs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("JCL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"JCL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    print(f"JCL: {len(jcl_files)} files")


def _build_call_copy_graph(
    config: CorpusConfig, cics_program_names: set[str], writer: GraphWriter, failures: list[str]
) -> None:
    """CALL/COPY graph for every COBOL program in the corpus, VM-free.

    Reproduces the (kind, id) node/edge identity of production's
    interpreter.project.cobol_connections.extract_cobol_connections output from
    the raw COPY/CALL scan (interpreter.project.cobol_imports), plus the single
    transitive DFHEIBLK edge production gets from CICS-source-prepassing each
    subprogram a CICS program statically CALLs (see below).
    """
    cbl_files = _matching_files(config.cobol_dir, config.cobol_globs)

    # per-program CALL/COPY edges + CALL adjacency + working-storage presence
    call_targets: dict[str, set[str]] = {}
    has_ws: dict[str, bool] = {}
    for path in cbl_files:
        prog = path.stem.upper()
        try:
            src = path.read_bytes()
            refs = extract_cobol_imports(src, path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("COBOL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"COBOL {path.name}: {exc}")
            continue
        writer.add_node(GraphNode(id=prog, kind=NodeKind.PROGRAM))
        tgts: set[str] = set()
        for ref in refs:
            if ref.kind == ImportKind.INCLUDE:
                tid = ref.module_path.upper()
                writer.add_node(GraphNode(id=tid, kind=NodeKind.COPYBOOK))
                writer.add_edge(GraphEdge(
                    source=prog, source_kind=NodeKind.PROGRAM,
                    target=tid, target_kind=NodeKind.COPYBOOK, kind=EdgeKind.COPY))
            elif ref.kind == ImportKind.REQUIRE:
                tid = ref.module_path.upper()
                writer.add_node(GraphNode(id=tid, kind=NodeKind.PROGRAM))
                writer.add_edge(GraphEdge(
                    source=prog, source_kind=NodeKind.PROGRAM,
                    target=tid, target_kind=NodeKind.PROGRAM, kind=EdgeKind.CALL))
                tgts.add(tid)
        call_targets[prog] = tgts
        txt = src.decode("utf-8", errors="replace")
        has_ws[prog] = any(
            (toks := line.strip().upper().split())[:2] == ["WORKING-STORAGE", "SECTION."]
            for line in txt.splitlines()
            if line.strip()
        )

    # Transitive DFHEIBLK: a CICS program that statically CALLs a corpus program
    # causes that callee's source to be CICS-source-prepassed (inject COPY
    # DFHEIBLK after WORKING-STORAGE SECTION). Walk the CALL closure from CICS
    # programs over corpus targets; each reached subprogram (non-CICS) that has a
    # WORKING-STORAGE SECTION gains a PROGRAM -> COPYBOOK(DFHEIBLK) COPY edge.
    corpus = set(call_targets)
    seen: set[str] = set()
    stack = list(cics_program_names)
    reached_subs: set[str] = set()
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        for t in call_targets.get(p, ()):
            if t in corpus:
                if t not in cics_program_names:
                    reached_subs.add(t)
                if t not in seen:
                    stack.append(t)
    for sub in sorted(reached_subs):
        if has_ws.get(sub):
            writer.add_node(GraphNode(id="DFHEIBLK", kind=NodeKind.COPYBOOK))
            writer.add_edge(GraphEdge(
                source=sub, source_kind=NodeKind.PROGRAM,
                target="DFHEIBLK", target_kind=NodeKind.COPYBOOK, kind=EdgeKind.COPY))

    print(f"CALL/COPY: {len(cbl_files)} programs")


def _build_cics_flow_graph(
    config: CorpusConfig, transid_to_program: dict[str, str], writer: GraphWriter, failures: list[str]
) -> None:
    cobol_sources: dict[str, bytes] = {}
    for prog_name in set(transid_to_program.values()):
        cbl_path = config.cobol_dir / f"{prog_name}.cbl"
        if cbl_path.is_file():
            cobol_sources[prog_name] = cbl_path.read_bytes()
        else:
            logger.warning("CICS program %s: no %s found", prog_name, cbl_path.name)
            failures.append(f"CICS program {prog_name}: no {cbl_path.name} found")

    csd_source = "\n".join(csd_file.read_text() for csd_file in config.csd_files)
    parser = _make_parser(config)
    try:
        extract_transaction_flow_graph(
            csd_source=csd_source,
            bms_mapsets={},
            cobol_sources=cobol_sources,
            parser=parser,
            sink=writer,
            failures=failures,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("CICS flow graph (whole CSD) failed: %s", exc, exc_info=True)
        failures.append(f"CICS flow graph (whole CSD): {exc}")
    print(
        f"CICS flow: {len(transid_to_program)} transactions, "
        f"{len(cobol_sources)} programs compiled"
    )


def _build_batch_file_graph(
    config: CorpusConfig, cics_program_names: set[str], writer: GraphWriter, failures: list[str]
) -> None:
    parser = _make_parser(config)
    cbl_files = [
        p for p in _matching_files(config.cobol_dir, config.cobol_globs)
        if p.stem.upper() not in cics_program_names
    ]
    store = AstStore(AstStrategy.DISK)
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
    print(f"FILE-CONTROL: {len(cbl_files)} batch programs")


def _read_ndjson(nodes_path: Path, edges_path: Path):
    nodes = []
    for line in nodes_path.read_text().splitlines():
        d = json.loads(line)
        nodes.append(GraphNode(
            id=d["id"], kind=NodeKind(d["kind"]),
            file_path=d.get("file_path"), attrs=d.get("attrs", {})))
    edges = []
    for line in edges_path.read_text().splitlines():
        d = json.loads(line)
        edges.append(GraphEdge(
            source=d["source"], source_kind=NodeKind(d["source_kind"]),
            target=d["target"], target_kind=NodeKind(d["target_kind"]),
            kind=EdgeKind(d["kind"]), attrs=d.get("attrs", {})))
    return nodes, edges


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, type=Path,
        help="Path to a corpus YAML config (see corpus_config.py / config/carddemo.yaml)",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    failures: list[str] = []

    args = _parse_args()
    config = load_corpus_config(args.config)

    transid_to_program = _load_transid_to_program(config)
    cics_program_names = set(transid_to_program.values())

    config.out_dir.mkdir(parents=True, exist_ok=True)
    nodes_jsonl = config.out_dir / "nodes.jsonl"
    edges_jsonl = config.out_dir / "edges.jsonl"
    with GraphWriter(nodes_jsonl, edges_jsonl) as writer:
        _build_jcl_graph(config, writer, failures)
        _build_call_copy_graph(config, cics_program_names, writer, failures)
        if config.csd_files:
            _build_cics_flow_graph(config, transid_to_program, writer, failures)
        else:
            print("CICS flow: skipped (no csd_files configured)")
        _build_batch_file_graph(config, cics_program_names, writer, failures)

    graph = merge_graph(*_read_ndjson(nodes_jsonl, edges_jsonl))
    print(
        f"\nMerged graph: {graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges"
    )
    print(f"Wrote {nodes_jsonl}\nWrote {edges_jsonl}")

    if failures:
        print(f"\n{len(failures)} failure(s) (skipped, did not abort the run):")
        for f in failures:
            print(f"  - {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify usage errors are clear**

Run: `uv run python build_graph.py`
Expected: argparse error, exit nonzero, message mentions `the following arguments are required: --config`.

Run: `uv run python build_graph.py --config does-not-exist.yaml`
Expected: `FileNotFoundError` (from `Path.read_text()` in `load_corpus_config`), not a silent fallback to CardDemo.

- [ ] **Step 4: Verify it reproduces today's graph exactly**

Run (from repo root, with `PROLEAP_BRIDGE_JAR`/`JCL_BRIDGE_JAR` set as `make build` does):
```bash
PROLEAP_BRIDGE_JAR=$(pwd)/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar \
JCL_BRIDGE_JAR=$(pwd)/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar \
uv run python build_graph.py --config config/carddemo.yaml
```
Expected: same output as today's `make build` — `Merged graph: 449 nodes, 803 edges`.

Then run: `uv run python compare.py`
Expected: `RESULT: EMPTY DIFF — out matches reference exactly.`

- [ ] **Step 5: Commit**

```bash
git add build_graph.py
git commit -m "cobble: rename build_port.py to build_graph.py, make config-driven"
```

(Note: `git mv` in Step 1 already stages the rename; Step 2's edits modify the staged `build_graph.py` — `git add build_graph.py` picks up both.)

---

### Task 4: Refactor `generate_sym.py` to use `--config`/`BmsConfig`

**Files:**
- Modify: `generate_sym.py` (full rewrite of contents, not renamed)

**Interfaces:**
- Consumes: `BmsConfig`, `load_bms_config` from Task 1's `corpus_config.py`.

- [ ] **Step 1: Replace the full contents of `generate_sym.py`**

Replace the entire contents of `generate_sym.py` with:

```python
#!/usr/bin/env python3
"""Stage-0: GENERATE the BMS symbolic copybooks from a corpus's .bms map
sources.

A port of cics.bms.generate.generate_symbolic_copybooks. For each
<bms_dir>/*.bms (bms_dir comes from the --config YAML's `bms:` section), runs

    hlasm_export <map>.bms --syslib <macros_dir>/ | python -m cobble.bms_copybook_gen

and writes <sym_dir>/<stem>.cpy. This produces the symbolic copybooks the CICS
COBOL programs `COPY`, from source -- nothing pre-generated is shipped.
hlasm_export is built from the che-che4z-lsp-for-hlasm submodule; the
DFHMSD/DFHMDI/DFHMDF prototype macros are the assembler SYSLIB.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # make `corpus_config` importable

from corpus_config import load_bms_config

_HLASM = _HERE / "vendor" / "che-che4z-lsp-for-hlasm" / "build" / "bin" / "hlasm_export"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, type=Path,
        help="Path to a corpus YAML config (see corpus_config.py / config/carddemo.yaml)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_bms_config(args.config)

    if not _HLASM.is_file():
        sys.exit(f"hlasm_export not built: {_HLASM} (run `make jars` / the HLASM build first)")
    syslib_args = ["--syslib", str(config.macros_dir)]
    config.sym_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(_HERE)}  # so `python -m cobble.bms_copybook_gen` resolves

    written = 0
    for bms in sorted(config.bms_dir.glob("*.bms")):
        export = subprocess.run(
            [str(_HLASM), str(bms), *syslib_args], capture_output=True, check=True
        )
        gen = subprocess.run(
            [sys.executable, "-m", "cobble.bms_copybook_gen"],
            input=export.stdout, capture_output=True, check=True, env=env,
        )
        if not gen.stdout.strip():
            raise RuntimeError(
                f"bms_copybook_gen produced an empty copybook for {bms.name} "
                f"(a BMS macro keyword is likely undeclared in {config.macros_dir})"
            )
        (config.sym_dir / (bms.stem + ".cpy")).write_bytes(gen.stdout)
        written += 1
        print(f"  BMS: {bms.stem}.cpy")
    print(f"generated {written} symbolic copybooks -> {config.sym_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verify usage errors are clear**

Run: `uv run python generate_sym.py`
Expected: argparse error, message mentions `the following arguments are required: --config`.

- [ ] **Step 3: Verify it reproduces today's copybooks exactly**

Run: `rm -rf sym && uv run python generate_sym.py --config config/carddemo.yaml`
Expected: same output as today's `make sym` — one `BMS: <stem>.cpy` line per generated copybook, same count as before.

- [ ] **Step 4: Commit**

```bash
git add generate_sym.py
git commit -m "cobble: make generate_sym.py config-driven via --config"
```

---

### Task 5: Update `Makefile` and `README.md`

**Files:**
- Modify: `Makefile:41-46` (the `sym` and `build` targets)
- Modify: `README.md` (multiple sections — see steps below)
- Modify: `render_graph.py:2` (docstring mentions `build_port.py`)

**Interfaces:**
- Consumes: `config/carddemo.yaml` (Task 2), `build_graph.py` (Task 3), `generate_sym.py --config` (Task 4).

- [ ] **Step 1: Update the Makefile**

In `Makefile`, change:
```makefile
## Stage-0: GENERATE the BMS symbolic copybooks from the CardDemo .bms sources
## (hlasm_export | bms_copybook_gen -> sym/*.cpy). Nothing pre-generated is shipped.
sym:
	uv run python generate_sym.py

## Run the four ported extractors over the corpus -> out/{nodes,edges}.jsonl
build:
	$(BRIDGE_ENV) uv run python build_port.py
```
to:
```makefile
## Stage-0: GENERATE the BMS symbolic copybooks from the CardDemo .bms sources
## (hlasm_export | bms_copybook_gen -> sym/*.cpy). Nothing pre-generated is shipped.
sym:
	uv run python generate_sym.py --config config/carddemo.yaml

## Run the four ported extractors over the corpus -> out/{nodes,edges}.jsonl
build:
	$(BRIDGE_ENV) uv run python build_graph.py --config config/carddemo.yaml
```

- [ ] **Step 2: Update `render_graph.py`'s docstring**

In `render_graph.py`, change the docstring line:
```python
"""render_graph.py — render out/nodes.jsonl + out/edges.jsonl (produced by
build_port.py) as one self-contained interactive HTML visualization at
```
to:
```python
"""render_graph.py — render out/nodes.jsonl + out/edges.jsonl (produced by
build_graph.py) as one self-contained interactive HTML visualization at
```

- [ ] **Step 3: Update README's "What's here" table row**

In `README.md`, change:
```markdown
| `build_port.py` / `compare.py` | Extract the graph → `out/`; identity-diff `out/` vs `reference/`. |
```
to:
```markdown
| `build_graph.py` / `compare.py` | Extract the graph → `out/`; identity-diff `out/` vs `reference/`. |
| `corpus_config.py` | `CorpusConfig`/`BmsConfig` dataclasses + YAML loading — `build_graph.py --config <path>` / `generate_sym.py --config <path>` read the corpus location/layout from here instead of a hardcoded CardDemo path. |
| `config/carddemo.yaml` | The tracked config `make build`/`make sym` use — captures CardDemo's layout in `corpus_config.py`'s schema. Copy this file as a starting point to point cobble at a different corpus. |
```

- [ ] **Step 4: Add a "Point this at your own codebase" README section**

In `README.md`, after the existing "### Build the graph from CardDemo" section (which ends with the `make build` re-run note), add a new subsection:

```markdown
### Point this at your own codebase

`build_graph.py`/`generate_sym.py` take a required `--config <path>` flag —
nothing about a specific corpus is hardcoded in Python. `config/carddemo.yaml`
is both the config `make build`/`make sym` use for CardDemo and a template for
your own corpus:

```yaml
corpus:
  cobol_dir: path/to/your/cobol
  cobol_globs: ["*.cbl", "*.CBL"]
  jcl_dir: path/to/your/jcl
  jcl_globs: ["*.jcl", "*.JCL"]
  proclib_dirs:
    - path/to/your/proclib
  csd_files:               # omit or leave empty ([]) if your corpus has no CICS
    - path/to/your/site.csd
  copybook_dirs:
    - path/to/your/copybooks
  out_dir: out

bms:
  bms_dir: path/to/your/bms
  macros_dir: bms-macros
  sym_dir: sym
```

Every path is relative to wherever you invoke the script from (not to the
config file's own location). Every field is required except `proclib_dirs`
and `csd_files`, which default to empty if omitted. Then run:

```bash
uv run python build_graph.py --config your-corpus.yaml
uv run python generate_sym.py --config your-corpus.yaml   # only if you have BMS maps
```

`compare.py`'s golden-file check stays CardDemo-specific — it's not meaningful
against a different corpus's output.
```

- [ ] **Step 5: Verify the Makefile still works**

Run: `make sym && make build`
Expected: same output as before this task (same copybook count, same 449/803 graph).

- [ ] **Step 6: Commit**

```bash
git add Makefile README.md render_graph.py
git commit -m "cobble: wire Makefile/README to config-driven build_graph.py"
```

---

### Task 6: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `make test`
Expected: all tests pass (75 total: 66 from Phase 1-2 + 9 from Task 1).

- [ ] **Step 2: Run the invariant check**

Run: `grep -rE '^\s*(import|from)\s+(interpreter|cics|jackal|knowledge_graph)\b' cobble`
Expected: no output (exit code 1).

- [ ] **Step 3: Run the full golden-file verification**

Run: `make verify`
Expected: `RESULT: EMPTY DIFF — out matches reference exactly.` (449 nodes / 803 edges, unchanged from before this plan).

- [ ] **Step 4: Confirm no leftover references to the old filename**

Run: `grep -rn "build_port" --include="*.py" --include="*.md" --include="Makefile" . | grep -v '^\./vendor\|^\./proleap-bridge\|^\./\.venv\|^\./docs/superpowers'`
Expected: no output (the historical spec/plan docs under `docs/superpowers/` are allowed to still mention `build_port.py` — they're a dated record, not live docs).

- [ ] **Step 5: Review the full diff**

Run: `git status --short` and `git log --oneline -6`
Expected: working tree clean, one commit per task above (5-6 commits total).

- [ ] **Step 6: Push**

Only after the user confirms — this plan does not push automatically. Ask: "All tasks complete and verified. Push to origin/main?"
