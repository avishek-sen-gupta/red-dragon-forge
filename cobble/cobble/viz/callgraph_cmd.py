"""CLI: extract program-level call dependency graph from cobble's graph file.

Input:  --graph <file>              (the graph file cobble-build --output wrote)
        <srccfg_dir>/cfg-*.jsonl    (cobble CFG or closure bundle — the program list)
Output: <out_dir>/call-dep.json     (CallDepGraph)
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import EdgeKind, GraphEdge
from cobble.path_utils import ensure_parent
from cobble.viz.models import CallDepGraph, CallEdge, ProgramNode

_LOG = logging.getLogger(__name__)

# (src_prog, tgt_prog, paragraph, commarea)
_LinkKey = tuple[str, str, str, str]

# The proven program-to-program transfers; a *_CANDIDATE edge is a possible
# target the analysis could not vouch for.
_CALL_KINDS = frozenset({EdgeKind.CALL, EdgeKind.XCTL, EdgeKind.LINK})


def _extract_para(edge: GraphEdge) -> str:
    return str(
        edge.attrs.get("paragraph")
        or (edge.source.split(".")[1] if "." in edge.source else "")
    )


def _is_cross_link(src: str, tgt: str, target_programs: frozenset[str]) -> bool:
    return src in target_programs and tgt in target_programs and src != tgt


def _valid_link(
    edge: GraphEdge, target_programs: frozenset[str]
) -> tuple[_LinkKey, ...]:
    """Return a 1-tuple for a proven cross-program call edge, else ()."""
    if edge.kind not in _CALL_KINDS:
        return ()
    src = edge.source.split(".")[0]
    tgt = edge.target.split(".")[0]
    if not _is_cross_link(src, tgt, target_programs):
        return ()
    return ((src, tgt, _extract_para(edge), str(edge.attrs.get("commarea") or "")),)


def _callees_of(prog: str, keys: frozenset[_LinkKey]) -> tuple[str, ...]:
    return tuple(sorted({tgt for src, tgt, p2, p3 in keys if src == prog}))


def _callers_of(prog: str, keys: frozenset[_LinkKey]) -> tuple[str, ...]:
    return tuple(sorted({src for src, tgt, p2, p3 in keys if tgt == prog}))


def extract(graph_path: Path, target_programs: frozenset[str]) -> CallDepGraph:
    _nodes, graph_edges = read_graph(graph_path)
    unique_keys: frozenset[_LinkKey] = frozenset(
        link for edge in graph_edges for link in _valid_link(edge, target_programs)
    )

    edges = tuple(
        CallEdge(from_program=src, to_program=tgt, paragraph=para, commarea=comm)
        for src, tgt, para, comm in sorted(unique_keys)
    )
    nodes = tuple(
        ProgramNode(
            program=prog,
            calls=_callees_of(prog, unique_keys),
            called_by=_callers_of(prog, unique_keys),
        )
        for prog in sorted(target_programs)
    )
    programs = sorted(target_programs)
    entry = next(
        (prog for prog in programs if not _callers_of(prog, unique_keys)),
        next(iter(programs), ""),
    )
    return CallDepGraph(entry=entry, nodes=nodes, edges=edges)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--graph", required=True, type=Path, help="The graph file cobble-build wrote"
    )
    ap.add_argument("--cfg", required=True, type=Path, help="cobble cfg-<ENTRY>.jsonl")
    ap.add_argument("--out", required=True, type=Path, help="output call-dep.json")
    return ap.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    if not args.graph.is_file():
        _LOG.error(
            "error: %s not found — run `cobble-build --output` first", args.graph
        )
        return 1
    targets = frozenset(cfg.program for cfg in load_bundle(args.cfg).cfgs)
    graph = extract(args.graph, targets)
    ensure_parent(args.out).write_text(graph.model_dump_json(indent=2))
    _LOG.info("call-dep.json: %d nodes, %d edges", len(graph.nodes), len(graph.edges))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return _run(_parse_args(sys.argv[1:]))
