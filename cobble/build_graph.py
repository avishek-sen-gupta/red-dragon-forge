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

Every extractor RETURNS what it skipped rather than appending to a shared list,
so a failure is part of a stage's result instead of an effect it had on its
caller's state, and the run's report is one fold over those results. The
GraphWriter it feeds is the one real accumulator here, and deliberately so: its
job is to stream to disk.

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
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from types import MappingProxyType

from tqdm import tqdm

from cobble.cics.csd_parse import CsdParseError, parse_csd
from cobble.cics.flow_map import extract_transaction_flow_graph
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.corpus_index import CorpusIndex
from cobble.corpus_index_builder import build_corpus_index
from cobble.file_location import to_json_value
from cobble.interpreter.cobol.ast_store import AstStore, AstStrategy
from cobble.interpreter.cobol.cobol_parser import ProLeapCobolParser
from cobble.interpreter.cobol.source_text import decode_source
from cobble.interpreter.cobol.subprocess_runner import RealSubprocessRunner
from cobble.interpreter.project.cobol_imports import extract_cobol_imports
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.interpreter.project.import_types import ImportKind, ImportRef
from cobble.jackal.cobol_file_graph import extract_cobol_file_graph
from cobble.jackal.jcl.jcl_store import JclStore, temp_jcl_store
from cobble.jackal.jcl.parser import bridge_parser
from cobble.jackal.jcl_graph import jcl_graph_from_job
from cobble.knowledge_graph.graph_writer import GraphWriter
from cobble.knowledge_graph.merge import merge_graph
from cobble.matching_files import matching_files

logger = logging.getLogger(__name__)

RULE = "=" * 78

_NO_TRANSACTIONS: Mapping[str, str] = MappingProxyType({})

# The two ref kinds the CALL/COPY scan produces an edge for, and what that edge
# is. A ref of any other kind is not an import of a corpus artefact.
_REF_GRAPH_SHAPE: Mapping[ImportKind, tuple[NodeKind, EdgeKind]] = MappingProxyType(
    {
        ImportKind.INCLUDE: (NodeKind.COPYBOOK, EdgeKind.COPY),
        ImportKind.REQUIRE: (NodeKind.PROGRAM, EdgeKind.CALL),
    }
)


def _bridge_jar() -> str:
    return os.environ["PROLEAP_BRIDGE_JAR"]


def _make_parser(config: CorpusConfig) -> ProLeapCobolParser:
    return ProLeapCobolParser(
        RealSubprocessRunner(),
        _bridge_jar(),
        copybook_dirs=list(config.copybook_dirs),
        copybook_extensions=list(config.copybook_extensions),
    )


def _out_paths(config: CorpusConfig) -> tuple[Path, Path]:
    return config.out_dir / "nodes.jsonl", config.out_dir / "edges.jsonl"


# ── CSD: transaction -> program ──────────────────────────────────


@dataclass(frozen=True)
class _CsdRead:
    """The transaction map one or more CSD files yielded, and what would not read."""

    transid_to_program: Mapping[str, str] = _NO_TRANSACTIONS
    failures: tuple[str, ...] = ()


def _read_one_csd(csd_file: Path) -> _CsdRead:
    # Guarded per file, like every other corpus read in this module. Unguarded,
    # one malformed CSD aborted the run here -- before the writer even opened --
    # while CorpusIndex went on to guard the very same file and report it.
    try:
        return _CsdRead(transid_to_program=parse_csd(csd_file))
    except (CsdParseError, OSError) as exc:
        logger.warning("CSD %s failed to parse: %s", csd_file.name, exc)
        return _CsdRead(failures=(f"CSD {csd_file.name}: {exc}",))


def _load_transid_to_program(config: CorpusConfig) -> _CsdRead:
    """Merge every configured CSD's transaction map, later files winning."""
    reads = tuple(map(_read_one_csd, config.csd_files))
    return _CsdRead(
        transid_to_program=MappingProxyType(
            dict(chain.from_iterable(read.transid_to_program.items() for read in reads))
        ),
        failures=tuple(chain.from_iterable(read.failures for read in reads)),
    )


# ── the failure report ───────────────────────────────────────────


def _category(failure: str) -> str:
    """Everything before the member name: given "index JCL X.jcl: ...",
    "JCL X.jcl: ..." or "COBOL X.cbl: ...", the category is the leading words."""
    return failure.split(":", 1)[0].rsplit(" ", 1)[0] or failure


