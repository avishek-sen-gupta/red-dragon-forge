"""build_graph.py — config-driven knowledge-graph extraction over a
COBOL/CICS/JCL corpus.

Runs the same four extractors as production (JCL, CALL/COPY, CICS flow, batch
FILE-CONTROL) entirely through the ``cobble.*`` package tree (a byte-for-byte +
import-rewrite port of the production extractors, with ONE seam: VM-free CICS
verb sourcing in cobble/cics/verb_source_asg.py). No VM, no compile/lower
pipeline.

Corpus location and layout come from a YAML config file (see
cobble/corpus_config.py) passed via --config -- nothing about the corpus is
hardcoded here. Writes <out_dir>/{nodes,edges}.jsonl and prints per-extractor
+ merged counts.

Invoke as: uv run python -m cobble.build_graph --config <path>

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

from tqdm import tqdm

from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.corpus_index import CorpusIndex
from cobble.file_location import to_json_value
from cobble.matching_files import matching_files

from cobble.interpreter.cobol.ast_store import AstStore, AstStrategy
from cobble.interpreter.cobol.cobol_parser import ProLeapCobolParser
from cobble.interpreter.cobol.source_text import decode_source
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


def _bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


def _make_parser(config: CorpusConfig) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        _bridge_jar(),
        copybook_dirs=list(config.copybook_dirs),
        copybook_extensions=list(config.copybook_extensions),
    )


def _load_transid_to_program(config: CorpusConfig) -> dict[str, str]:
    merged: dict[str, str] = {}
    for csd_file in config.csd_files:
        merged.update(parse_csd(csd_file))
    return merged


def _build_jcl_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    writer: GraphWriter,
    failures: list[str],
) -> None:
    jcl_files = matching_files(config.jcl_dir, config.jcl_globs)
    for path in tqdm(jcl_files, desc="JCL", unit="file"):
        try:
            nodes, edges = extract_jcl_graph(
                decode_source(path.read_bytes()),
                corpus_index,
                proclib_dirs=config.proclib_dirs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("JCL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"JCL {path.name}: {exc}")
            continue
        writer.add_all(nodes, edges)
    print(f"JCL: {len(jcl_files)} files")


def _build_call_copy_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    cics_program_names: set[str],
    writer: GraphWriter,
    failures: list[str],
) -> None:
    """CALL/COPY graph for every COBOL program in the corpus, VM-free.

    Reproduces the (kind, id) node/edge identity of production's
    interpreter.project.cobol_connections.extract_cobol_connections output from
    the raw COPY/CALL scan (interpreter.project.cobol_imports), plus the single
    transitive DFHEIBLK edge production gets from CICS-source-prepassing each
    subprogram a CICS program statically CALLs (see below).
    """
    cbl_files = matching_files(config.cobol_dir, config.cobol_globs)

    # per-program CALL/COPY edges + CALL adjacency + working-storage presence
    call_targets: dict[str, set[str]] = {}
    has_ws: dict[str, bool] = {}
    for path in tqdm(cbl_files, desc="CALL/COPY", unit="program"):
        prog = path.stem.upper()
        try:
            src = path.read_bytes()
            refs = extract_cobol_imports(src, path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("COBOL %s failed: %s", path.name, exc, exc_info=True)
            failures.append(f"COBOL {path.name}: {exc}")
            continue
        writer.add_node(
            GraphNode(
                id=prog,
                kind=NodeKind.PROGRAM,
                file_path=to_json_value(
                    corpus_index.resolve_file_path(NodeKind.PROGRAM, prog)
                ),
            )
        )
        tgts: set[str] = set()
        for ref in refs:
            if ref.kind == ImportKind.INCLUDE:
                tid = ref.module_path.upper()
                writer.add_node(
                    GraphNode(
                        id=tid,
                        kind=NodeKind.COPYBOOK,
                        file_path=to_json_value(
                            corpus_index.resolve_file_path(NodeKind.COPYBOOK, tid)
                        ),
                    )
                )
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
                writer.add_node(
                    GraphNode(
                        id=tid,
                        kind=NodeKind.PROGRAM,
                        file_path=to_json_value(
                            corpus_index.resolve_file_path(NodeKind.PROGRAM, tid)
                        ),
                    )
                )
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
            writer.add_node(
                GraphNode(
                    id="DFHEIBLK",
                    kind=NodeKind.COPYBOOK,
                    file_path=to_json_value(
                        corpus_index.resolve_file_path(NodeKind.COPYBOOK, "DFHEIBLK")
                    ),
                )
            )
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
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    transid_to_program: dict[str, str],
    writer: GraphWriter,
    failures: list[str],
) -> None:
    cobol_sources: dict[str, bytes] = {}
    # Build a map of uppercase file stems to paths using configured cobol_globs
    cobol_files = matching_files(config.cobol_dir, config.cobol_globs)
    file_stem_map = {path.stem.upper(): path for path in cobol_files}

    for prog_name in tqdm(
        set(transid_to_program.values()), desc="CICS flow", unit="program"
    ):
        if prog_name in file_stem_map:
            cobol_sources[prog_name] = file_stem_map[prog_name].read_bytes()
        else:
            logger.warning(
                "CICS program %s: not found in cobol_globs matches", prog_name
            )
            failures.append(
                f"CICS program {prog_name}: not found in cobol_globs matches"
            )

    csd_source = "\n".join(
        decode_source(csd_file.read_bytes()) for csd_file in config.csd_files
    )
    parser = _make_parser(config)
    try:
        extract_transaction_flow_graph(
            csd_source=csd_source,
            bms_mapsets={},
            cobol_sources=cobol_sources,
            parser=parser,
            sink=writer,
            corpus_index=corpus_index,
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
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    cics_program_names: set[str],
    writer: GraphWriter,
    failures: list[str],
) -> None:
    parser = _make_parser(config)
    cbl_files = [
        p
        for p in matching_files(config.cobol_dir, config.cobol_globs)
        if p.stem.upper() not in cics_program_names
    ]
    store = AstStore(AstStrategy.DISK)
    store.parse_all({p: p.read_bytes() for p in cbl_files}, parser)
    for path in tqdm(cbl_files, desc="FILE-CONTROL", unit="program"):
        try:
            nodes, edges = extract_cobol_file_graph(store.get(path), corpus_index)
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus YAML config (see cobble/corpus_config.py / config/carddemo.yaml)",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    failures: list[str] = []

    args = _parse_args()
    config = load_corpus_config(args.config)
    corpus_index = CorpusIndex(config)
    # Members the index skipped. Everything in them is absent from the index, so
    # they belong in the same report as the graph-building failures below.
    failures.extend(corpus_index.failures)

    transid_to_program = _load_transid_to_program(config)
    cics_program_names = set(transid_to_program.values())

    config.out_dir.mkdir(parents=True, exist_ok=True)
    nodes_jsonl = config.out_dir / "nodes.jsonl"
    edges_jsonl = config.out_dir / "edges.jsonl"
    with GraphWriter(nodes_jsonl, edges_jsonl, corpus_index) as writer:
        _build_jcl_graph(config, corpus_index, writer, failures)
        _build_call_copy_graph(
            config, corpus_index, cics_program_names, writer, failures
        )
        if config.csd_files:
            _build_cics_flow_graph(
                config, corpus_index, transid_to_program, writer, failures
            )
        else:
            print("CICS flow: skipped (no csd_files configured)")
        _build_batch_file_graph(
            config, corpus_index, cics_program_names, writer, failures
        )

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
