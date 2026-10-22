"""build_graph.py — config-driven knowledge-graph extraction over a
COBOL/CICS/JCL corpus.

Runs the same four extractors as production (JCL, CALL/COPY, CICS flow, batch
FILE-CONTROL) entirely through the ``cobble.*`` package tree (a byte-for-byte +
import-rewrite port of the production extractors, with ONE seam: VM-free CICS
verb sourcing in cobble/cics/verb_source_asg.py). No VM, no compile/lower
pipeline.

Corpus location and layout come from a TOML config file (see
cobble/corpus_config.py) passed via --config -- nothing about the corpus is
hardcoded here. Writes the graph to --output as one JSONL file, a row per node
and per edge, and prints per-extractor + merged counts.

Needs a cobble-parse-corpus run first: the CICS-flow and FILE-CONTROL extractors
read the ASGs from the config's asg_dir rather than parsing them, because a parse
is 4-7 seconds of JVM per member and every other stage needs the same ASGs. A member absent from
that cache is reported as one skipped member, not silently reparsed.

Every extractor RETURNS what it skipped rather than appending to a shared list,
so a failure is part of a stage's result instead of an effect it had on its
caller's state, and the run's report is one fold over those results. The
GraphWriter it feeds is the one real accumulator here, and deliberately so: its
job is to stream to disk.

Invoke as: uv run python -m cobble.build_graph --config <path> --output <file>

Env: JCL_BRIDGE_JAR -- `. ../bridge-env.sh` exports it. No COBOL is parsed here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from itertools import chain
from pathlib import Path
from types import MappingProxyType

import networkx as nx
from cics.csd_parse import CsdParseError, parse_csd
from cobble.cics.asg_dialect_scope import asg_dialect_parsers_registered
from cobble.cics.flow_graph_core import (
    VSAM_FILE_CANDIDATE_EDGE_KIND,
    VSAM_FILE_EDGE_KIND,
)
from cobble.cics.flow_map import FlowExtraction, extract_transaction_flow_graph
from cobble.cics.flow_observer import DynamicSite
from cobble.cics.graph_sink import GraphSink
from cobble.cics.suppressed_transactions import SuppressedTransactions
from cobble.cics.synth_csd import SYNTHETIC_TRANSID_PREFIX
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.corpus_index import CorpusIndex, FileLocationResolver
from cobble.corpus_index_builder import build_corpus_index
from cobble.dataflow.fields.emit_extents import worker_count
from cobble.dataflow.fixpoint.rows import Row, strings, text
from cobble.dataflow.fixpoint.rows import read as read_targets
from cobble.dataflow.fixpoint.target_kind import TargetKind
from cobble.dynamic_call_targets import NO_DYNAMIC_CALL_TARGETS, DynamicCallTargets
from cobble.jcl.cobol_file_graph import file_accesses, file_graph
from cobble.jcl.file_accesses import FileAccesses
from cobble.jcl.jcl_graph import jcl_graph_from_job
from cobble.jcl.jcl_store import JclStore, temp_jcl_store
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobble.knowledge_graph.graph_writer import GraphWriter, graph_writer
from cobble.knowledge_graph.merge import merge_graph
from cobble.matching_files import matching_files
from cobble.ordered_work import consumed_in_order
from cobble.parsing.asg_cache import cached_first_program, programs_of
from cobble.path_utils import ensure_parent
from cobol_asg.cobol_imports import extract_cobol_imports
from cobol_asg.import_types import ImportKind, ImportRef
from cobol_asg.source_text import decode_source
from jackal.expansion import DirectoryProcLibrary
from jackal.jcl.parser import bridge_parser
from tqdm import tqdm

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


def _unusable_csd_paths(config: CorpusConfig) -> tuple[Path, ...]:
    """Every configured CSD that is not a regular file, which no read can recover.

    Content is the guarded stage's business: a CSD that parses to nothing is a
    corpus problem, reported per file. A path that is not a file is the CONFIG
    being wrong, and it costs the whole CICS flow stage -- every TRANSACTION node,
    every STARTS edge, and the parse of every CICS member, because the worklist is
    the transaction map's values.

    Empty csd_files is not here: a corpus with no CICS configures none, and the
    stage says it skipped.
    """
    return tuple(path for path in config.csd_files if not path.is_file())


def _unusable_csd_message(unusable: Sequence[Path]) -> str:
    """Why the run is refusing to start, and the two ways out.

    A generated CSD lives wherever cobble-csd --out put it, so cleaning that
    directory leaves the config pointing at nothing -- and a directory can appear at that path from any tool
    told to write there. Both read the same from here.
    """
    return "\n".join(
        (
            f"{len(unusable)} configured csd_files entr(y/ies) not a readable file:",
            *(f"  - {path}" for path in unusable),
            "The whole CICS flow stage reads these, so the graph would have no",
            "TRANSACTION nodes and no CICS member parsed at all. Regenerate a",
            "synthetic CSD (`cobble-csd --config <config>`), or correct csd_files.",
        )
    )


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


def _counted_lines(tally: Mapping[str, int]) -> tuple[str, ...]:
    """Commonest first, ties by name. Sorted on negated counts rather than with a
    sort-order callback, which talisman reads as a secret pattern."""
    return tuple(
        f"  {-negated_count:5}  {name}"
        for negated_count, name in sorted(
            (-count, name) for name, count in tally.items()
        )
    )


def _tally_lines(failures: Sequence[str]) -> tuple[str, ...]:
    return _counted_lines(Counter(map(_category, failures)))


def _failure_report_lines(failures: Sequence[str]) -> tuple[str, ...]:
    return (
        "",
        RULE,
        f"!!  {len(failures)} FAILURE(S) -- THIS GRAPH IS INCOMPLETE",
        "!!  The members below were SKIPPED. Everything in them is absent from",
        "!!  the graph file and every reference to it is UNRESOLVED.",
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
    the graph file, and every reference to them resolves UNRESOLVED. The counts
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
            DirectoryProcLibrary(tuple(config.proclib_dirs)),
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
        location=corpus_index.resolve_file_path(NodeKind.PROGRAM, program),
    )


def _ref_node(target: str, kind: NodeKind, corpus_index: CorpusIndex) -> GraphNode:
    return GraphNode(
        id=target,
        kind=kind,
        location=corpus_index.resolve_file_path(kind, target),
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


# ── dynamic call targets: the three-way rule over targets.jsonl ──────────────

# One row's ``transfer`` to the edge kind it earns once the site is a proven
# fact: exactly one candidate and an empty ``reasons``, or no candidate at
# all -- both cases are certain about the transfer itself.
_ORDINARY: Mapping[str, EdgeKind] = MappingProxyType(
    {
        "CICS_XCTL": EdgeKind.XCTL,
        "CICS_LINK": EdgeKind.LINK,
        "CALL": EdgeKind.CALL,
        **{f"CICS_{verb}": kind for verb, kind in VSAM_FILE_EDGE_KIND.items()},
    }
)

# The same rows, for the kind a site earns instead when two or more
# candidates survived, or one did but carrying doubt.
_CANDIDATE: Mapping[str, EdgeKind] = MappingProxyType(
    {
        "CICS_XCTL": EdgeKind.XCTL_CANDIDATE,
        "CICS_LINK": EdgeKind.LINK_CANDIDATE,
        "CALL": EdgeKind.CALL_CANDIDATE,
        **{
            f"CICS_{verb}": kind for verb, kind in VSAM_FILE_CANDIDATE_EDGE_KIND.items()
        },
    }
)

# CicsVerb spells XCTL/LINK and the file verbs without the CICS_ prefix
# targets.jsonl's ``transfer`` column carries; only these verbs reach
# _not_attempted_graph, since a dynamic COBOL CALL is invisible to the walk that
# fills it.
_CICS_TRANSFER: Mapping[str, EdgeKind] = MappingProxyType(
    {"XCTL": EdgeKind.XCTL, "LINK": EdgeKind.LINK, **VSAM_FILE_EDGE_KIND}
)

# What a resolved name of each kind of site points at.
_NAMED_KIND: Mapping[TargetKind, NodeKind] = MappingProxyType(
    {TargetKind.PROGRAM: NodeKind.PROGRAM, TargetKind.FILE: NodeKind.CICS_FILE}
)

# A graph-level value the lattice never produces -- nothing in the analysis
# concludes this, only the absence of the artifact that would have.
_NOT_ATTEMPTED = "not-attempted"

_DynamicGraph = tuple[tuple[GraphNode, ...], tuple[GraphEdge, ...]]


def _dynamic_target_id(caller: str, expression: str) -> str:
    """The id ``<program>.<expression>`` -- scoped like FIELD, never corpus-wide;
    see NodeKind.DYNAMIC_TARGET."""
    return f"{caller}.{expression}"


def _dynamic_target_node(
    caller: str,
    expression: str,
    reason: str,
    dropped: Sequence[str],
    corpus_index: CorpusIndex,
) -> GraphNode:
    node_id = _dynamic_target_id(caller, expression)
    return GraphNode(
        id=node_id,
        kind=NodeKind.DYNAMIC_TARGET,
        location=corpus_index.resolve_file_path(NodeKind.DYNAMIC_TARGET, node_id),
        attrs={"reason": reason, "dropped": list(dropped)},
    )


@dataclass(frozen=True)
class _RowSite:
    """One targets.jsonl row's site: who names it, by which statement, and whether
    it names a program or a CICS file."""

    caller: str
    transfer: str
    kind: TargetKind


def _row_site(row: Row) -> _RowSite:
    return _RowSite(
        caller=text(row, "caller"),
        transfer=text(row, "transfer"),
        kind=TargetKind(text(row, "kind", TargetKind.PROGRAM.value)),
    )


def _named_node(site: _RowSite, name: str, corpus_index: CorpusIndex) -> GraphNode:
    return _ref_node(name, _NAMED_KIND[site.kind], corpus_index)


def _ordinary_target(
    site: _RowSite, candidate: str, corpus_index: CorpusIndex
) -> _DynamicGraph:
    """Exactly one candidate and no doubt: a proven edge to the program or file."""
    node = _named_node(site, candidate, corpus_index)
    return (
        (node,),
        (_ref_edge(site.caller, node.id, node.kind, _ORDINARY[site.transfer]),),
    )


def _candidate_edge(
    site: _RowSite, node: GraphNode, reasons: Sequence[str]
) -> GraphEdge:
    """A file candidate carries why it is not proven; a call candidate does not."""
    edge = _ref_edge(site.caller, node.id, node.kind, _CANDIDATE[site.transfer])
    if site.kind is not TargetKind.FILE:
        return edge
    return replace(edge, attrs={"reasons": ", ".join(reasons)})


def _candidate_targets(
    site: _RowSite,
    candidates: Sequence[str],
    reasons: Sequence[str],
    corpus_index: CorpusIndex,
) -> _DynamicGraph:
    """Two or more candidates, or one carrying doubt: one *_CANDIDATE edge each."""
    nodes = tuple(_named_node(site, name, corpus_index) for name in candidates)
    return nodes, tuple(_candidate_edge(site, node, reasons) for node in nodes)


def _no_candidate_target(
    site: _RowSite, row: Row, corpus_index: CorpusIndex
) -> _DynamicGraph:
    """No candidate survived: a proven transfer to a DYNAMIC_TARGET node, which
    carries why -- the reasons, or (candidates and reasons both empty) the
    dropped values that explain it on their own."""
    node = _dynamic_target_node(
        site.caller,
        text(row, "expression"),
        ", ".join(strings(row, "reasons")),
        strings(row, "dropped"),
        corpus_index,
    )
    return (node,), (
        _ref_edge(
            site.caller, node.id, NodeKind.DYNAMIC_TARGET, _ORDINARY[site.transfer]
        ),
    )


def _row_target(row: Row, corpus_index: CorpusIndex) -> _DynamicGraph:
    """One targets.jsonl row, resolved by the three-way rule.

    Promotion to an ordinary edge requires an empty ``reasons``, not merely one
    candidate: a walk that did not settle yields a subset, so a singleton
    carrying a reason may have a second candidate the walk never reached.
    """
    site = _row_site(row)
    candidates = strings(row, "candidates")
    reasons = strings(row, "reasons")
    if len(candidates) == 1 and not reasons:
        return _ordinary_target(site, candidates[0], corpus_index)
    if candidates:
        return _candidate_targets(site, candidates, reasons, corpus_index)
    return _no_candidate_target(site, row, corpus_index)


def dynamic_target_graph(
    rows: Sequence[Row], corpus_index: CorpusIndex
) -> _DynamicGraph:
    """Every dynamic CALL/XCTL/LINK site targets.jsonl names, as the three-way
    rule's nodes and edges. See _ORDINARY/_CANDIDATE and NodeKind.DYNAMIC_TARGET."""
    built = tuple(_row_target(row, corpus_index) for row in rows)
    return (
        tuple(chain.from_iterable(nodes for nodes, _edges in built)),
        tuple(chain.from_iterable(edges for _nodes, edges in built)),
    )


