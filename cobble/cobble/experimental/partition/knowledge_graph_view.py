"""The knowledge-graph edges a dataset join reads, indexed the ways it asks them."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from typing import TypeVar

from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge, NodeKind

USES = frozenset(
    {
        EdgeKind.READS,
        EdgeKind.WRITES,
        EdgeKind.UPDATES,
        EdgeKind.DELETES,
        EdgeKind.ENDS_BROWSE,
    }
)
RUNS = frozenset({EdgeKind.JCL_STEP_RUNS, EdgeKind.TSO_RUNS_PROGRAM})
CALL_CANDIDATE = "call-candidate"
CALLS: Mapping[EdgeKind, tuple[str, ...]] = {
    EdgeKind.CALL: (),
    EdgeKind.CALL_CANDIDATE: (CALL_CANDIDATE,),
}

_Caller = tuple[str, tuple[str, ...]]
_T = TypeVar("_T", str, _Caller)


def _grouped(pairs: Sequence[tuple[str, _T]]) -> Mapping[str, tuple[_T, ...]]:
    return {
        name: tuple(value for _, value in group)
        for name, group in groupby(sorted(pairs), itemgetter(0))
    }


@dataclass(frozen=True)
class KnowledgeGraph:
    """Program file bindings, step DD bindings, who runs and calls whom, and the CSD's file datasets."""

    edges: tuple[GraphEdge, ...]

    def _of(
        self, kinds: frozenset[EdgeKind], source: NodeKind, target: NodeKind
    ) -> tuple[GraphEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.kind in kinds
            and edge.source_kind is source
            and edge.target_kind is target
        )

    @cached_property
    def selects(self) -> Mapping[tuple[str, str], str]:
        return {
            (edge.source, str(edge.attrs.get("select_name", ""))): edge.target
            for edge in self._of(USES, NodeKind.PROGRAM, NodeKind.COBOL_FILE)
        }

    @cached_property
    def bindings(self) -> Mapping[tuple[str, str], str]:
        return {
            (edge.source, str(edge.attrs.get("ddname", ""))): edge.target
            for edge in self._of(USES, NodeKind.STEP, NodeKind.DATASET)
        }

    @cached_property
    def runs(self) -> Mapping[str, tuple[str, ...]]:
        return _grouped(
            tuple(
                (edge.target, edge.source)
                for edge in self._of(RUNS, NodeKind.STEP, NodeKind.PROGRAM)
            )
        )

    @cached_property
    def callers(self) -> Mapping[str, tuple[_Caller, ...]]:
        return _grouped(
            tuple(
                (edge.target, (edge.source, CALLS[edge.kind]))
                for edge in self._of(
                    frozenset(CALLS), NodeKind.PROGRAM, NodeKind.PROGRAM
                )
            )
        )

    @cached_property
    def csd(self) -> Mapping[str, str]:
        return {
            edge.source.rstrip(): edge.target
            for edge in self._of(
                frozenset({EdgeKind.DEFINES_DATASET}),
                NodeKind.CICS_FILE,
                NodeKind.DATASET,
            )
        }


def knowledge_graph(path: Path) -> KnowledgeGraph:
    _, edges = read_graph(path)
    return KnowledgeGraph(edges=tuple(edges))
