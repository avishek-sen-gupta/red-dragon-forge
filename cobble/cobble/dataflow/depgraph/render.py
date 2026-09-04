"""render.py — the variable dependency graph as one self-contained WebGL page.

    uv run cobble-depgraph-render --config config/depgraph.local.toml  # --min-degree 2
                                                                      # to thin it

Reads graph_dir/nodes.jsonl + graph_dir/pairs.json and writes
graph_dir/depgraph-webgl.html. pairs.json rather than edges.jsonl: 412k edge rows
collapse to 176k distinct pairs, and the same pair seen in ten programs is one
arrow on a page, drawn once.

Reuses the corpus graph's renderer wholesale -- sfdp for the layout, sigma.js for
the page -- because the reason that page exists (a corpus-sized graph shown all at
once, positions precomputed, no simulation in the browser) is exactly the problem
here at 120,738 nodes and 176,364 edges.

Its kinds, though, are this graph's own and not NodeKind/EdgeKind: a node is a
COBOL variable, and the useful thing to colour it by is WHERE IT IS DECLARED,
which is the first question anyone asks of a name. WORKING-STORAGE is the corpus's
scratch and its copybook-borne records both; FILE is a VSAM/QSAM record area;
LINKAGE is a commarea, so a LINKAGE node is a program boundary; <undeclared> is a
name the layout pass never saw a declaration for, which is worth seeing as its own
colour rather than hidden among the rest.

Five kinds are not variables at all but the external objects the verb table names
-- DATASET, MAP, PROGRAM, TSQUEUE, TRANSID (see flows.py). They are the ends of
the graph: a chain that starts at a DATASET and finishes at a MAP is a field read
off a file and put on a screen, which is the sentence the whole thing exists to
produce.

Edges are coloured by the verb that made them, in families: MOVE, arithmetic,
string handling, batch file I/O, CALL, and EXEC CICS.

Scale note: sfdp at this size takes minutes and the page is ~10 MB. --min-degree
exists for when that is not what you want -- 66,508 of the nodes have degree 1,
so --min-degree 2 halves the graph without touching anything that carries traffic.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import Path
from types import MappingProxyType

import networkx as nx

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.depgraph.config import DepgraphConfig, load_depgraph_config
from cobble.dataflow.depgraph.flows import VERB_LABELS
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.render_webgl import render_webgl_html

logger = logging.getLogger(__name__)

HTML_NAME = "depgraph-webgl.html"


class VariableKind(Enum):
    """Where a variable is declared, or which external object a node is.

    The section name verbatim, so a section one corpus has and another does not shows
    up as itself instead of as an "other". The last five are build.py's
    IDENTITY_SECTIONS: not declarations at all, but the datasets, maps, programs,
    queues and transactions the verb table names.
    """

    WORKING_STORAGE = "WORKING-STORAGE"
    FILE = "FILE"
    LINKAGE = "LINKAGE"
    LOCAL_STORAGE = "LOCAL-STORAGE"
    UNDECLARED = "<undeclared>"
    DATASET = "DATASET"
    MAP = "MAP"
    PROGRAM = "PROGRAM"
    TSQUEUE = "TSQUEUE"
    TRANSID = "TRANSID"


# Every verb an edge can carry, straight off the verb table, so the legend cannot
# fall behind flows.py. A dynamic Enum because the alternative is this list written
# out twice.
FlowKind = Enum("FlowKind", {label: label for label in sorted(VERB_LABELS)})


# Chosen so the kinds that mark a boundary read loudest: the five external kinds,
# then LINKAGE (a commarea, so another program is on the far side) and FILE (a
# record area, so a dataset is). WORKING-STORAGE is 87% of the nodes and takes the
# quiet blue.
NODE_PALETTE: Mapping[str, str] = MappingProxyType(
    {
        VariableKind.WORKING_STORAGE.value: "#4C72B0",
        VariableKind.FILE.value: "#DD8452",
        VariableKind.LINKAGE.value: "#C44E52",
        VariableKind.LOCAL_STORAGE.value: "#8172B2",
        VariableKind.UNDECLARED.value: "#999999",
        VariableKind.DATASET.value: "#8C564B",
        VariableKind.MAP.value: "#E377C2",
        VariableKind.PROGRAM.value: "#D62728",
        VariableKind.TSQUEUE.value: "#17BECF",
        VariableKind.TRANSID.value: "#BCBD22",
    }
)

# One colour per family rather than per verb: 27 verbs is more swatches than anyone
# reads, and the question an edge's colour answers is "what kind of statement moved
# this", not which spelling of it.
_EDGE_FAMILIES: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"MOVE", "MOVE_CORRESPONDING"}), "#55A868"),
    (
        frozenset(
            {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE", "ADD_CORRESPONDING"}
        ),
        "#8172B2",
    ),
    (frozenset({"STRING", "UNSTRING", "INSPECT", "SET", "SEARCH"}), "#64B5CD"),
    (frozenset({"READ", "WRITE", "REWRITE", "XML_GENERATE"}), "#DD8452"),
    (frozenset({"CALL"}), "#C44E52"),
)
_CICS_EDGE_COLOR = "#4C72B0"
_OTHER_EDGE_COLOR = "#999999"


def _edge_color(verb: str) -> str:
    for verbs, color in _EDGE_FAMILIES:
        if verb in verbs:
            return color
    return _CICS_EDGE_COLOR if verb.startswith("CICS_") else _OTHER_EDGE_COLOR


EDGE_PALETTE: Mapping[str, str] = MappingProxyType(
    {verb: _edge_color(verb) for verb in sorted(VERB_LABELS)}
)


def _kind_of(section: str) -> VariableKind:
    """The section string as a kind, unknown sections landing in UNDECLARED.

    A section cobble has not seen before is a rendering question, not a reason to
    fail a render: it gets the grey that says "nothing known about this one".
    """
    try:
        return VariableKind(section)
    except ValueError:
        return VariableKind.UNDECLARED


def _dominant_verb(pair: dict) -> str:
    """The verb an arrow is coloured by: the one that moved this pair most often.

    Ties break on the verb name so a rerun over the same data draws the same
    colours. A pair moved by four MOVEs and one COMPUTE is a MOVE on the page; the
    full breakdown stays in pairs.json for anyone who needs it.
    """
    verbs = pair.get("verbs") or {}
    if not verbs:
        return "MOVE"
    return max(verbs.items(), key=lambda kv: (kv[1], kv[0]))[0]


def build_graph(
    nodes: Iterable[dict], pairs: list[dict], min_degree: int = 1
) -> nx.MultiDiGraph:
    """The nodes.jsonl/pairs.json pair as the graph the renderer draws.

    Keyed (kind, name) like the corpus graph, so sfdp_positions and
    render_webgl_html index it unchanged. A pair naming a variable that nodes.jsonl
    has no row for cannot happen -- build.py writes both from the same edge list --
    so it raises here rather than being papered over with a synthesised node.
    """
    degree: Counter = Counter()
    for pair in pairs:
        degree[pair["src"]] += 1
        degree[pair["dst"]] += 1
    keep = {name for name, d in degree.items() if d >= min_degree}

    graph = nx.MultiDiGraph()
    key_of: dict[str, tuple[VariableKind, str]] = {}
    for node in nodes:
        name = node["name"]
        if name not in keep:
            continue
        kind = _kind_of(node["section"])
        key = (kind, name)
        key_of[name] = key
        graph.add_node(key, kind=kind, id=name)

    for pair in pairs:
        src, dst = pair["src"], pair["dst"]
        if src not in keep or dst not in keep:
            continue
        graph.add_edge(key_of[src], key_of[dst], kind=FlowKind[_dominant_verb(pair)])
    return graph


def read_nodes(path: Path) -> list[dict]:
    """nodes.jsonl, one object per line. A blank trailing line is not a node."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def render(config: DepgraphConfig, min_degree: int) -> Path:
    nodes = read_nodes(config.graph_dir / "nodes.jsonl")
    pairs = json.loads((config.graph_dir / "pairs.json").read_text())
    logger.info("read %d nodes, %d distinct pairs", len(nodes), len(pairs))

    graph = build_graph(nodes, pairs, min_degree)
    logger.info(
        "laying out %d nodes / %d edges with sfdp -- this is the slow part",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    positions = sfdp_positions(graph)

    output = config.graph_dir / HTML_NAME
    render_webgl_html(
        graph,
        positions,
        output,
        title=f"{config.graph_dir.name} variable dependencies",
        node_palette=NODE_PALETTE,
        edge_palette=EDGE_PALETTE,
    )
    logger.info(
        "rendered %d nodes, %d edges -> %s (%.1f MB)",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        output,
        output.stat().st_size / 1e6,
    )
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a depgraph TOML config (see cobble/dataflow/depgraph/config.py)",
    )
    parser.add_argument(
        "--min-degree",
        type=int,
        default=1,
        help="Drop variables with fewer than this many edges (default: 1, keep all)",
    )
    return parser.parse_args()


def main() -> int:
    configure_cli_logging()
    args = _parse_args()
    config = load_depgraph_config(args.config)
    for name in ("nodes.jsonl", "pairs.json"):
        if not (config.graph_dir / name).is_file():
            logger.error(
                "error: %s not found -- run cobble-depgraph first",
                config.graph_dir / name,
            )
            return 1
    render(config, args.min_degree)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
