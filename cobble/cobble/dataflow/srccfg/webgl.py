"""webgl.py -- a source CFG as one self-contained WebGL page.

    uv run cobble-srccfg-webgl --cfg out-<corpus>-srccfg/MEMBER.jsonl \
                               --output MEMBER-webgl.html   # --program MEMBER
                                                            # for one member of it

The sibling of dot.py, and the only target that shows a whole closure. graphviz's
`dot` is a layered layout with crossing minimisation, and on a closure it does not
finish: a 6,638-node / 9,468-edge bundle ran past twelve minutes and was killed,
where sfdp lays the same graph out in about five seconds. Per program `dot` is fine
and its picture is the better one -- ranked top to bottom, edges labelled -- so
neither target replaces the other.

Reuses the corpus graph's renderer wholesale, sfdp for the layout and sigma.js for
the page, exactly as depgraph/render.py does and for the same reason: the positions
are computed once here, so the browser opens an arranged graph and simulates nothing.

The graph itself comes from joined.py and the node text from presentation.py, shared
with dot.py so the two pictures cannot label a node differently, and so a traversal
crosses a call exactly where the picture draws it. Colour does not: dot.py's
fills are pale graphviz pastels chosen to hold black text inside a shape, and an
#ffffff node is invisible on this page's white background.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

import networkx as nx
from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.srccfg.bundle import load_bundle
from cobble.dataflow.srccfg.cfg import Cfg, EdgeKind, NodeKind
from cobble.dataflow.srccfg.joined import CallKind, graph_of
from cobble.dataflow.srccfg.link import BundleCall
from cobble.knowledge_graph.drawn_node import DrawnNode
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.render_webgl import render_webgl_html

logger = logging.getLogger(__name__)

Layout = Callable[[nx.MultiDiGraph], Mapping[DrawnNode, tuple[float, float]]]


# Where the branches are is what a reader looks for first, so TEST takes the loudest
# colour and CALL -- the other place control leaves the statement it is on -- the
# next. NOP is plumbing a query walks through and takes the grey that says so.
NODE_PALETTE: Mapping[str, str] = MappingProxyType(
    {
        NodeKind.TEST.value: "#DD8452",
        NodeKind.CALL.value: "#C44E52",
        NodeKind.ASSIGN.value: "#4C72B0",
        NodeKind.LABEL.value: "#55A868",
        NodeKind.NOP.value: "#999999",
    }
)

# TRUE green and FALSE red, because which way a condition went is the question the
# picture exists to answer. FLOW and FALLTHRU are the overwhelming majority and take
# the grey that lets the rest be seen.
EDGE_PALETTE: Mapping[str, str] = MappingProxyType(
    {
        EdgeKind.TRUE.value: "#2E7D32",
        EdgeKind.FALSE.value: "#C62828",
        EdgeKind.GOTO.value: "#8172B2",
        EdgeKind.PERFORM.value: "#4C72B0",
        EdgeKind.RETURN.value: "#64B5CD",
        EdgeKind.FLOW.value: "#BBBBBB",
        EdgeKind.FALLTHRU.value: "#DDDDDD",
        CallKind.CALL.value: "#EF6C00",
        CallKind.CALL_CANDIDATE.value: "#9E9E9E",
    }
)


def selected(cfgs: Sequence[Cfg], program: str) -> tuple[Cfg, ...]:
    """The whole bundle, or the one program named. Empty when that name is not here."""
    return tuple(cfg for cfg in cfgs if not program or cfg.program == program)


def render(
    cfgs: Sequence[Cfg],
    output: Path,
    *,
    title: str,
    calls: Sequence[BundleCall] = (),
    layout: Layout = sfdp_positions,
) -> Path:
    """Lay the bundle out and write the page. ``layout`` is a seam for the tests.

    The default is the only one a person wants -- sfdp is what makes a closure-sized
    graph drawable at all -- but it needs graphviz on PATH, which a unit test asking
    "is the page self-contained" has no business needing.
    """
    graph = graph_of(cfgs, calls)
    logger.info(
        "laying out %d nodes / %d edges -- this is the slow part",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    render_webgl_html(
        graph,
        layout(graph),
        output,
        title=title,
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a source CFG as one self-contained WebGL page."
    )
    parser.add_argument("--cfg", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--program",
        default="",
        help="draw only this member of the closure (default: all of it)",
    )
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    bundle = load_bundle(arguments.cfg)
    cfgs = selected(bundle.cfgs, arguments.program)
    if not cfgs:
        logger.error(
            "%s holds no program %s -- nothing to draw",
            arguments.cfg,
            arguments.program,
        )
        return 1
    render(
        cfgs,
        arguments.output,
        title=f"{arguments.cfg.stem} source CFG",
        calls=bundle.calls,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