def _not_attempted_graph(
    sites: Sequence[DynamicSite], corpus_index: CorpusIndex
) -> _DynamicGraph:
    """The dynamic XCTL/LINK sites no targets.jsonl row answers, marked
    not-attempted.

    ``sites`` is what _write_not_attempted_sites left after subtracting the
    table's own (caller, expression) pairs, so a site the analysis resolved is
    never also written here under the wrong reason.
    """
    return (
        tuple(
            _dynamic_target_node(
                site.program, site.expression, _NOT_ATTEMPTED, (), corpus_index
            )
            for site in sites
        ),
        tuple(
            _ref_edge(
                site.program,
                _dynamic_target_id(site.program, site.expression),
                NodeKind.DYNAMIC_TARGET,
                _CICS_TRANSFER[site.transfer],
            )
            for site in sites
        ),
    )


def _operand_name(expression: str) -> str:
    """An operand expression reduced to the data-name the two front ends agree on.

    They do not agree on the rest. The fixpoint's CFG renders the subscript into its
    ``expression`` -- CDEMO-MENU-OPT-PGMNAME(WS-OPTION) -- while the CICS walk
    carries the data-name alone, so matching the rendered texts leaves the two menu
    sites reading as unanswered and marks them not-attempted beside the eleven
    candidates the table had already resolved for them. In COBOL the name ends at
    the first parenthesis, whether a subscript or a reference modifier follows.
    """
    return expression.split("(", 1)[0].strip()


