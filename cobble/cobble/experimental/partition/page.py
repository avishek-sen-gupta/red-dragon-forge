"""Renders the graph as one self-contained WebGL page."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from cobble.experimental.partition.field_components import component_of
from cobble.experimental.partition.field_graph import FieldGraph
from cobble.experimental.partition.fold import folded
from cobble.experimental.partition.layout import layout
from cobble.experimental.partition.page_data import PageData
from cobble.experimental.partition.page_node import PageNode

TEMPLATE = Path(__file__).with_name("partition_page.html")


def _data(full: FieldGraph) -> PageData:
    components = component_of(full)
    drawn = folded(full, components)
    graph = drawn.graph
    stands = {node: run[0].id for node, run in drawn.occurrences.items()}
    placement = layout(graph)
    points = placement.points
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
                component=components.get(stands.get(node.id, node.id), -1),
                degree=degree[node.id],
                occurrences=tuple(
                    member.label for member in drawn.occurrences.get(node.id, ())
                ),
                offset=node.offset,
                length=node.size,
            )
            for node in graph.nodes
        ),
        edges=graph.edges,
        regions=placement.regions,
    )


def page(graph: FieldGraph, sources: Sequence[str]) -> str:
    head, rest = TEMPLATE.read_text(encoding="utf-8").split("/*SCRIPTS*/", 1)
    middle, tail = rest.split("/*DATA*/", 1)
    data = _data(graph).model_dump_json().replace("</", "<\\/")
    tags = "\n".join(f'<script src="{source}"></script>' for source in sources)
    return f"{head}{tags}{middle}{data}{tail}"