def _tally_lines(failures: Sequence[str]) -> tuple[str, ...]:
    """Commonest category first, ties by name. Sorted on negated counts rather
    than with a sort-order callback, which talisman reads as a secret pattern."""
    tally = Counter(map(_category, failures))
    return tuple(
        f"  {-negated_count:5}  {category}"
        for negated_count, category in sorted(
            (-count, category) for category, count in tally.items()
        )
    )


def _failure_report_lines(failures: Sequence[str]) -> tuple[str, ...]:
    return (
        "",
        RULE,
        f"!!  {len(failures)} FAILURE(S) -- THIS GRAPH IS INCOMPLETE",
        "!!  The members below were SKIPPED. Everything in them is absent from",
        "!!  nodes.jsonl/edges.jsonl and every reference to it is UNRESOLVED.",
        RULE,
        *_tally_lines(failures),
        RULE,
        *(f"  - {failure}" for failure in failures),
        RULE,
    )


def _report_failures(failures: Sequence[str]) -> None:
    """Say loudly that the graph just written is missing things.

    A skipped member is not a warning about the run -- it is a statement about
    the output: those jobs, steps, programs and datasets are absent from
    nodes.jsonl, and every reference to them resolves UNRESOLVED. The counts
    logged above this look like a finished graph either way, so this has to be
    hard to scroll past and it has to name the shape of what went wrong, not
    just list lines.

    ERROR, not INFO: it describes the artifact rather than the progress, so a
    caller that raises the level to silence the per-stage counts must still get
    this. One record, so nothing interleaves through the middle of the report.
    """
    if not failures:
        return
    logger.error("%s", "\n".join(_failure_report_lines(failures)))


# ── extractor 1: JCL ─────────────────────────────────────────────


def _jcl_file_failures(
    path: Path,
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    writer: GraphWriter,
    store: JclStore,
) -> tuple[str, ...]:
    try:
        nodes, edges = jcl_graph_from_job(
            store.get(path),
            corpus_index,
            proclib_dirs=config.proclib_dirs,
        )
    except Exception as exc:
        logger.warning("JCL %s failed: %s", path.name, exc, exc_info=True)
        return (f"JCL {path.name}: {exc}",)
    writer.add_all(nodes, edges)
    return ()


def _build_jcl_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    writer: GraphWriter,
    store: JclStore,
) -> tuple[str, ...]:
    jcl_files = matching_files(config.jcl_dir, config.jcl_globs)
    failures = tuple(
        chain.from_iterable(
            _jcl_file_failures(path, config, corpus_index, writer, store)
            for path in tqdm(jcl_files, desc="JCL", unit="file")
        )
    )
    logger.info("JCL: %d files", len(jcl_files))
    return failures


# ── extractor 2: CALL/COPY ───────────────────────────────────────


def _program_node(program: str, corpus_index: CorpusIndex) -> GraphNode:
    return GraphNode(
        id=program,
        kind=NodeKind.PROGRAM,
        file_path=to_json_value(
            corpus_index.resolve_file_path(NodeKind.PROGRAM, program)
        ),
    )


def _ref_node(target: str, kind: NodeKind, corpus_index: CorpusIndex) -> GraphNode:
    return GraphNode(
        id=target,
        kind=kind,
        file_path=to_json_value(corpus_index.resolve_file_path(kind, target)),
    )


def _ref_edge(
    program: str, target: str, target_kind: NodeKind, kind: EdgeKind
) -> GraphEdge:
    return GraphEdge(
        source=program,
        source_kind=NodeKind.PROGRAM,
        target=target,
        target_kind=target_kind,
        kind=kind,
    )


def _graph_refs(refs: Sequence[ImportRef]) -> tuple[tuple[str, ImportKind], ...]:
    """The refs that become an edge, as (uppercased target, ref kind)."""
    return tuple(
        (ref.module_path.upper(), ref.kind)
        for ref in refs
        if ref.kind in _REF_GRAPH_SHAPE
    )


def _ref_graph(
    program: str, refs: Sequence[ImportRef], corpus_index: CorpusIndex
) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
    """One program's COPY/CALL targets as nodes plus the edges reaching them."""
    graphed = _graph_refs(refs)
    return (
        tuple(
            _ref_node(target, _REF_GRAPH_SHAPE[kind][0], corpus_index)
            for target, kind in graphed
        ),
        tuple(
            _ref_edge(program, target, *_REF_GRAPH_SHAPE[kind])
            for target, kind in graphed
        ),
    )