def _site(caller: str, expression: str, kind: TargetKind) -> tuple[str, str, str]:
    return caller, _operand_name(expression), kind.value


def _dynamic_site_kind(site: DynamicSite) -> TargetKind:
    return (
        TargetKind.FILE if site.transfer in VSAM_FILE_EDGE_KIND else TargetKind.PROGRAM
    )


def _covered_sites(targets: DynamicCallTargets) -> frozenset[tuple[str, str, str]]:
    """Every (caller, operand, kind) the dynamic-call-targets table answers for.

    Matched on the operand and not on the CFG node id: a row carries the node the
    fixpoint's own CFG named, and the CICS walk knows a site by the program and the
    operand alone. A caller writing one operand at several sites is answered by one
    entry, which is how the DYNAMIC_TARGET id is scoped too. The kind keeps a file
    row from answering a call naming its program through the same field.
    """
    return frozenset(
        _site(text(row, "caller"), text(row, "expression"), _row_site(row).kind)
        for row in targets.rows
    )


def _unanswered_sites(
    sites: Sequence[DynamicSite], covered: frozenset[tuple[str, str, str]]
) -> tuple[DynamicSite, ...]:
    """The sites no row in the table speaks for."""
    return tuple(
        site
        for site in sites
        if _site(site.program, site.expression, _dynamic_site_kind(site)) not in covered
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
    the raw COPY/CALL scan (cobol_asg.cobol_imports), plus the single
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

    paths: tuple[tuple[str, Path], ...] = ()
    failures: tuple[str, ...] = ()


def _cics_source(program: str, stems: Mapping[str, Path]) -> _CicsSources:
    if program not in stems:
        message = f"CICS program {program}: not found in cobol_globs matches"
        logger.warning("CICS program %s: not found in cobol_globs matches", program)
        return _CicsSources(failures=(message,))
    return _CicsSources(paths=((program, stems[program]),))


def _cics_sources(
    program_names: frozenset[str], stems: Mapping[str, Path]
) -> _CicsSources:
    # "CICS sources", not "CICS flow": this loop only finds each member's source
    # path. The flow stage -- one ASG per member, built from the parse cache, i.e. all
    # of the stage's cost -- runs after it, under its own bar in cics/flow_map.py.
    found = tuple(
        _cics_source(program, stems)
        for program in tqdm(program_names, desc="CICS sources", unit="program")
    )
    return _CicsSources(
        paths=tuple(chain.from_iterable(item.paths for item in found)),
        failures=tuple(chain.from_iterable(item.failures for item in found)),
    )


def _build_cics_flow_graph(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    transid_to_program: Mapping[str, str],
    targets: DynamicCallTargets,
    writer: GraphWriter,
    max_workers: int,
) -> tuple[str, ...]:
    stems = {
        path.stem.upper(): path
        for path in matching_files(config.cobol_dir, config.cobol_globs)
    }
    found = _cics_sources(frozenset(transid_to_program.values()), stems)
    # The stage's inputs first, then the pass over them, then what it read: the two
    # counts answer different questions, and a stage that only ever printed its
    # inputs could not say whether anything came out.
    logger.info(
        "CICS flow: %d transactions, %d program sources found",
        len(transid_to_program),
        len(found.paths),
    )
    return found.failures + _run_flow_extractor(
        config, corpus_index, found, targets, writer, max_workers
    )


def _is_synthetic_transaction(kind: NodeKind, node_id: str) -> bool:
    return kind is NodeKind.TRANSACTION and node_id.startswith(SYNTHETIC_TRANSID_PREFIX)


@dataclass(frozen=True)
class _WithoutSyntheticTransactions:
    """A sink that drops the placeholder transactions a generated CSD carries.

    cobble/cics/synth_csd.py defines a transaction for every CICS member, because
    that definition is the only way a member reaches the flow stage's worklist and
    has its literal LINK/XCTL edges read. The members whose real transaction is not
    recoverable are defined under ``UNKNOWN.<member>``, and nothing in the corpus
    says those transactions exist -- so they must not reach the graph.

    Filtered here rather than upstream because the flow pass parses the CSD itself
    and emits a TRANSACTION node and a STARTS edge for every definition in it, and
    because which transactions are placeholders is this module's own convention, not
    something the pass over a CSD can know. Edges are dropped by either endpoint: an
    edge to a node that was never written would dangle.
    """

    inner: GraphSink
    suppressed: SuppressedTransactions = field(default_factory=SuppressedTransactions)

    def add_node(self, node: GraphNode) -> None:
        if _is_synthetic_transaction(node.kind, node.id):
            self.suppressed.transaction(node.id)
            return
        self.inner.add_node(node)

    def add_edge(self, edge: GraphEdge) -> None:
        if _is_synthetic_transaction(
            edge.source_kind, edge.source
        ) or _is_synthetic_transaction(edge.target_kind, edge.target):
            self.suppressed.edge()
            return
        self.inner.add_edge(edge)


def _without_synthetic_transactions(sink: GraphSink) -> _WithoutSyntheticTransactions:
    return _WithoutSyntheticTransactions(inner=sink)


def _csd_source(config: CorpusConfig) -> str:
    """Every configured CSD as one document, which is what the flow pass parses."""
    return "\n".join(
        decode_source(csd_file.read_bytes()) for csd_file in config.csd_files
    )


def _log_suppressed(suppressed: SuppressedTransactions) -> None:
    """Say what the placeholder filter removed, or say nothing when it removed
    nothing -- a real CSD has no placeholders and needs no line about them."""
    if not suppressed.transactions:
        return
    logger.info(
        "CICS flow: %d placeholder transactions suppressed, with %d of their edges",
        len(suppressed.transactions),
        suppressed.edges,
    )


def _write_not_attempted_sites(
    targets: DynamicCallTargets,
    corpus_index: CorpusIndex,
    extraction: FlowExtraction,
    writer: GraphWriter,
) -> None:
    """Every dynamic site this walk saw that the dynamic-call-targets table does not
    answer for.

    Subtracted site by site rather than skipped whenever the file exists: a table
    written for a subset of members -- a fields config carrying a ``members``
    filter, or a member whose walk the dequeue cap gave up on and whose rows were
    dropped -- covers some callers and not others, and testing the file would
    remove every uncovered member's sites from the graph entirely. That is the
    invisibility this stage exists to end, applied to exactly the members hardest
    to analyse.

    dynamic_target_graph over the table (wired in _extract_all) remains the
    exclusive source for a site the table does name, so nothing here duplicates
    or races it.
    """
    sites = _unanswered_sites(extraction.dynamic_sites, _covered_sites(targets))
    logger.info(
        "dynamic sites: %d seen, %d answered by --dynamic-call-targets, %d marked %s",
        len(extraction.dynamic_sites),
        len(extraction.dynamic_sites) - len(sites),
        len(sites),
        _NOT_ATTEMPTED,
    )
    writer.add_all(*_not_attempted_graph(sites, corpus_index))


def _flow_extraction_attempt(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    found: _CicsSources,
    writer: GraphWriter,
    max_workers: int,
) -> tuple[FlowExtraction, tuple[str, ...]]:
    """What the whole-CSD pass produced, or a blank FlowExtraction paired with
    a single abort message when it raised.

    The whole CSD is one call, so a failure escaping it is the stage's, not one
    member's -- and one that escapes takes the pass's own report with it, so the
    per-program failures it had already collected are lost. Hence the sink is built
    here: what it suppressed survives the exception and is logged either way.
    """
    sink = _without_synthetic_transactions(writer)
    try:
        extraction = extract_transaction_flow_graph(
            csd_source=_csd_source(config),
            bms_mapsets={},
            members=dict(found.paths),
            read_asg=partial(cached_first_program, config.asg_dir),
            sink=sink,
            corpus_index=corpus_index,
            max_workers=max_workers,
        )
    except Exception as exc:
        logger.warning("CICS flow graph (whole CSD) failed: %s", exc, exc_info=True)
        return FlowExtraction(), (f"CICS flow graph (whole CSD): {exc}",)
    finally:
        _log_suppressed(sink.suppressed)
    return extraction, ()


def _run_flow_extractor(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    found: _CicsSources,
    targets: DynamicCallTargets,
    writer: GraphWriter,
    max_workers: int,
) -> tuple[str, ...]:
    """Run the flow extractor over the whole CSD and return what it skipped."""
    extraction, abort = _flow_extraction_attempt(
        config, corpus_index, found, writer, max_workers
    )
    if abort:
        return abort
    logger.info(
        "CICS flow: %d programs read, %d skipped",
        extraction.programs_read,
        len(extraction.failures),
    )
    _write_not_attempted_sites(targets, corpus_index, extraction, writer)
    return extraction.failures


def _cics_flow_or_skip(
    config: CorpusConfig,
    corpus_index: CorpusIndex,
    transid_to_program: Mapping[str, str],
    targets: DynamicCallTargets,
    writer: GraphWriter,
    max_workers: int,
) -> tuple[str, ...]:
    if not config.csd_files:
        logger.info("CICS flow: skipped (no csd_files configured)")
        return ()
    return _build_cics_flow_graph(
        config, corpus_index, transid_to_program, targets, writer, max_workers
    )


# ── extractor 4: batch FILE-CONTROL ──────────────────────────────


@dataclass(frozen=True)
class _FileControlRead:
    """One batch member as a worker read it: what each of its programs OPENs, or
    why it could not be read. Locations are resolved by the process that writes
    the graph."""

    found: tuple[FileAccesses, ...] = ()
    failures: tuple[str, ...] = ()


def _file_control_read(path: Path, asg_dir: Path) -> _FileControlRead:
    try:
        with asg_dialect_parsers_registered():
            asgs = programs_of(asg_dir, path)
        return _FileControlRead(found=tuple(file_accesses(asg) for asg in asgs))
    except Exception as exc:
        logger.warning("FILE-CONTROL %s failed: %s", path.name, exc, exc_info=True)
        return _FileControlRead(failures=(f"FILE-CONTROL {path.name}: {exc}",))


def _file_control_written(
    read: _FileControlRead, corpus_index: FileLocationResolver, writer: GraphWriter
) -> tuple[str, ...]:
    if read.failures:
        return read.failures
    for found in read.found:
        writer.add_all(*file_graph(found, corpus_index))
    return ()


def _file_control_failures(
    path: Path,
    asg_dir: Path,
    corpus_index: FileLocationResolver,
    writer: GraphWriter,
) -> tuple[str, ...]:
    return _file_control_written(
        _file_control_read(path, asg_dir), corpus_index, writer
    )


def _build_batch_file_graph(
    config: CorpusConfig,
    corpus_index: FileLocationResolver,
    cics_program_names: frozenset[str],
    writer: GraphWriter,
    max_workers: int,
) -> tuple[str, ...]:
    cbl_files = tuple(
        path
        for path in matching_files(config.cobol_dir, config.cobol_globs)
        if path.stem.upper() not in cics_program_names
    )
    # One ASG at a time per worker, out of the cache cobble-parse-corpus wrote,
    # written to the graph in member order whatever order the workers finish in.
    failures = consumed_in_order(
        partial(_file_control_read, asg_dir=config.asg_dir),
        cbl_files,
        max_workers,
        lambda reads: tuple(
            chain.from_iterable(
                _file_control_written(read, corpus_index, writer)
                for read in tqdm(
                    reads, total=len(cbl_files), desc="FILE-CONTROL", unit="program"
                )
            )
        ),
    )
    logger.info("FILE-CONTROL: %d batch programs", len(cbl_files))
    return failures


# ── the run ──────────────────────────────────────────────────────


def _build_dynamic_targets(
    targets: DynamicCallTargets, corpus_index: CorpusIndex
) -> _DynamicGraph:
    """The three-way rule's nodes and edges over the dynamic-call-targets table.

    Logged as its own input, not folded silently into a stage that already runs:
    a corpus whose node count changed because this table was or was not named
    must read as that, not as drift nothing explains.
    """
    logger.info("dynamic call targets: %d rows", len(targets.rows))
    return dynamic_target_graph(targets.rows, corpus_index)


def _extract_all(
    config: CorpusConfig,
    output: Path,
    targets: DynamicCallTargets,
    corpus_index: CorpusIndex,
    csd: _CsdRead,
    store: JclStore,
    max_workers: int,
) -> tuple[str, ...]:
    """Run the four extractors into one writer, returning everything they skipped."""
    cics_program_names = frozenset(csd.transid_to_program.values())
    with graph_writer(ensure_parent(output), corpus_index) as writer:
        failures = (
            _build_jcl_graph(config, corpus_index, writer, store)
            + _build_call_copy_graph(config, corpus_index, cics_program_names, writer)
            + _cics_flow_or_skip(
                config,
                corpus_index,
                csd.transid_to_program,
                targets,
                writer,
                max_workers,
            )
            + _build_batch_file_graph(
                config, corpus_index, cics_program_names, writer, max_workers
            )
        )
        writer.add_all(*_build_dynamic_targets(targets, corpus_index))
        return failures


def _edge_kind_lines(graph: nx.MultiDiGraph) -> tuple[str, ...]:
    """How many edges of each kind the graph just written has.

    Every other count a run prints is an input -- transactions defined, programs
    compiled -- so nothing said whether a kind of edge came out at all, which is the
    question after any change that adds one. Counted from the graph read back off
    disk, so it counts what a consumer will read: deduped, filtered and merged.
    """
    return _counted_lines(
        Counter(attrs["kind"].value for *_endpoints, attrs in graph.edges(data=True))
    )


def _report_merged(output: Path) -> None:
    graph = merge_graph(*read_graph(output))
    logger.info(
        "\nMerged graph: %d nodes, %d edges\n%s\nWrote %s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        "\n".join(_edge_kind_lines(graph)),
        output,
    )


def _dynamic_call_targets(text: str) -> DynamicCallTargets:
    path = Path(text)
    if not path.is_file():
        raise argparse.ArgumentTypeError(
            f"{path} not found — cobble-dataflow-fixpoint writes targets.jsonl "
            "into its --out-dir"
        )
    return DynamicCallTargets(rows=read_targets(path))


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus TOML config (see cobble/corpus_config.py / config/carddemo.toml)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="The graph file to write: one JSON line per node and per edge, tagged with which it is",
    )
    parser.add_argument(
        "--dynamic-call-targets",
        type=_dynamic_call_targets,
        default=NO_DYNAMIC_CALL_TARGETS,
        help="The targets.jsonl cobble-dataflow-fixpoint wrote: which programs each "
        "dynamic CALL/XCTL/LINK site can reach. Without it, no dynamic-target edges",
    )
    parser.add_argument(
        "--max-workers",
        type=worker_count,
        default=4,
        help="Worker processes for the CICS verbs, and threads for the JCL bridge "
        "(default 4). The graph is the same for any count",
    )
    return parser.parse_args(argv)


