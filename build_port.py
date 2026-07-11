"""build_port.py — VM-free standalone port of the CardDemo knowledge-graph
extraction pipeline.

Runs the same four extractors as knowledge_graph/build_carddemo_graph.py, but
entirely through the ``cobble.*`` package tree (a byte-for-byte + import-rewrite
port of the production extractors, with ONE seam: VM-free CICS verb sourcing in
cobble/cics/verb_source_asg.py). No VM, no compile/lower pipeline.

Writes experiments/standalone-graph/out/{nodes,edges}.jsonl and prints per-
extractor + merged counts.

Env:
    PROLEAP_BRIDGE_JAR=$(pwd)/vendor/red-dragon/proleap-bridge/target/proleap-bridge-0.1.0-shaded.jar
    JCL_BRIDGE_JAR=$(pwd)/jackal/jcl-bridge/target/jcl-bridge-0.1.0-shaded.jar
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # make `port` importable

from cobble.interpreter.cobol.ast_store import AstStore, AstStrategy
from cobble.interpreter.cobol.cobol_parser import ProLeapCobolParser
from cobble.interpreter.cobol.subprocess_runner import RealSubprocessRunner
from cobble.interpreter.project.cobol_imports import extract_cobol_imports
from cobble.interpreter.project.import_types import ImportKind
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)

from cobble.cics.csd_parse import parse_csd
from cobble.cics.flow_map import extract_transaction_flow_graph

from cobble.jackal.cobol_file_graph import extract_cobol_file_graph
from cobble.jackal.jcl_graph import extract_jcl_graph

from cobble.knowledge_graph.graph_writer import GraphWriter
from cobble.knowledge_graph.merge import merge_graph

logger = logging.getLogger(__name__)

_REPO_ROOT = _HERE  # cobble repo root (build_port.py lives here)
_CARDDEMO_HOME = _REPO_ROOT / "vendor" / "carddemo" / "app"
_CICS_COPYBOOKS = _REPO_ROOT / "cics-copybooks"
_SYM_DIR = _REPO_ROOT / "sym"
_OUT_DIR = _HERE / "out"

_COPYBOOK_DIRS = [
    _SYM_DIR,
    _CARDDEMO_HOME / "cpy",
    _CARDDEMO_HOME / "cpy-bms",
    _CICS_COPYBOOKS,
]


def _bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


def _make_parser() -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(), _bridge_jar(), copybook_dirs=_COPYBOOK_DIRS
    )


def _build_jcl_graph(writer: GraphWriter, failures: list[str]) -> None:
    jcl_dir = _CARDDEMO_HOME / "jcl"
    proclib_dirs = [_CARDDEMO_HOME / "proc"]
    jcl_files = sorted(jcl_dir.glob("*.jcl")) + sorted(jcl_dir.glob("*.JCL"))
    for path in jcl_files:
        try:
            nodes, edges = extract_jcl_graph(
                path.read_text(), proclib_dirs=proclib_dirs
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("JCL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"JCL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    print(f"JCL: {len(jcl_files)} files")


def _build_call_copy_graph(
    cics_program_names: set[str], writer: GraphWriter, failures: list[str]
) -> None:
    """CALL/COPY graph for every CardDemo COBOL program, VM-free.

    Reproduces the (kind, id) node/edge identity of production's
    interpreter.project.cobol_connections.extract_cobol_connections output from
    the raw COPY/CALL scan (interpreter.project.cobol_imports), plus the single
    transitive DFHEIBLK edge production gets from CICS-source-prepassing each
    subprogram a CICS program statically CALLs (see below).
    """
    cbl_dir = _CARDDEMO_HOME / "cbl"
    cbl_files = sorted(cbl_dir.glob("*.cbl"))

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
                writer.add_edge(
                    GraphEdge(
                        source=prog,
                        source_kind=NodeKind.PROGRAM,
                        target=tid,
                        target_kind=NodeKind.COPYBOOK,
                        kind=EdgeKind.COPY,
                    )
                )
            elif ref.kind == ImportKind.REQUIRE:
                tid = ref.module_path.upper()
                writer.add_node(GraphNode(id=tid, kind=NodeKind.PROGRAM))
                writer.add_edge(
                    GraphEdge(
                        source=prog,
                        source_kind=NodeKind.PROGRAM,
                        target=tid,
                        target_kind=NodeKind.PROGRAM,
                        kind=EdgeKind.CALL,
                    )
                )
                tgts.add(tid)
        call_targets[prog] = tgts
        txt = src.decode("utf-8", errors="replace")
        has_ws[prog] = any(
            (toks := line.strip().upper().split())[:2]
            == ["WORKING-STORAGE", "SECTION."]
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
            writer.add_edge(
                GraphEdge(
                    source=sub,
                    source_kind=NodeKind.PROGRAM,
                    target="DFHEIBLK",
                    target_kind=NodeKind.COPYBOOK,
                    kind=EdgeKind.COPY,
                )
            )

    print(f"CALL/COPY: {len(cbl_files)} programs")


def _build_cics_flow_graph(
    transid_to_program: dict[str, str], writer: GraphWriter, failures: list[str]
) -> None:
    csd_path = _CARDDEMO_HOME / "csd" / "CARDDEMO.CSD"
    cbl_dir = _CARDDEMO_HOME / "cbl"
    cobol_sources: dict[str, bytes] = {}
    for prog_name in set(transid_to_program.values()):
        cbl_path = cbl_dir / f"{prog_name}.cbl"
        if cbl_path.is_file():
            cobol_sources[prog_name] = cbl_path.read_bytes()
        else:
            logger.warning("CICS program %s: no %s found", prog_name, cbl_path.name)
            failures.append(f"CICS program {prog_name}: no {cbl_path.name} found")

    parser = _make_parser()
    try:
        extract_transaction_flow_graph(
            csd_source=csd_path.read_text(),
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
    cics_program_names: set[str], writer: GraphWriter, failures: list[str]
) -> None:
    cbl_dir = _CARDDEMO_HOME / "cbl"
    parser = _make_parser()
    cbl_files = [
        p
        for p in sorted(cbl_dir.glob("*.cbl"))
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
        nodes.append(
            GraphNode(
                id=d["id"],
                kind=NodeKind(d["kind"]),
                file_path=d.get("file_path"),
                attrs=d.get("attrs", {}),
            )
        )
    edges = []
    for line in edges_path.read_text().splitlines():
        d = json.loads(line)
        edges.append(
            GraphEdge(
                source=d["source"],
                source_kind=NodeKind(d["source_kind"]),
                target=d["target"],
                target_kind=NodeKind(d["target_kind"]),
                kind=EdgeKind(d["kind"]),
                attrs=d.get("attrs", {}),
            )
        )
    return nodes, edges


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    failures: list[str] = []

    transid_to_program = parse_csd(_CARDDEMO_HOME / "csd" / "CARDDEMO.CSD")
    cics_program_names = set(transid_to_program.values())

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    nodes_jsonl = _OUT_DIR / "nodes.jsonl"
    edges_jsonl = _OUT_DIR / "edges.jsonl"
    with GraphWriter(nodes_jsonl, edges_jsonl) as writer:
        _build_jcl_graph(writer, failures)
        _build_call_copy_graph(cics_program_names, writer, failures)
        _build_cics_flow_graph(transid_to_program, writer, failures)
        _build_batch_file_graph(cics_program_names, writer, failures)

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
