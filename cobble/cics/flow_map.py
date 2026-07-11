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

from cobble.bms_copybook_gen.models import BmsMapSet
from cobble.cics.csd_parse import parse_csd, parse_csd_files
from cobble.cics.flow_observer import CicsVerb  # noqa: F401  (re-exported vocabulary)
from cobble.cics.graph_sink import GraphSink
from cobble.cics.verb_source_asg import (
    stream_program_verbs,
)  # SEAM: VM-free verb source (was cics.verb_source_lowering)
from cobble.interpreter.project.graph_types import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


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
        sink.add_edge(
            GraphEdge(
                source=t,
                source_kind=NodeKind.TRANSACTION,
                target=p,
                target_kind=NodeKind.PROGRAM,
                kind=EdgeKind.STARTS,
            )
        )

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
        sink.add_edge(
            GraphEdge(
                source=file_name,
                source_kind=NodeKind.CICS_FILE,
                target=dataset_name,
                target_kind=NodeKind.DATASET,
                kind=EdgeKind.DEFINES_DATASET,
            )
        )
