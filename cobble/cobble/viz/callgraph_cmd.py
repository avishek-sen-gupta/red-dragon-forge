"""CLI: extract program-level call dependency graph from cobble edges.

Input:  <out_dir>/edges.jsonl       (cobble dep graph)
        <srccfg_dir>/cfg-*.json     (cobble CFG or closure bundle — the program list)
Output: <out_dir>/call-dep.json     (CallDepGraph)
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from cobble.dataflow.srccfg.bundle import load_cfg_dicts
from cobble.path_utils import ensure_parent
from cobble.viz.models import CallDepGraph, CallEdge, ProgramNode

_LOG = logging.getLogger(__name__)

# (src_prog, tgt_prog, paragraph, commarea)
_LinkKey = tuple[str, str, str, str]
# Concrete JSON edge shape: attrs is always str-keyed str-valued
_Attrs = Mapping[str, str]
_RawEdge = Mapping[str, str | _Attrs]


def _extract_para(edge: _RawEdge) -> str:
    raw_attrs = edge.get("attrs", {})
    attrs: _Attrs = raw_attrs if isinstance(raw_attrs, Mapping) else {}
    source_str = str(edge.get("source", ""))
    return str(
        attrs.get("paragraph")
        or (source_str.split(".")[1] if "." in source_str else "")
    )


def _is_cross_link(src: str, tgt: str, target_programs: frozenset[str]) -> bool:
    return src in target_programs and tgt in target_programs and src != tgt


def _valid_link(
    edge: _RawEdge, target_programs: frozenset[str]
) -> tuple[_LinkKey, ...]:
    """Return a 1-tuple for a valid cross-program LINK edge, else ()."""
    if edge.get("kind") != "LINK":
        return ()
    src = str(edge.get("source", "")).split(".")[0]
    tgt = str(edge.get("target", "")).split(".")[0]
    if not _is_cross_link(src, tgt, target_programs):
        return ()
    raw_attrs = edge.get("attrs", {})
    attrs: _Attrs = raw_attrs if isinstance(raw_attrs, Mapping) else {}
    return ((src, tgt, _extract_para(edge), str(attrs.get("commarea") or "")),)


def _callees_of(prog: str, keys: frozenset[_LinkKey]) -> tuple[str, ...]:
    return tuple(sorted({tgt for src, tgt, p2, p3 in keys if src == prog}))


def _callers_of(prog: str, keys: frozenset[_LinkKey]) -> tuple[str, ...]:
    return tuple(sorted({src for src, tgt, p2, p3 in keys if tgt == prog}))


def extract(edges_path: Path, target_programs: frozenset[str]) -> CallDepGraph:
    edges_raw: Sequence[_RawEdge] = [
        json.loads(line) for line in edges_path.read_text().splitlines() if line.strip()
    ]

    unique_keys: frozenset[_LinkKey] = frozenset(
        key for edge in edges_raw for key in _valid_link(edge, target_programs)
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
    entry = next(
        (
            prog
            for prog in sorted(target_programs)
            if not _callers_of(prog, unique_keys)
        ),
        sorted(target_programs)[0],
    )
    return CallDepGraph(entry=entry, nodes=nodes, edges=edges)


def _run(args: argparse.Namespace) -> None:
    cfgs_raw = load_cfg_dicts(args.cfg)
    targets = frozenset(c["program"] for c in cfgs_raw)
    graph = extract(args.edges, targets)
    ensure_parent(args.out).write_text(graph.model_dump_json(indent=2))
    _LOG.info("call-dep.json: %d nodes, %d edges", len(graph.nodes), len(graph.edges))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--edges", required=True, type=Path, help="cobble edges.jsonl")
    ap.add_argument("--cfg", required=True, type=Path, help="cobble cfg-<ENTRY>.json")
    ap.add_argument("--out", required=True, type=Path, help="output call-dep.json")
    _run(ap.parse_args())
