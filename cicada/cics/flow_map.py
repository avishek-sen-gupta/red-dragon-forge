"""extract_transaction_flow_map() / extract_transaction_flow_graph() — static
analysis builder APIs (public, unchanged signatures).

Thin composition over: cics.verb_source_lowering (lowers each program to
CicsVerb events), cics.csd_parse (CSD file→dataset edges), and
cics.flow_graph_core (verbs-as-data graph/map building). The verb-sourcing and
graph-building phases are separated so the knowledge-graph pipeline can reuse
flow_graph_core with its own (lowering-free) verb source.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from bms_copybook_gen.models import BmsMapSet
from cics.csd_parse import parse_csd_files
from cics.flow_graph_core import build_flow_graph, build_flow_map
from cics.verb_source_lowering import compile_all_programs
from interpreter.project.graph_types import GraphEdge, GraphNode


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
    transid_to_program, verbs_by_program = compile_all_programs(
        csd_source, cobol_sources, parser
    )
    return build_flow_map(transid_to_program, verbs_by_program, bms_mapsets)


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

    Same inputs and compilation as extract_transaction_flow_map — a different
    output shape, not new extraction. Every node id is uppercased (the
    standard CICS/COBOL convention).

    Also includes CICS_FILE -> DATASET edges from the CSD's own
    DEFINE FILE(name) ... DSNAME(dataset) entries (see
    cics.csd_parse.parse_csd_files) — a CSD with no such entries
    contributes none, additively.
    """
    transid_to_program, verbs_by_program = compile_all_programs(
        csd_source, cobol_sources, parser
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csd", delete=False) as f:
        f.write(csd_source)
        csd_path = Path(f.name)
    file_to_dataset = parse_csd_files(csd_path)
    csd_path.unlink(missing_ok=True)

    return build_flow_graph(
        transid_to_program, verbs_by_program, bms_mapsets, file_to_dataset
    )
