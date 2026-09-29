"""cobble-viz-pathwalk: paragraph-level data layer for CFG path animation."""

from __future__ import annotations

import argparse
import importlib.resources
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from functools import reduce
from pathlib import Path
from typing import IO, TypedDict

import networkx as nx
from cobble.dataflow.srccfg.cfg import Cfg, Edge, EdgeKind, Node

_LOG = logging.getLogger(__name__)

# A JSON-safe value: scalar, sequence, or string-keyed mapping thereof.
JsonValue = str | int | float | bool | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
JsonRecord = Mapping[str, JsonValue]


# ---------------------------------------------------------------------------
# Bundle output types
# ---------------------------------------------------------------------------


class AnimNode(TypedDict):
    """One paragraph node in the animation graph."""

    id: str
    label: str
    x: float
    y: float
    kind: str


class AnimEdge(TypedDict):
    """One directed edge between paragraphs."""

    source: str
    target: str
    kind: str


class AnimPath(TypedDict):
    """One annotated path through the paragraph graph."""

    paragraphs: list[str]
    branch_edges_new: list[list[str]]
    provenance: dict[str, tuple[JsonRecord, ...]]


class AnimBundle(TypedDict):
    """Full animation bundle passed to the HTML renderer."""

    nodes: list[AnimNode]
    edges: list[AnimEdge]
    paths: list[AnimPath]
    vars: list[str]
    speed_ms: int
    pause_ms: int


# ---------------------------------------------------------------------------
# collapse_path
# ---------------------------------------------------------------------------


def node_paragraph_of(cfgs: Sequence[Cfg]) -> dict[str, str]:
    """Every statement-level node.id -> its qualified "PROGRAM/PARAGRAPH" key.

    The only correct way to resolve a node id to its paragraph: via the
    structured ``(cfg.program, node.paragraph)`` fields every ``Cfg`` already
    carries. Never by splitting the id string -- real ids are
    ``"{paragraph}#label"``, ``"{paragraph}#end"``, or
    ``"{paragraph}/{statement_index}"``, carrying no program prefix at all
    (``PathListener`` in the sampler only ever emits the bare node id). A
    split on ``"/"`` recovers the statement index, not the paragraph, for
    the third shape, and does not split at all for the first two.
    """
    return {
        node.id: f"{cfg.program}/{node.paragraph}" for cfg in cfgs for node in cfg.nodes
    }


def _collapse_step(
    node_para: Mapping[str, str], acc: tuple[str, ...], node_id: str
) -> tuple[str, ...]:
    para = node_para.get(node_id, "")
    if not para:
        return acc
    return acc if (acc and acc[-1] == para) else (*acc, para)


def collapse_path(
    nodes: tuple[str, ...], node_para: Mapping[str, str]
) -> tuple[str, ...]:
    """Map statement-level node IDs to qualified paragraph keys via
    ``node_para`` (see ``node_paragraph_of``), dropping consecutive repeats.

    An id absent from ``node_para`` is dropped rather than injected as an
    unresolved placeholder -- a trace path may visit a node outside the
    loaded CFG bundle (e.g. a callee not included in ``--cfg``), and
    dropping keeps the collapsed sequence contiguous.
    """
    return reduce(
        lambda acc, node_id: _collapse_step(node_para, acc, node_id), nodes, ()
    )


# ---------------------------------------------------------------------------
# paragraphs_of
# ---------------------------------------------------------------------------


def _add_node_to_para(
    acc: Mapping[str, frozenset[str]], entry: tuple[str, Node]
) -> dict[str, frozenset[str]]:
    program, node = entry
    key = f"{program}/{node.paragraph}"
    return {**acc, key: acc.get(key, frozenset()) | {node.id}}


def paragraphs_of(cfgs: Sequence[Cfg]) -> dict[str, set[str]]:
    """Map "PROGRAM/paragraph" key → set of statement node IDs across all CFGs."""
    all_entries = tuple((cfg.program, node) for cfg in cfgs for node in cfg.nodes)
    frozen = reduce(_add_node_to_para, all_entries, {})
    return {k: set(v) for k, v in frozen.items()}


# ---------------------------------------------------------------------------
# paragraph_graph — helpers
# ---------------------------------------------------------------------------


