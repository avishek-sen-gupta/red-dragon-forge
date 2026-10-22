"""Renders the graph and its clusters as one self-contained WebGL page."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from cobble.experimental.partition.cluster_set import ClusterSet
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.layout import layout
from cobble.experimental.partition.page_data import PageData
from cobble.experimental.partition.page_node import PageNode

TEMPLATE = Path(__file__).with_name("partition_page.html")


def _data(graph: FieldGraph, clusters: ClusterSet) -> PageData:
    points = layout(graph, clusters)
    placed = {
        member: (cluster.component, cluster.id)
        for cluster in clusters.clusters
        for member in cluster.members
    }
    degree = Counter(end for edge in graph.edges for end in (edge.source, edge.target))
    return PageData(
        barrier=graph.barrier,
        nodes=tuple(
            PageNode(
                id=node.id,
                kind=node.kind,
                label=node.label,
                program=node.program,
                record=node.record,
                pic=node.pic,
                x=points[node.id][0],
                y=points[node.id][1],
                component=placed.get(node.id, (-1, -1))[0],
                cluster=placed.get(node.id, (-1, -1))[1],
                degree=degree[node.id],
            )
            for node in graph.nodes
        ),
        edges=graph.edges,
    )


def page(graph: FieldGraph, clusters: ClusterSet, scripts: Sequence[str]) -> str:
    head, rest = TEMPLATE.read_text(encoding="utf-8").split("/*SCRIPTS*/", 1)
    middle, tail = rest.split("/*DATA*/", 1)
    data = _data(graph, clusters).model_dump_json().replace("</", "<\\/")
    tags = "\n".join(f"<script>{script}</script>" for script in scripts)
    return f"{head}{tags}{middle}{data}{tail}"
