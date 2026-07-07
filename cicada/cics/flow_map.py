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
        verb.mapset_name and verb.map_name and verb.verb in ("SEND_MAP", "RECEIVE_MAP")
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
