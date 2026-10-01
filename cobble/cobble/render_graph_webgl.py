"""render_graph_webgl.py — render the graph file cobble.build_graph wrote
(--graph) as one self-contained WebGL HTML view beside it, named for the graph
file's stem: out/carddemo.jsonl -> out/carddemo-webgl.html.

The sibling of cobble.render_graph, for a different job: render_graph's
vis-network page is for navigating a graph, this one is for showing a whole
corpus-sized graph to somebody without it crawling. Neither replaces the other
and both read the same graph file -- see knowledge_graph/render_webgl.py for
what the WebGL page does differently and why.

The layout is computed here rather than in the browser, by graphviz's sfdp, so
graphviz has to be installed for this target (and only for this target). It is
the slow part: about a minute for a graph of tens of thousands of nodes.

Invoke as: uv run python -m cobble.render_graph_webgl --graph <file>
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.merge import merge_graph
from cobble.knowledge_graph.render_webgl import render_webgl_html

logger = logging.getLogger(__name__)


def _render(graph_path: Path) -> Path:
    graph = merge_graph(*read_graph(graph_path))
    logger.info(
        "Laying out %d nodes / %d edges with sfdp — this is the slow part",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    positions = sfdp_positions(graph)
    output_path = graph_path.with_name(f"{graph_path.stem}-webgl.html")
    render_webgl_html(
        graph, positions, output_path, title=f"{graph_path.stem} Knowledge Graph"
    )
    logger.info(
        "Rendered %d nodes, %d edges -> %s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        output_path,
    )
    return output_path


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        required=True,
        type=Path,
        help="The graph file cobble-build wrote",
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    if not args.graph.is_file():
        logger.error(
            "error: %s not found — run `cobble-build --output` first", args.graph
        )
        return 1
    _render(args.graph)
    return 0


def main() -> int:
    configure_cli_logging()
    return _run(_parse_args(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
