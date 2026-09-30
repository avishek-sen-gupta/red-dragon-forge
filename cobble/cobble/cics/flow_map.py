"""extract_transaction_flow_graph() — streaming CICS flow extraction.

Emits the CICS-flow portion of the knowledge graph into a GraphSink as each
program is read (via the verb source's on_verb seam), plus the structural
STARTS / DEFINES_DATASET edges from the CSD. Per-program failures are isolated
and loudly warned; they do not abort the pass.

Reading a program is the expensive part of a corpus run -- a bridge subprocess and
an ASG per member -- and it happens in this module's loop, so this is where the
pass says where it has got to: a bar over that loop, and the member's name at DEBUG
before it is read.

The pass RETURNS what it read and what it could not, rather than reporting into a
list the caller hands it: every other stage in build_graph hands its failures back
as a tuple, and a pass that mutates an argument cannot say how far it got.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING

from bms_copybook_gen.models import BmsMapSet
from cics.csd_parse import parse_csd, parse_csd_files
from cobble.cics.flow_observer import (  # noqa: F401  (re-exported vocabulary)
    CicsVerb,
    DynamicSite,
)
from cobble.cics.graph_sink import GraphSink
from cobble.cics.verb_source_asg import (  # SEAM: VM-free verb source
    VerbStreamResult,
    stream_program_verbs,
)
from cobble.knowledge_graph.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from cobol_asg.cobol_parser import CobolParser
from tqdm import tqdm

if TYPE_CHECKING:
    from cobble.corpus_index import CorpusIndex

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowExtraction:
    """A summary of one pass: which programs were read, which ones failed, and
    which dynamic XCTL/LINK sites turned up along the way."""

    programs_read: int = 0
    failures: tuple[str, ...] = ()
    dynamic_sites: tuple[DynamicSite, ...] = ()


@dataclass(frozen=True)
class _CsdDefinitions:
    """The two maps a CSD yields: transaction -> program, and file -> dataset."""

    transid_to_program: Mapping[str, str]
    file_to_dataset: Mapping[str, str]


def _csd_definitions(csd_source: str) -> _CsdDefinitions:
    """Parse CSD text, through the temp file both parsers take a path to."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    try:
        return _CsdDefinitions(parse_csd(csd_path), parse_csd_files(csd_path))
    finally:
        csd_path.unlink(missing_ok=True)


def _node(kind: NodeKind, node_id: str, corpus_index: CorpusIndex) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind=kind,
        location=corpus_index.resolve_file_path(kind, node_id),
    )


def _starts_edges(transid_to_program: Mapping[str, str]) -> Iterator[GraphEdge]:
    """TRANSACTION -> PROGRAM, one per CSD DEFINE TRANSACTION, ids uppercased."""
    return (
        GraphEdge(
            source=transid.upper(),
            source_kind=NodeKind.TRANSACTION,
            target=prog_name.upper(),
            target_kind=NodeKind.PROGRAM,
            kind=EdgeKind.STARTS,
        )
        for transid, prog_name in transid_to_program.items()
    )


def _defines_dataset_edges(file_to_dataset: Mapping[str, str]) -> Iterator[GraphEdge]:
    """CICS_FILE -> DATASET, one per CSD DEFINE FILE that names a DSNAME."""
    return (
        GraphEdge(
            source=file_name,
            source_kind=NodeKind.CICS_FILE,
            target=dataset_name,
            target_kind=NodeKind.DATASET,
            kind=EdgeKind.DEFINES_DATASET,
        )
        for file_name, dataset_name in file_to_dataset.items()
    )


def _emit(
    edges: Iterable[GraphEdge], sink: GraphSink, corpus_index: CorpusIndex
) -> None:
    """Each edge and both its endpoints, in the order a streaming sink writes them."""
    for edge in edges:
        sink.add_node(_node(edge.source_kind, edge.source, corpus_index))
        sink.add_node(_node(edge.target_kind, edge.target, corpus_index))
        sink.add_edge(edge)


def _programs_to_read(
    transid_to_program: Mapping[str, str], cobol_sources: Mapping[str, bytes]
) -> tuple[str, ...]:
    """Each program a transaction names and whose source the stage found, once, in
    CSD order. ``dict.fromkeys`` rather than a seen-set: a program two transactions
    name is one program to read, and reading it is a subprocess and an ASG.

    A program with no source is not a failure here -- the stage reported that when
    it looked for the file, before this pass ran.
    """
    named = dict.fromkeys(transid_to_program.values())
    return tuple(prog_name for prog_name in named if prog_name in cobol_sources)


def _read_program(
    prog_name: str,
    source: bytes,
    parser: CobolParser,
    bms_mapsets: Mapping[str, BmsMapSet],
    sink: GraphSink,
    corpus_index: CorpusIndex,
) -> VerbStreamResult:
    """One program's verb edges into the sink; what could not be read, and the
    dynamic sites it named.

    Named before the read, not after: on a corpus where one member takes minutes,
    this line is the only thing that distinguishes a working run from a stuck one.
    """
    logger.debug("CICS flow: reading %s", prog_name)
    return stream_program_verbs(
        prog_name, source, parser, bms_mapsets, sink, corpus_index
    )


def _read_programs(
    programs: Sequence[str],
    cobol_sources: Mapping[str, bytes],
    parser: CobolParser,
    bms_mapsets: Mapping[str, BmsMapSet],
    sink: GraphSink,
    corpus_index: CorpusIndex,
) -> tuple[VerbStreamResult, ...]:
    """Stream every program's CICS verbs into the sink; one result each."""
    return tuple(
        _read_program(
            prog_name,
            cobol_sources[prog_name],
            parser,
            bms_mapsets,
            sink,
            corpus_index,
        )
        for prog_name in tqdm(programs, desc="CICS verbs", unit="program")
    )


def extract_transaction_flow_graph(
    csd_source: str,
    bms_mapsets: Mapping[str, BmsMapSet],
    cobol_sources: Mapping[str, bytes],
    *,
    parser: CobolParser,
    sink: GraphSink,
    corpus_index: CorpusIndex,
) -> FlowExtraction:
    """Emit the CSD's structural edges and every program's CICS verb edges into
    ``sink``, and report what was read."""
    csd = _csd_definitions(csd_source)
    _emit(_starts_edges(csd.transid_to_program), sink, corpus_index)
    programs = _programs_to_read(csd.transid_to_program, cobol_sources)
    results = _read_programs(
        programs, cobol_sources, parser, bms_mapsets, sink, corpus_index
    )
    failures = tuple(chain.from_iterable(result.failures for result in results))
    dynamic_sites = tuple(
        chain.from_iterable(result.dynamic_sites for result in results)
    )
    _emit(_defines_dataset_edges(csd.file_to_dataset), sink, corpus_index)
    return FlowExtraction(
        programs_read=len(programs) - len(failures),
        failures=failures,
        dynamic_sites=dynamic_sites,
    )