def _has_working_storage(source: bytes) -> bool:
    return any(
        line.strip().upper().split()[:2] == ["WORKING-STORAGE", "SECTION."]
        for line in source.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    )


@dataclass(frozen=True)
class _Scanned:
    """One program's contribution to the CALL closure, or why it made none."""

    program: str
    call_targets: frozenset[str] = frozenset()
    has_working_storage: bool = False
    failures: tuple[str, ...] = ()


def _scan_program(
    path: Path, corpus_index: CorpusIndex, writer: GraphWriter
) -> _Scanned:
    program = path.stem.upper()
    try:
        source = path.read_bytes()
        refs = extract_cobol_imports(source, path)
    except Exception as exc:
        logger.warning("COBOL %s failed: %s", path.name, exc, exc_info=True)
        return _Scanned(program=program, failures=(f"COBOL {path.name}: {exc}",))
    nodes, edges = _ref_graph(program, refs, corpus_index)
    writer.add_all((_program_node(program, corpus_index), *nodes), edges)
    return _Scanned(
        program=program,
        call_targets=frozenset(
            target for target, kind in _graph_refs(refs) if kind == ImportKind.REQUIRE
        ),
        has_working_storage=_has_working_storage(source),
    )


def _call_closure(
    frontier: frozenset[str], seen: frozenset[str], calls: Mapping[str, frozenset[str]]
) -> frozenset[str]:
    """Every program reachable from ``frontier`` over CALL edges within the corpus.

    Breadth at a time, and only through programs the corpus actually has: a CALL
    to something absent is an edge in the graph but not a place the closure can
    continue from.
    """
    if not frontier:
        return seen
    reached = frozenset(
        chain.from_iterable(calls.get(program, frozenset()) for program in frontier)
    ).intersection(calls)
    return _call_closure(reached - seen - frontier, seen | frontier, calls)


def _dfheiblk_graph(
    subprograms: Sequence[str], corpus_index: CorpusIndex
) -> tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]:
    """The transitive DFHEIBLK copies, one node and one edge per subprogram.

    A CICS program that statically CALLs a corpus program causes that callee's
    source to be CICS-source-prepassed (inject COPY DFHEIBLK after
    WORKING-STORAGE SECTION), so each reached non-CICS program that HAS a
    WORKING-STORAGE SECTION gains a PROGRAM -> COPYBOOK(DFHEIBLK) COPY edge.
    """
    return (
        tuple(
            _ref_node("DFHEIBLK", NodeKind.COPYBOOK, corpus_index) for _ in subprograms
        ),
        tuple(
            _ref_edge(sub, "DFHEIBLK", NodeKind.COPYBOOK, EdgeKind.COPY)
            for sub in subprograms
        ),
    )


def _prepassed_subprograms(
    scanned: Sequence[_Scanned], cics_program_names: frozenset[str]
) -> tuple[str, ...]:
    """The non-CICS corpus programs the CICS CALL closure reaches that have a
    WORKING-STORAGE SECTION for the injected COPY to follow.

    A program that failed to scan is not in the corpus adjacency at all, so a
    CALL into it is an edge the closure cannot continue through -- same as the
    ``continue`` it replaced.
    """
    calls = MappingProxyType(
        {item.program: item.call_targets for item in scanned if not item.failures}
    )
    with_working_storage = frozenset(
        item.program for item in scanned if item.has_working_storage
    )
    reached = _call_closure(cics_program_names, frozenset(), calls)
    return tuple(sorted((reached - cics_program_names) & with_working_storage))


def _build_call_copy_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    cics_program_names: frozenset[str],
    writer: GraphWriter,
) -> tuple[str, ...]:
    """CALL/COPY graph for every COBOL program in the corpus, VM-free.

    Reproduces the (kind, id) node/edge identity of production's
    interpreter.project.cobol_connections.extract_cobol_connections output from
    the raw COPY/CALL scan (interpreter.project.cobol_imports), plus the single
    transitive DFHEIBLK edge production gets from CICS-source-prepassing each
    subprogram a CICS program statically CALLs.
    """
    cbl_files = matching_files(config.cobol_dir, config.cobol_globs)
    scanned = tuple(
        _scan_program(path, corpus_index, writer)
        for path in tqdm(cbl_files, desc="CALL/COPY", unit="program")
    )
    writer.add_all(
        *_dfheiblk_graph(
            _prepassed_subprograms(scanned, cics_program_names), corpus_index
        )
    )
    logger.info("CALL/COPY: %d programs", len(cbl_files))
    return tuple(chain.from_iterable(item.failures for item in scanned))


