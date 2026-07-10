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

from cobble.bms_copybook_gen.models import BmsMapSet
from cobble.cics.flow_observer import CicsVerb, field_direction
from cobble.interpreter.project.graph_types import EdgeKind, GraphEdge, NodeKind


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
