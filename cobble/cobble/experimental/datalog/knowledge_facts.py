"""The knowledge graph's nodes and edges as facts."""

from collections.abc import Iterable, Mapping, Sequence
from itertools import chain
from pathlib import Path

from cobble.experimental.datalog.column import symbol
from cobble.experimental.datalog.encoding import yes_no
from cobble.experimental.datalog.facts import Facts, Row
from cobble.experimental.datalog.relation import Relation
from cobble.experimental.datalog.run_files import required
from cobble.knowledge_graph.attr_value import AttrValue
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import GraphEdge

KG_NODE = Relation("kg_node", (symbol("id"), symbol("kind")))
_EDGE_COLUMNS = (
    symbol("src"),
    symbol("src_kind"),
    symbol("kind"),
    symbol("dst"),
    symbol("dst_kind"),
)
KG_EDGE = Relation("kg_edge", _EDGE_COLUMNS)
KG_EDGE_ATTR = Relation(
    "kg_edge_attr", (*_EDGE_COLUMNS, symbol("key"), symbol("value"))
)


def _scalar_text(value: str | int | float | bool) -> str:
    return yes_no(value) if isinstance(value, bool) else str(value)


def _flattened(
    pairs: Iterable[tuple[str, AttrValue]],
) -> tuple[tuple[str, str], ...]:
    return tuple(chain.from_iterable(_scalars(key, value) for key, value in pairs))


def _scalars(key: str, value: AttrValue) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        return _flattened((f"{key}.{name}", inner) for name, inner in value.items())
    if isinstance(value, str) or not isinstance(value, Sequence):
        return ((key, _scalar_text(value)),)
    return _flattened((f"{key}.{index}", inner) for index, inner in enumerate(value))


def _edge(edge: GraphEdge) -> Row:
    return (
        edge.source,
        edge.source_kind.value,
        edge.kind.value,
        edge.target,
        edge.target_kind.value,
    )


def _attrs(edge: GraphEdge) -> tuple[Row, ...]:
    return tuple((*_edge(edge), *pair) for pair in _flattened(edge.attrs.items()))


def knowledge_facts(run: Path) -> tuple[Facts, ...]:
    nodes, edges = read_graph(required(run / "knowledge-graph.jsonl"))
    return (
        Facts(KG_NODE, tuple((node.id, node.kind.value) for node in nodes)),
        Facts(KG_EDGE, tuple(map(_edge, edges))),
        Facts(KG_EDGE_ATTR, tuple(chain.from_iterable(map(_attrs, edges)))),
    )