# ── extractor 3: CICS flow ───────────────────────────────────────


@dataclass(frozen=True)
class _CicsSources:
    """The CICS programs whose source was found, and the ones that were not."""

    sources: tuple[tuple[str, bytes], ...] = ()
    failures: tuple[str, ...] = ()


def _cics_source(program: str, stems: Mapping[str, Path]) -> _CicsSources:
    if program not in stems:
        message = f"CICS program {program}: not found in cobol_globs matches"
        logger.warning("CICS program %s: not found in cobol_globs matches", program)
        return _CicsSources(failures=(message,))
    return _CicsSources(sources=((program, stems[program].read_bytes()),))


def _cics_sources(
    program_names: frozenset[str], stems: Mapping[str, Path]
) -> _CicsSources:
    found = tuple(
        _cics_source(program, stems)
        for program in tqdm(program_names, desc="CICS flow", unit="program")
    )
    return _CicsSources(
        sources=tuple(chain.from_iterable(item.sources for item in found)),
        failures=tuple(chain.from_iterable(item.failures for item in found)),
    )


def _build_cics_flow_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    transid_to_program: Mapping[str, str],
    writer: GraphWriter,
) -> tuple[str, ...]:
    stems = {
        path.stem.upper(): path
        for path in matching_files(config.cobol_dir, config.cobol_globs)
    }
    found = _cics_sources(frozenset(transid_to_program.values()), stems)
    stage_failures = _run_flow_extractor(config, corpus_index, found, writer)
    logger.info(
        "CICS flow: %d transactions, %d programs compiled",
        len(transid_to_program),
        len(found.sources),
    )
    return found.failures + stage_failures


def _run_flow_extractor(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    found: _CicsSources,
    writer: GraphWriter,
) -> tuple[str, ...]:
    """Run the flow extractor over the whole CSD and return what it reported.

    The sink list is this function's own, not the run's: extract_transaction_flow_graph
    reports into a list it is handed (cobble/cics/flow_map.py owns that contract),
    so the list stays local and leaves here as a tuple. The whole CSD is one
    call, so a failure escaping it is the stage's, not one member's.
    """
    csd_source = "\n".join(
        decode_source(csd_file.read_bytes()) for csd_file in config.csd_files
    )
    sink: list[str] = []
    try:
        extract_transaction_flow_graph(
            csd_source=csd_source,
            bms_mapsets={},
            cobol_sources=dict(found.sources),
            parser=_make_parser(config),
            sink=writer,
            corpus_index=corpus_index,
            failures=sink,
        )
    except Exception as exc:
        logger.warning("CICS flow graph (whole CSD) failed: %s", exc, exc_info=True)
        return (*sink, f"CICS flow graph (whole CSD): {exc}")
    return tuple(sink)


def _cics_flow_or_skip(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    transid_to_program: Mapping[str, str],
    writer: GraphWriter,
) -> tuple[str, ...]:
    if not config.csd_files:
        logger.info("CICS flow: skipped (no csd_files configured)")
        return ()
    return _build_cics_flow_graph(config, corpus_index, transid_to_program, writer)


# ── extractor 4: batch FILE-CONTROL ──────────────────────────────


def _file_control_failures(
    path: Path, store: AstStore, corpus_index: CorpusIndex, writer: GraphWriter
) -> tuple[str, ...]:
    try:
        nodes, edges = extract_cobol_file_graph(store.get(path), corpus_index)
    except Exception as exc:
        logger.warning("FILE-CONTROL %s failed: %s", path.name, exc, exc_info=True)
        return (f"FILE-CONTROL {path.name}: {exc}",)
    writer.add_all(nodes, edges)
    return ()


def _build_batch_file_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    cics_program_names: frozenset[str],
    writer: GraphWriter,
) -> tuple[str, ...]:
    cbl_files = tuple(
        path
        for path in matching_files(config.cobol_dir, config.cobol_globs)
        if path.stem.upper() not in cics_program_names
    )
    store = AstStore(AstStrategy.DISK)
    store.parse_all(
        {path: path.read_bytes() for path in cbl_files}, _make_parser(config)
    )
    failures = tuple(
        chain.from_iterable(
            _file_control_failures(path, store, corpus_index, writer)
            for path in tqdm(cbl_files, desc="FILE-CONTROL", unit="program")
        )
    )
    store.close()
    logger.info("FILE-CONTROL: %d batch programs", len(cbl_files))
    return failures