def _cross_para_pair(edge: Edge, node_para: Mapping[str, str]) -> tuple[str, str]:
    """Qualified (src_para, tgt_para) via ``node_para``, or ("", "") when
    same paragraph or either endpoint is unresolvable.

    Resolved via the same structured lookup ``node_paragraph_of`` builds --
    never by splitting ``edge.source``/``edge.target``, which cannot recover
    a paragraph from a "#label"/"#end" suffixed id (no "/" to split on) and
    recovers the statement index, not the paragraph, from a "/"-suffixed one.
    """
    src_para = node_para.get(edge.source, "")
    tgt_para = node_para.get(edge.target, "")
    if not src_para or not tgt_para or src_para == tgt_para:
        return ("", "")
    return (src_para, tgt_para)


def _first_matching_kind(
    cfg: Cfg, node_para: Mapping[str, str], src_para: str, tgt_para: str
) -> str:
    matching = next(
        (
            e
            for e in cfg.edges
            if _cross_para_pair(e, node_para) == (src_para, tgt_para)
        ),
        Edge(source="", target="", kind=EdgeKind.FLOW),
    )
    return matching.kind.value


def _cross_valid_edges(
    cfg: Cfg, node_para: Mapping[str, str]
) -> tuple[tuple[str, str], ...]:
    """All qualified cross-paragraph (src, tgt) pairs from a CFG's edges."""
    return tuple(
        pair for pair in (_cross_para_pair(e, node_para) for e in cfg.edges) if pair[0]
    )


def _add_cfg_edges(g: nx.DiGraph, cfg: Cfg, node_para: Mapping[str, str]) -> nx.DiGraph:
    for src_para, tgt_para in _cross_valid_edges(cfg, node_para):
        g.add_edge(
            src_para,
            tgt_para,
            kind=_first_matching_kind(cfg, node_para, src_para, tgt_para),
        )
    return g


def _add_cfg_nodes(g: nx.DiGraph, cfg: Cfg) -> nx.DiGraph:
    for node in cfg.nodes:
        g.add_node(f"{cfg.program}/{node.paragraph}", kind=node.kind.value)
    return g


def _add_cfg_to_graph(
    g: nx.DiGraph, cfg: Cfg, node_para: Mapping[str, str]
) -> nx.DiGraph:
    return _add_cfg_edges(_add_cfg_nodes(g, cfg), cfg, node_para)


def paragraph_graph(cfgs: Sequence[Cfg]) -> nx.DiGraph:
    """Directed paragraph-level graph from a CFG bundle.

    Nodes are program-qualified paragraph keys ("PROGRAM/PARAGRAPH"), which
    avoids collisions when different programs reuse the same paragraph name.
    Edges are cross-paragraph transitions within a program.
    """
    node_para = node_paragraph_of(cfgs)
    return reduce(
        lambda g, cfg: _add_cfg_to_graph(g, cfg, node_para), cfgs, nx.DiGraph()
    )


# ---------------------------------------------------------------------------
# layered_positions
# ---------------------------------------------------------------------------


def _back_edges(g: nx.DiGraph) -> frozenset[tuple[str, str]]:
    return frozenset(
        (u, v)
        for cycle in nx.simple_cycles(g)
        for u, v in zip(cycle, (*cycle[1:], cycle[0]), strict=False)
    )


def _isolated_nodes(g: nx.DiGraph, dag: nx.DiGraph) -> tuple[str, ...]:
    return tuple(node for node in g.nodes() if node not in dag)


def _dag_from_acyclic(g: nx.DiGraph) -> nx.DiGraph:
    back = _back_edges(g)
    dag = nx.DiGraph((u, v) for u, v in g.edges() if (u, v) not in back)
    for node in _isolated_nodes(g, dag):
        dag.add_node(node)
    return dag


def _dag_from(g: nx.DiGraph) -> nx.DiGraph:
    return nx.DiGraph(g) if nx.is_directed_acyclic_graph(g) else _dag_from_acyclic(g)


def _x_for(pos_idx: int, n_in_layer: int) -> float:
    return 0.05 + (pos_idx / (n_in_layer - 1)) * 0.90 if n_in_layer > 1 else 0.5


def _layer_positions(
    layer_idx: int, n_layers: int, layer: Sequence[str]
) -> dict[str, tuple[float, float]]:
    y = round(0.05 + (layer_idx / max(n_layers - 1, 1)) * 0.90, 4)
    return {
        node: (round(_x_for(pos_idx, len(layer)), 4), y)
        for pos_idx, node in enumerate(sorted(layer))
    }


