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

from collections.abc import Mapping

from bms_copybook_gen.models import BmsMapSet
from cobble.cics.flow_observer import CicsVerb, field_direction
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, NodeKind

# Which edge each verb yields, grouped by what the edge points at. A verb absent
# from all four tables is one the graph does not read.
VSAM_FILE_EDGE_KIND: dict[str, EdgeKind] = {
    "READ": EdgeKind.READS,
    "WRITE": EdgeKind.WRITES,
    "REWRITE": EdgeKind.UPDATES,
    "DELETE": EdgeKind.DELETES,
    "STARTBR": EdgeKind.READS,
    "READNEXT": EdgeKind.READS,
    "READPREV": EdgeKind.READS,
    "ENDBR": EdgeKind.ENDS_BROWSE,
}

# The same verbs, for the kind an edge earns when the file is a candidate only.
VSAM_FILE_CANDIDATE_EDGE_KIND: dict[str, EdgeKind] = {
    "READ": EdgeKind.READS_CANDIDATE,
    "WRITE": EdgeKind.WRITES_CANDIDATE,
    "REWRITE": EdgeKind.UPDATES_CANDIDATE,
    "DELETE": EdgeKind.DELETES_CANDIDATE,
    "STARTBR": EdgeKind.READS_CANDIDATE,
    "READNEXT": EdgeKind.READS_CANDIDATE,
    "READPREV": EdgeKind.READS_CANDIDATE,
    "ENDBR": EdgeKind.ENDS_BROWSE_CANDIDATE,
}

_PROGRAM_EDGE_KIND: dict[str, EdgeKind] = {
    "XCTL": EdgeKind.XCTL,
    "LINK": EdgeKind.LINK,
}

# RETURN TRANSID hands control on as the task ends; START TRANSID dispatches work
# asynchronously. Same endpoints, so one branch, with the kind saying which.
_TRANSACTION_EDGE_KIND: dict[str, EdgeKind] = {
    "RETURN_TRANSID": EdgeKind.RETURN_TRANSID,
    "START_TRANSID": EdgeKind.START_TRANSID,
}

_MAP_EDGE_KIND: dict[str, EdgeKind] = {
    "SEND_MAP": EdgeKind.SENDS_MAP,
    "RECEIVE_MAP": EdgeKind.RECEIVES_MAP,
}


def _named_map(verb: CicsVerb, bms_mapsets: Mapping[str, BmsMapSet]) -> tuple:
    """The BMS map a verb names, as a 0-or-1 tuple.

    An unknown mapset and a known mapset carrying no such map are the same answer
    here: nothing to take field metadata from.
    """
    mapset = bms_mapsets.get(verb.mapset_name or "")
    maps = mapset.maps if mapset else ()
    return tuple(m for m in maps if m.label == verb.map_name)


def _bms_fields(
    verb: CicsVerb, bms_mapsets: Mapping[str, BmsMapSet]
) -> list[dict[str, str]]:
    """Field direction metadata for a SEND_MAP/RECEIVE_MAP verb, or [] if unavailable."""
    if not (verb.verb in _MAP_EDGE_KIND and verb.mapset_name and verb.map_name):
        return []
    return [
        {"name": f.label, "direction": field_direction(f)}
        for bms_map in _named_map(verb, bms_mapsets)
        for f in bms_map.fields
    ]


def _file_edge(
    verb: CicsVerb, _bms_mapsets: Mapping[str, BmsMapSet]
) -> tuple[GraphEdge, ...]:
    """The VSAM point and browse verbs, which name a CICS file."""
    if verb.verb not in VSAM_FILE_EDGE_KIND or not verb.file_name:
        return ()
    return (
        GraphEdge(
            source=verb.program.upper(),
            source_kind=NodeKind.PROGRAM,
            target=verb.file_name.upper(),
            target_kind=NodeKind.CICS_FILE,
            kind=VSAM_FILE_EDGE_KIND[verb.verb],
        ),
    )


def _program_edge(
    verb: CicsVerb, _bms_mapsets: Mapping[str, BmsMapSet]
) -> tuple[GraphEdge, ...]:
    """XCTL and LINK: both name the program they transfer to."""
    if verb.verb not in _PROGRAM_EDGE_KIND or not verb.xctl_target:
        return ()
    return (
        GraphEdge(
            source=verb.program.upper(),
            source_kind=NodeKind.PROGRAM,
            target=verb.xctl_target.upper(),
            target_kind=NodeKind.PROGRAM,
            kind=_PROGRAM_EDGE_KIND[verb.verb],
        ),
    )


def _transaction_edge(
    verb: CicsVerb, _bms_mapsets: Mapping[str, BmsMapSet]
) -> tuple[GraphEdge, ...]:
    """RETURN TRANSID and START TRANSID: both name a transaction, not a program."""
    if verb.verb not in _TRANSACTION_EDGE_KIND or not verb.transid:
        return ()
    return (
        GraphEdge(
            source=verb.program.upper(),
            source_kind=NodeKind.PROGRAM,
            target=verb.transid.upper(),
            target_kind=NodeKind.TRANSACTION,
            kind=_TRANSACTION_EDGE_KIND[verb.verb],
        ),
    )


def _map_edge(
    verb: CicsVerb, bms_mapsets: Mapping[str, BmsMapSet]
) -> tuple[GraphEdge, ...]:
    """SEND MAP and RECEIVE MAP, carrying field directions when BMS supplies them."""
    if verb.verb not in _MAP_EDGE_KIND or not (verb.mapset_name and verb.map_name):
        return ()
    fields = _bms_fields(verb, bms_mapsets)
    return (
        GraphEdge(
            source=verb.program.upper(),
            source_kind=NodeKind.PROGRAM,
            target=f"{verb.mapset_name.upper()}.{verb.map_name.upper()}",
            target_kind=NodeKind.BMS_MAP,
            kind=_MAP_EDGE_KIND[verb.verb],
            attrs={"fields": fields} if fields else {},
        ),
    )


# Tried in order; verb names do not overlap between them, so at most one answers.
_EDGE_BUILDERS = (_file_edge, _program_edge, _transaction_edge, _map_edge)


def _verb_edge(
    verb: CicsVerb, bms_mapsets: Mapping[str, BmsMapSet]
) -> tuple[GraphEdge, ...]:
    """The graph edges one CicsVerb event yields: one for a verb that names a
    graph target, none for a verb that does not (e.g. a plain RETURN with no
    TRANSID, or an XCTL whose target the parser could not resolve)."""
    built = (builder(verb, bms_mapsets) for builder in _EDGE_BUILDERS)
    return next((edges for edges in built if edges), ())