def _corpus_failures(
    config: CorpusConfig, output: Path, targets: DynamicCallTargets, max_workers: int
) -> tuple[str, ...]:
    """One full pass over the corpus, returning everything it skipped.

    Both JCL passes read every member, so the bridge runs once per member here
    rather than once per pass. The store keeps only the bridge's JSON, on disk,
    and deserializes one Job at a time -- a resident Job per member does not
    scale to a corpus. Its cache dies with the store, so no run can be served
    output from a different grammar.
    """
    with temp_jcl_store(max_workers) as store:
        store.parse_all(
            matching_files(config.jcl_dir, config.jcl_globs), bridge_parser()
        )
        corpus_index = build_corpus_index(config, store.get)
        csd = _load_transid_to_program(config)
        # Members the index skipped come first: everything in them is absent from
        # the index, so they belong in the same report as the graph-building
        # failures.
        return (
            corpus_index.failures
            + csd.failures
            + _extract_all(
                config, output, targets, corpus_index, csd, store, max_workers
            )
        )


def main() -> int:
    # Everything this run says is a log record on stderr, which is where the tqdm
    # bars already are -- so the per-stage counts and the bar each followed
    # interleave in the order they happened, with no stdout buffering to work
    # around. stdout stays empty.
    configure_cli_logging()
    args = _parse_args(sys.argv[1:])
    config = load_corpus_config(args.config)
    # Before the expensive phase, because this one cannot be recovered from later:
    # read as a per-file failure it was one warning in a report under a graph that
    # otherwise looked finished.
    unusable_csd = _unusable_csd_paths(config)
    if unusable_csd:
        sys.exit(_unusable_csd_message(unusable_csd))
    failures = _corpus_failures(
        config, args.output, args.dynamic_call_targets, args.max_workers
    )
    _report_merged(args.output)
    _report_failures(failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
