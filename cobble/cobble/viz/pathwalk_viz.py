"""cobble-viz-pathwalk: paragraph-level data layer for CFG path animation.

Every node and edge drawn comes from the sampled paths themselves
(``--record-paths``). The sampler already walked the program and recorded
exactly what it visited; this module extracts exactly that, nothing more.
There is no static full-program graph construction, no topological sort,
and no cycle detection anywhere in this module: a recorded walk has no
cycles to detect, only revisits, and revisiting a node during animation is
just stepping to it again.

Node positions are not computed here at all -- the browser lays the graph
out itself via a d3-force simulation (see ``pathwalk_template.html``),
which spreads a real CFG's shape out organically far better than any
depth-layered grid this module could compute.
"""

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

from cobble.dataflow.srccfg.cfg import Cfg

_LOG = logging.getLogger(__name__)

# A JSON-safe value: scalar, sequence, or string-keyed mapping thereof.
JsonValue = str | int | float | bool | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
JsonRecord = Mapping[str, JsonValue]


# ---------------------------------------------------------------------------
# Bundle output types
# ---------------------------------------------------------------------------


class AnimNode(TypedDict):
    """One paragraph node in the animation graph.

    No position is carried here -- the browser lays the graph out itself
    via a force simulation (see ``pathwalk_template.html``), which spreads
    nodes far more organically than any position this module could compute.
    """

    id: str
    label: str


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
# Edge kind lookup
# ---------------------------------------------------------------------------


def _edge_kind_lookup(
    cfgs: Sequence[Cfg], node_para: Mapping[str, str]
) -> dict[tuple[str, str], str]:
    """(src_para, tgt_para) -> the first-seen edge kind connecting them.

    Built once from every CFG's own edges, resolved via ``node_para`` (never
    by splitting an edge endpoint's id string -- see ``node_paragraph_of``).
    Used only to label an edge a sampled path actually took with its real
    kind (PERFORM/RETURN/FALLTHRU/...); this is a lookup, not a graph --
    nothing here is drawn or laid out from it beyond what a path visited.
    """
    triples = (
        (
            node_para.get(edge.source, ""),
            node_para.get(edge.target, ""),
            edge.kind.value,
        )
        for cfg in cfgs
        for edge in cfg.edges
    )
    valid = (t for t in triples if t[0] and t[1] and t[0] != t[1])
    return reduce(
        lambda acc, t: acc if (t[0], t[1]) in acc else {**acc, (t[0], t[1]): t[2]},
        valid,
        {},
    )


# ---------------------------------------------------------------------------
# Nodes, edges, and layout -- all derived from the sampled paths
# ---------------------------------------------------------------------------


def _paths_nodes(paths: Sequence[tuple[str, ...]]) -> tuple[str, ...]:
    """Every paragraph key appearing in any sampled path, in first-seen order.

    Only paragraphs a sampled walk actually visited are drawn -- a paragraph
    the sampler never reached (dead code, or a coverage gap) has nothing
    recorded to animate and is left off the graph entirely.
    """
    all_paras = (para for path in paths for para in path)
    return reduce(lambda acc, para: acc if para in acc else (*acc, para), all_paras, ())


def _paths_edges(paths: Sequence[tuple[str, ...]]) -> tuple[tuple[str, str], ...]:
    """Every consecutive (src, tgt) pair actually observed across all sampled
    paths, in first-seen order.

    This -- not a full static CFG -- is the edge set drawn: only an edge a
    sampled walk actually took is ever shown.
    """
    all_pairs = ((path[i], path[i + 1]) for path in paths for i in range(len(path) - 1))
    valid_pairs = (pair for pair in all_pairs if pair[0] != pair[1])
    return reduce(
        lambda acc, pair: acc if pair in acc else (*acc, pair), valid_pairs, ()
    )


# ---------------------------------------------------------------------------
# _derive_branch_edges_new
# ---------------------------------------------------------------------------
def _path_edges(path: tuple[str, ...]) -> frozenset[tuple[str, str]]:
    return frozenset(
        (path[i], path[i + 1]) for i in range(len(path) - 1) if path[i] != path[i + 1]
    )


def _new_edges_step(
    acc: tuple[frozenset[tuple[str, str]], tuple[list[list[str]], ...]],
    path: tuple[str, ...],
) -> tuple[frozenset[tuple[str, str]], tuple[list[list[str]], ...]]:
    covered, result = acc
    newly = _path_edges(path) - covered
    return (covered | newly, (*result, sorted([list(e) for e in newly])))


def _derive_branch_edges_new(
    paths: Sequence[tuple[str, ...]],
) -> tuple[list[list[str]], ...]:
    """Which edges each path covers for the first time, in path order.

    The coverage this drives measures progress through revealing everything
    ``--record-paths`` captured -- not independent CFG coverage. Whether the
    sampler covered the *real* CFG is fields-trace's own reported statistic
    (its ``N/M branches`` line), computed against the static CFG it walked;
    this bundle only ever knows the paths it was handed.
    """
    _, result = reduce(_new_edges_step, paths, (frozenset(), ()))
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


def _node_entry(n: str) -> AnimNode:
    # id is the qualified key ("PROGRAM/PARAGRAPH"); label is just the
    # trailing paragraph segment, kept for readable on-screen display.
    label = n.rsplit("/", 1)[-1]
    return AnimNode(id=n, label=label)


def build_bundle(
    cfgs: Sequence[Cfg],
    path_records: IO[str],
    var_names: Sequence[str],
    speed_ms: int,
    pause_ms: int,
) -> AnimBundle:
    """Build the JSON-serialisable animation bundle.

    Every node and edge comes from the recorded paths themselves --
    ``cfgs`` is consulted only to resolve a path's raw node ids to
    paragraph keys and to look up an edge's real kind for display; it
    never contributes a node or edge the paths did not themselves visit.
    No position is computed here at all: the browser lays the graph out
    itself via a force simulation (see ``pathwalk_template.html``).

    Parameters
    ----------
    cfgs:
        Parsed CFG objects (one per program file) -- consulted only for
        node-id resolution and edge-kind lookup, never for graph or layout.
    path_records:
        File-like yielding JSONL lines; only lines with ``"kind": "path"`` are consumed.
    var_names:
        Variable names to track provenance for.
    speed_ms:
        Milliseconds per animation step.
    pause_ms:
        Milliseconds to pause at path boundaries.
    """
    node_para = node_paragraph_of(cfgs)
    raw_paths = _parse_path_records(path_records)
    collapsed = tuple(collapse_path(_raw_nodes(r), node_para) for r in raw_paths)

    nodes_seq = _paths_nodes(collapsed)
    edges_seq = _paths_edges(collapsed)
    kind_lookup = _edge_kind_lookup(cfgs, node_para)
    new_edges = _derive_branch_edges_new(collapsed)

    return AnimBundle(
        nodes=[_node_entry(n) for n in nodes_seq],
        edges=[
            AnimEdge(source=s, target=t, kind=kind_lookup.get((s, t), "FLOW"))
            for s, t in edges_seq
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
    """Write the HTML animation file. Loads d3-force from a CDN at view
    time for the layout simulation; not self-contained offline."""
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
