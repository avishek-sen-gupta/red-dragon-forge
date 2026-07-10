"""Production verb source for CICS flow analysis: lower each program through the
CICS lowering strategy and emit CicsVerb-derived graph edges directly.

The knowledge-graph pipeline does NOT use this module — it sources the same
{program: [CicsVerb]} shape from a typed-ASG walk instead — which is why the
lowering imports live here, isolated from the shared cics.flow_graph_core.
"""

from __future__ import annotations

import logging

from cics.flow_graph_core import _verb_edge
from cics.flow_observer import CicsVerb
from cics.graph_sink import GraphSink
from interpreter.project.graph_types import GraphNode

logger = logging.getLogger(__name__)


class GraphEmittingObserver:
    """on_verb → _verb_edge → push endpoints + edge to a GraphSink (no accumulation)."""

    def __init__(self, program_name: str, bms_mapsets, sink: GraphSink) -> None:
        self._program = program_name
        self._bms = bms_mapsets
        self._sink = sink

    def on_verb(self, verb) -> None:
        tagged = CicsVerb(
            verb=verb.verb, program=self._program, map_name=verb.map_name,
            mapset_name=verb.mapset_name, xctl_target=verb.xctl_target,
            transid=verb.transid, file_name=verb.file_name,
        )
        edge = _verb_edge(tagged, self._bms)
        if edge is None:
            return
        self._sink.add_node(GraphNode(id=edge.source, kind=edge.source_kind))
        self._sink.add_node(GraphNode(id=edge.target, kind=edge.target_kind))
        self._sink.add_edge(edge)


def stream_program_verbs(prog_name, raw, parser, bms_mapsets, sink, failures):
    """Compile one program under a GraphEmittingObserver; isolate + loudly warn on failure."""
    from cics.bootstrap import compile_cics_program  # noqa: PLC0415
    from cics.coprocessor import build_cics_spec  # noqa: PLC0415
    try:
        observer = GraphEmittingObserver(prog_name, bms_mapsets, sink)
        spec = build_cics_spec(context_holder=[None], result_holder=[None], observer=observer)
        compile_cics_program(raw, parser, spec)
    except Exception as exc:  # noqa: BLE001 — one bad program must not abort the run
        logger.warning("CICS program %s failed to compile: %s", prog_name, exc, exc_info=True)
        if failures is not None:
            failures.append(f"CICS program {prog_name}: {exc}")
