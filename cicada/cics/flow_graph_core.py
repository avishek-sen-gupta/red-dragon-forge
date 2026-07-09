"""CICS flow-graph building — verbs-as-data core shared by production and the
knowledge-graph pipeline.

Given a transid→program map and per-program CicsVerb lists (however sourced —
production lowers each program; the graph pipeline walks the typed ASG), build
either the JSON transaction flow map or the CICS-flow portion of the shared
knowledge graph. This module does NO CSD parsing, NO compilation, and imports
NO lowering machinery — it is the leaf the graph pipeline copies. See
cics.verb_source_lowering for production's verb source and cics.flow_map for the
composed public entry points.
"""

from __future__ import annotations

from bms_copybook_gen.models import BmsMapSet
from cics.flow_observer import CicsVerb, field_direction
from interpreter.project.graph_types import EdgeKind, GraphEdge, GraphNode, NodeKind


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


def build_flow_map(
    transid_to_program: dict[str, str],
    verbs_by_program: dict[str, list[CicsVerb]],
    bms_mapsets: dict[str, BmsMapSet],
) -> list[dict]:  # type: ignore[type-arg]
    """Build the JSON transaction flow map from already-sourced verbs."""
    results: list[dict] = []  # type: ignore[type-arg]
    for transid, prog_name in transid_to_program.items():
        verbs = verbs_by_program.get(prog_name, [])
        results.append(
            {
                "transid": transid,
                "entry_program": prog_name,
                "flow": [_enrich_verb(v, bms_mapsets) for v in verbs],
            }
        )
    return results


_VSAM_FILE_EDGE_KIND: dict[str, EdgeKind] = {
    "READ": EdgeKind.READS,
    "WRITE": EdgeKind.WRITES,
    "REWRITE": EdgeKind.UPDATES,
    "DELETE": EdgeKind.DELETES,
    "STARTBR": EdgeKind.READS,
    "READNEXT": EdgeKind.READS,
    "READPREV": EdgeKind.READS,
    "ENDBR": EdgeKind.ENDS_BROWSE,
}


def _verb_edge(verb: CicsVerb, bms_mapsets: dict[str, BmsMapSet]) -> GraphEdge | None:
    """Convert one CicsVerb event into a GraphEdge, or None for verbs with no
    graph-relevant target (e.g. a plain RETURN with no TRANSID)."""
    program_id = verb.program.upper()
    if verb.verb in _VSAM_FILE_EDGE_KIND and verb.file_name:
        return GraphEdge(
            source=program_id,
            source_kind=NodeKind.PROGRAM,
            target=verb.file_name.upper(),
            target_kind=NodeKind.CICS_FILE,
            kind=_VSAM_FILE_EDGE_KIND[verb.verb],
        )
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


def build_flow_graph(
    transid_to_program: dict[str, str],
    verbs_by_program: dict[str, list[CicsVerb]],
    bms_mapsets: dict[str, BmsMapSet],
    file_to_dataset: dict[str, str],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Build the CICS-flow graph portion from already-sourced verbs + CSD file
    edges. Every node id is uppercased (the standard CICS/COBOL convention)."""
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

        for verb in verbs_by_program.get(prog_name, []):
            edge = _verb_edge(verb, bms_mapsets)
            if edge is None:
                continue
            _add_node(edge.source_kind, edge.source)
            _add_node(edge.target_kind, edge.target)
            edges.append(edge)

    for file_name, dataset_name in file_to_dataset.items():
        file_id = _add_node(NodeKind.CICS_FILE, file_name)
        dataset_id = _add_node(NodeKind.DATASET, dataset_name)
        edges.append(
            GraphEdge(
                source=file_id,
                source_kind=NodeKind.CICS_FILE,
                target=dataset_id,
                target_kind=NodeKind.DATASET,
                kind=EdgeKind.DEFINES_DATASET,
            )
        )

    return list(nodes.values()), edges