# ── the run ──────────────────────────────────────────────────────


def _text(value: object) -> str:
    """A field the writer wrote as a string, read back as one.

    ``json.loads`` yields ``object``; every id/name field here was written from a
    ``str``, so this narrows rather than converts. A non-string would be a
    GraphWriter bug and shows up as its own repr in the merged graph.
    """
    return value if isinstance(value, str) else str(value)


def _attrs(row: Mapping[str, object]) -> dict[str, object]:
    value = row.get("attrs")
    return dict(value) if isinstance(value, Mapping) else {}


def _node_from_json(row: Mapping[str, object]) -> GraphNode:
    file_path = row.get("file_path")
    return GraphNode(
        id=_text(row["id"]),
        kind=NodeKind(row["kind"]),
        # Absent, JSON null and a non-string all mean "no file" here, exactly as
        # the dict.get this replaced handed them to GraphNode.
        file_path=file_path if isinstance(file_path, str) else None,
        attrs=_attrs(row),
    )


def _edge_from_json(row: Mapping[str, object]) -> GraphEdge:
    return GraphEdge(
        source=_text(row["source"]),
        source_kind=NodeKind(row["source_kind"]),
        target=_text(row["target"]),
        target_kind=NodeKind(row["target_kind"]),
        kind=EdgeKind(row["kind"]),
        attrs=_attrs(row),
    )


def _rows(path: Path) -> tuple[Mapping[str, object], ...]:
    return tuple(json.loads(line) for line in path.read_text().splitlines())


def _read_ndjson(
    nodes_path: Path, edges_path: Path
) -> tuple[list[GraphNode], list[GraphEdge]]:
    return (
        [_node_from_json(row) for row in _rows(nodes_path)],
        [_edge_from_json(row) for row in _rows(edges_path)],
    )


def _extract_all(
    config: CorpusConfig, corpus_index: CorpusIndex, csd: _CsdRead, store: JclStore
) -> tuple[str, ...]:
    """Run the four extractors into one writer, returning everything they skipped."""
    cics_program_names = frozenset(csd.transid_to_program.values())
    config.out_dir.mkdir(parents=True, exist_ok=True)
    nodes_jsonl, edges_jsonl = _out_paths(config)
    with GraphWriter(nodes_jsonl, edges_jsonl, corpus_index) as writer:
        return (
            _build_jcl_graph(config, corpus_index, writer, store)
            + _build_call_copy_graph(config, corpus_index, cics_program_names, writer)
            + _cics_flow_or_skip(config, corpus_index, csd.transid_to_program, writer)
            + _build_batch_file_graph(config, corpus_index, cics_program_names, writer)
        )


def _report_merged(config: CorpusConfig) -> None:
    nodes_jsonl, edges_jsonl = _out_paths(config)
    graph = merge_graph(*_read_ndjson(nodes_jsonl, edges_jsonl))
    logger.info(
        "\nMerged graph: %d nodes, %d edges\nWrote %s\nWrote %s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        nodes_jsonl,
        edges_jsonl,
    )


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
    # Everything this run says is a log record on stderr, which is where the tqdm
    # bars already are -- so the per-stage counts and the bar each followed
    # interleave in the order they happened, with no stdout buffering to work
    # around. stdout stays empty.
    configure_cli_logging()
    config = load_corpus_config(_parse_args().config)
    # Both JCL passes read every member, so the bridge runs once per member here
    # rather than once per pass. The store keeps only the bridge's JSON, on disk,
    # and deserializes one Job at a time -- a resident Job per member does not
    # scale to a corpus. Its cache dies with the store, so no run can be served
    # output from a different grammar.
    with temp_jcl_store() as store:
        store.parse_all(
            matching_files(config.jcl_dir, config.jcl_globs), bridge_parser()
        )
        corpus_index = build_corpus_index(config, store.get)
        csd = _load_transid_to_program(config)
        # Members the index skipped come first: everything in them is absent from
        # the index, so they belong in the same report as the graph-building
        # failures.
        failures = (
            corpus_index.failures
            + csd.failures
            + _extract_all(config, corpus_index, csd, store)
        )
    _report_merged(config)
    _report_failures(failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
