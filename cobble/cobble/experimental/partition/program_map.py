"""The program map: one node per program and per dataset record, an edge per pair some graph edge links, laid out by a seeded force layout."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import quote

import networkx as nx
from cobble.experimental.partition.graph_index import GraphIndex
from cobble.experimental.partition.layout import LAYOUT_SEED
from cobble.experimental.partition.map_data import MapData
from cobble.experimental.partition.map_edge import MapEdge
from cobble.experimental.partition.map_kind import MapKind
from cobble.experimental.partition.map_node import MapNode
from cobble.experimental.partition.node_kind import NodeKind

TEMPLATE = Path(__file__).with_name("program_map.html")
SCALE = 100.0


def _groups(index: GraphIndex) -> Mapping[str, str]:
    return {
        node.id: node.record if node.kind is NodeKind.DATASET else node.program
        for node in index.nodes.values()
    }


def _links(index: GraphIndex, group: Mapping[str, str]) -> Counter[tuple[str, str]]:
    pairs = (
        tuple(sorted((group[edge.source], group[edge.target]))) for edge in index.edges
    )
    return Counter((pair[0], pair[1]) for pair in pairs if pair[0] != pair[1])


def _placed(
    names: Sequence[str], links: Counter[tuple[str, str]]
) -> Mapping[str, tuple[float, float]]:
    linked: nx.Graph[str] = nx.Graph()
    linked.add_nodes_from(names)
    linked.add_weighted_edges_from((a, b, float(n)) for (a, b), n in links.items())
    placed = nx.spring_layout(linked, seed=LAYOUT_SEED, weight="weight")
    return {
        name: (float(placed[name][0]) * SCALE, float(placed[name][1]) * SCALE)
        for name in names
    }


def _node(name: str, kind: MapKind, at: tuple[float, float], fields: int) -> MapNode:
    href = f"programs/{quote(name, safe='')}.html" if kind is MapKind.PROGRAM else ""
    return MapNode(
        id=name, kind=kind, label=name, x=at[0], y=at[1], fields=fields, href=href
    )


def program_map(index: GraphIndex) -> MapData:
    group = _groups(index)
    sizes = Counter(group.values())
    kinds = {
        group[node.id]: (
            MapKind.DATASET if node.kind is NodeKind.DATASET else MapKind.PROGRAM
        )
        for node in index.nodes.values()
    }
    names = sorted(kinds)
    links = _links(index, group)
    at = _placed(names, links)
    return MapData(
        nodes=tuple(_node(name, kinds[name], at[name], sizes[name]) for name in names),
        edges=tuple(
            MapEdge(source=a, target=b, links=n) for (a, b), n in sorted(links.items())
        ),
    )


def map_page(data: MapData, sources: Sequence[str]) -> str:
    head, rest = TEMPLATE.read_text(encoding="utf-8").split("/*SCRIPTS*/", 1)
    middle, tail = rest.split("/*DATA*/", 1)
    payload = data.model_dump_json().replace("</", "<\\/")
    tags = "\n".join(f'<script src="{source}"></script>' for source in sources)
    return f"{head}{tags}{middle}{payload}{tail}"
