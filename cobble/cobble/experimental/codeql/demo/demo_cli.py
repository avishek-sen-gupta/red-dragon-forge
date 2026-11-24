"""cobble-experimental-codeql-demo: the demo pack's results, decoded to JSON, drawn as one WebGL page."""

import argparse
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import networkx as nx
from cobble.cli_logging import configure_cli_logging
from cobble.experimental.codeql.demo.graph import control_graph, with_flows
from cobble.experimental.codeql.demo.palette import EDGE_PALETTE, NODE_PALETTE
from cobble.experimental.codeql.demo.results import load_results
from cobble.knowledge_graph.drawn_node import DrawnNode
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.render_webgl import render_webgl_html

logger = logging.getLogger(__name__)

Layout = Callable[[nx.MultiDiGraph], Mapping[DrawnNode, tuple[float, float]]]


def render(results_dir: Path, output: Path, layout: Layout = sfdp_positions) -> Path:
    results = load_results(results_dir)
    control = control_graph(results)
    logger.info(
        "laying out %d nodes / %d edges of control flow",
        control.number_of_nodes(),
        control.number_of_edges(),
    )
    drawn = with_flows(control, results)
    render_webgl_html(
        drawn,
        layout(control),
        output,
        title="CodeQL control flow and dataflow",
        node_palette=NODE_PALETTE,
        edge_palette=EDGE_PALETTE,
    )
    logger.info(
        "rendered %d flow steps -> %s",
        drawn.number_of_edges() - control.number_of_edges(),
        output,
    )
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental: draw CodeQL's control-flow graph and the demo queries' "
            "dataflow paths as one WebGL page."
        )
    )
    parser.add_argument(
        "--results",
        required=True,
        type=Path,
        help="the demo pack's results, decoded with `codeql bqrs decode --format=json`",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(list(argv) if argv else sys.argv[1:])
    render(arguments.results, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
