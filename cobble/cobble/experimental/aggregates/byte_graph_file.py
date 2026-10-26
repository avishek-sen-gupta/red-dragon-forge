"""Reads the partition graph file a line at a time, keeping only what unify uses, with progress every tenth of the file."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from cobble.experimental.aggregates.byte_edge import ByteEdge
from cobble.experimental.aggregates.byte_edge_line import ByteEdgeLine
from cobble.experimental.aggregates.byte_graph import ByteGraph
from cobble.experimental.aggregates.byte_node import ByteNode
from cobble.experimental.aggregates.byte_node_line import ByteNodeLine
from cobble.experimental.partition.node_kind import NodeKind
from cobble.experimental.partition.progress import counted
from cobble.experimental.partition.tally import tenths
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)

UNIFY = "aggregate unify"
KEPT = frozenset({NodeKind.FIELD, NodeKind.DATASET})

_Line = ByteNodeLine | ByteEdgeLine
_LINE: TypeAdapter[_Line] = TypeAdapter(_Line)


def _texts(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8") as lines:
        yield from (line for line in lines if line.strip())


def _shared(edge: ByteEdge) -> ByteEdge:
    return replace(edge, source=sys.intern(edge.source), target=sys.intern(edge.target))


def _read(text: str) -> ByteNode | ByteEdge:
    line = _LINE.validate_json(text)
    if isinstance(line, ByteNodeLine):
        return replace(line.node, id=sys.intern(line.node.id))
    return _shared(line.edge)


def _kept(read: tuple[ByteNode | ByteEdge, ...]) -> ByteGraph:
    return ByteGraph(
        nodes=tuple(
            item for item in read if isinstance(item, ByteNode) and item.kind in KEPT
        ),
        edges=tuple(item for item in read if isinstance(item, ByteEdge)),
    )


def read_byte_graph(path: Path) -> ByteGraph:
    logger.info("%s: counting the lines of %s", UNIFY, path)
    total = sum(1 for _ in _texts(path))
    step = tenths(UNIFY, "graph lines read", total)
    return _kept(tuple(_read(text) for text in counted(_texts(path), step, total)))
