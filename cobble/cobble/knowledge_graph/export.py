"""NDJSON export/import for the merged knowledge graph — one line per node,
one line per edge, following the same analysis-only NDJSON precedent
interpreter.project.cobol_connections already established.

Both directions cross an untyped boundary: a networkx attribute dict on the
way out, json.loads output on the way in. The narrowing helpers here say what
each field was written as, so the row schema is stated once in the module that
owns it rather than re-guessed at every read.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import networkx as nx

from cobble.file_location import (
    NOT_ATTEMPTED,
    FileLocation,
    NoFileLocation,
    from_json,
    to_json_fields,
)
from cobble.interpreter.project.graph_types import (
    AttrValue,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def _kind_value(value: object) -> str:
    """A kind attribute off the merged graph, as the string that goes on the wire.

    networkx attribute dicts are untyped mappings; every kind in one was put
    there as a NodeKind or an EdgeKind by merge, so this narrows rather than
    converts. Anything else would be a merge bug and shows up as its own repr.
    """
    return value.value if isinstance(value, NodeKind | EdgeKind) else str(value)


def _location(value: object) -> FileLocation:
    """A location attribute off the merged graph, narrowed back to one.

    Same boundary as _kind_value. A value that is neither a path nor a stated
    reason came from something other than a GraphNode, and the only honest thing
    to write about it is that no resolution was recorded for it.
    """
    return value if isinstance(value, Path | NoFileLocation) else NOT_ATTEMPTED


def _node_row(data: Mapping[str, object]) -> Mapping[str, object]:
    """One node's JSON object. The two location fields are spread in from
    file_location, which owns what a location says on the wire."""
    return {
        "id": data["id"],
        "kind": _kind_value(data["kind"]),
        **to_json_fields(_location(data["location"])),
        "attrs": data["attrs"],
    }


def _edge_row(
    source: tuple[NodeKind, str],
    target: tuple[NodeKind, str],
    data: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        "source": source[1],
        "source_kind": source[0].value,
        "target": target[1],
        "target_kind": target[0].value,
        "kind": _kind_value(data["kind"]),
        "attrs": data["attrs"],
    }


def _write_lines(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def write_ndjson(graph: nx.MultiDiGraph, nodes_path: Path, edges_path: Path) -> None:
    """Write graph's nodes and edges as two NDJSON files."""
    _write_lines(nodes_path, (_node_row(data) for _key, data in graph.nodes(data=True)))
    _write_lines(
        edges_path,
        (
            _edge_row(source, target, data)
            for source, target, data in graph.edges(data=True)
        ),
    )


def _text(value: object) -> str:
    """A field the writer wrote as a string, read back as one.

    ``json.loads`` yields ``object``; every id/name field in a row was written
    from a ``str``, so this narrows rather than converts. A non-string would be
    a GraphWriter bug and shows up as its own repr in the merged graph.
    """
    return value if isinstance(value, str) else str(value)


def _attrs(row: Mapping[str, object]) -> dict[str, AttrValue]:
    """A row's attrs, as the mapping GraphNode and GraphEdge hold.

    Absent attrs and a non-object where they should be both read as empty: a
    single malformed row should not abort a whole corpus's worth of graph.
    """
    value = row.get("attrs")
    return dict(value) if isinstance(value, Mapping) else {}


def _node_from_json(row: Mapping[str, object]) -> GraphNode:
    return GraphNode(
        id=_text(row["id"]),
        kind=NodeKind(row["kind"]),
        location=from_json(row),
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


def _rows(path: Path) -> Iterable[Mapping[str, object]]:
    return (json.loads(line) for line in path.read_text().splitlines())


def read_ndjson(
    nodes_path: Path, edges_path: Path
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Read (nodes, edges) back from NDJSON files written by write_ndjson."""
    return (
        [_node_from_json(row) for row in _rows(nodes_path)],
        [_edge_from_json(row) for row in _rows(edges_path)],
    )