def _generations(g: nx.DiGraph) -> list[list[str]]:
    try:
        return list(nx.topological_generations(_dag_from(g)))
    except nx.NetworkXUnfeasible:
        return [list(g.nodes())]


def layered_positions(g: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Assign stable x,y positions in [0.05, 0.95]² using topological layering.

    Returns ``{node_name: (x, y)}`` where y increases with depth.
    """
    generations = _generations(g)
    n_layers = max(len(generations), 1)
    return {
        node: xy
        for layer_idx, layer in enumerate(generations)
        for node, xy in _layer_positions(layer_idx, n_layers, layer).items()
    }


# ---------------------------------------------------------------------------
# _derive_branch_edges_new
# ---------------------------------------------------------------------------


def _path_edges(path: tuple[str, ...], g: nx.DiGraph) -> frozenset[tuple[str, str]]:
    return frozenset(
        (path[i], path[i + 1])
        for i in range(len(path) - 1)
        if g.has_edge(path[i], path[i + 1])
    )


def _new_edges_step(
    g: nx.DiGraph,
    acc: tuple[frozenset[tuple[str, str]], tuple[list[list[str]], ...]],
    path: tuple[str, ...],
) -> tuple[frozenset[tuple[str, str]], tuple[list[list[str]], ...]]:
    covered, result = acc
    newly = _path_edges(path, g) - covered
    return (covered | newly, (*result, sorted([list(e) for e in newly])))


def _derive_branch_edges_new(
    paths: Sequence[tuple[str, ...]],
    g: nx.DiGraph,
) -> tuple[list[list[str]], ...]:
    _, result = reduce(
        lambda acc, path: _new_edges_step(g, acc, path),
        paths,
        (frozenset(), ()),
    )
    return result


# ---------------------------------------------------------------------------
# build_bundle — helpers
# ---------------------------------------------------------------------------


def _parse_path_records(path_records: IO[str]) -> tuple[JsonRecord, ...]:
    return tuple(
        row
        for row in (json.loads(line.strip()) for line in path_records if line.strip())
        if row.get("kind") == "path"
    )


def _str_get(mapping: JsonValue, field: str, default: str = "") -> str:
    if isinstance(mapping, Mapping):
        val = mapping.get(field, default)
        return str(val) if isinstance(val, (str, int, float, bool)) else default
    return default


def _int_get(mapping: JsonValue, field: str) -> int:
    if isinstance(mapping, Mapping):
        val = mapping.get(field, 0)
        return int(val) if isinstance(val, (int, float)) else 0
    return 0


def _provenance_entry(dep: JsonValue) -> tuple[str, JsonRecord]:
    if not isinstance(dep, Mapping):
        return ("", {})
    target_info = dep.get("target") or {}
    source_info = dep.get("source") or {}
    tgt_field = _str_get(target_info, "field")
    return (
        tgt_field,
        {
            "target_start": _int_get(target_info, "start"),
            "target_end": _int_get(target_info, "end"),
            "source_field": _str_get(source_info, "field"),
            "source_start": _int_get(source_info, "start"),
            "source_end": _int_get(source_info, "end"),
            "origin": _str_get(dep, "origin"),
        },
    )


_Provenance = dict[str, tuple[JsonRecord, ...]]


def _append_prov(acc: _Provenance, kv: tuple[str, JsonRecord]) -> _Provenance:
    field, entry = kv
    return {**acc, field: (*acc[field], entry)} if field in acc else acc


def _provenance_for_vars(
    deps: Sequence[JsonValue], var_names: Sequence[str]
) -> _Provenance:
    empty: _Provenance = {v: () for v in var_names}
    return reduce(_append_prov, (_provenance_entry(dep) for dep in deps), empty)


def _raw_nodes(raw: JsonRecord) -> tuple[str, ...]:
    val = raw.get("nodes", ())
    if isinstance(val, Sequence) and not isinstance(val, str):
        return tuple(str(n) for n in val)
    return ()


def _raw_deps(raw: JsonRecord) -> Sequence[JsonValue]:
    val = raw.get("deps", ())
    if isinstance(val, Sequence) and not isinstance(val, str):
        return val
    return ()


def _anim_path(
    para_seq: tuple[str, ...],
    new_edges: Sequence[Sequence[str]],
    raw: JsonRecord,
    var_names: Sequence[str],
) -> AnimPath:
    return AnimPath(
        paragraphs=list(para_seq),
        branch_edges_new=[list(e) for e in new_edges],
        provenance=_provenance_for_vars(_raw_deps(raw), var_names),
    )


def _node_entry(
    n: str,
    data: Mapping[str, JsonValue],
    positions: Mapping[str, tuple[float, float]],
) -> AnimNode:
    x, y = positions.get(n, (0.5, 0.5))
    # id is the program-qualified key ("PROGRAM/PARAGRAPH"); label is just the
    # trailing paragraph segment, kept for readable on-screen display.
    label = n.rsplit("/", 1)[-1]
    return AnimNode(
        id=n,
        label=label,
        x=x,
        y=y,
        kind=str(data.get("kind", "ASSIGN")),
    )


def build_bundle(
    cfgs: Sequence[Cfg],
    path_records: IO[str],
    var_names: Sequence[str],
    speed_ms: int,
    pause_ms: int,
) -> AnimBundle:
    """Build the JSON-serialisable animation bundle.

    Parameters
    ----------
    cfgs:
        Parsed CFG objects (one per program file).
    path_records:
        File-like yielding JSONL lines; only lines with ``"kind": "path"`` are consumed.
    var_names:
        Variable names to track provenance for.
    speed_ms:
        Milliseconds per animation step.
    pause_ms:
        Milliseconds to pause at path boundaries.
    """
    g = paragraph_graph(cfgs)
    node_para = node_paragraph_of(cfgs)
    positions = layered_positions(g)
    raw_paths = _parse_path_records(path_records)
    collapsed = tuple(collapse_path(_raw_nodes(r), node_para) for r in raw_paths)
    new_edges = _derive_branch_edges_new(collapsed, g)
    return AnimBundle(
        nodes=[_node_entry(n, data, positions) for n, data in g.nodes(data=True)],
        edges=[
            AnimEdge(source=u, target=v, kind=str(data.get("kind", "FLOW")))
            for u, v, data in g.edges(data=True)
        ],
        paths=[
            _anim_path(para_seq, new_edges[i], raw_paths[i], var_names)
            for i, para_seq in enumerate(collapsed)
        ],
        vars=list(var_names),
        speed_ms=speed_ms,
        pause_ms=pause_ms,
    )


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------


def render_html(bundle: AnimBundle, output: Path) -> None:
    """Write a self-contained HTML animation file."""
    template = (
        importlib.resources.files("cobble.viz")
        .joinpath("pathwalk_template.html")
        .read_text(encoding="utf-8")
    )
    html = template.replace("{{DATA}}", json.dumps(bundle).replace("</", "<\\/"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Animate CFG path walks with byte provenance strips."
    )
    p.add_argument(
        "--cfg",
        type=Path,
        required=True,
        help="srccfg bundle JSON from cobble-srccfg-build",
    )
    p.add_argument(
        "--paths",
        type=Path,
        required=True,
        help="path records JSONL from cobble-fields-trace --record-paths",
    )
    p.add_argument(
        "--vars",
        type=lambda s: s.split(","),
        default=[],
        metavar="FIELD1,FIELD2",
        help="comma-separated field names to show provenance strips for",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="output HTML file",
    )
    p.add_argument(
        "--speed",
        type=int,
        default=50,
        metavar="MS",
        help="milliseconds per node step (default 50)",
    )
    p.add_argument(
        "--pause",
        type=int,
        default=600,
        metavar="MS",
        help="milliseconds between paths (default 600)",
    )
    return p


def cli() -> int:
    from cobble.cli_logging import configure_cli_logging
    from cobble.dataflow.srccfg.bundle import load_bundle

    configure_cli_logging()
    args = _parser().parse_args()
    bundle_doc = load_bundle(args.cfg)
    with args.paths.open(encoding="utf-8") as f:
        bundle = build_bundle(bundle_doc.cfgs, f, args.vars, args.speed, args.pause)
    render_html(bundle, args.output)
    size_kb = args.output.stat().st_size // 1024
    _LOG.info("written: %s (%d KB)", args.output, size_kb)
    return 0


def main() -> None:
    sys.exit(cli())
