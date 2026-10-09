"""render_graph_webgl.py — render the graph file cobble.build_graph wrote
(--graph) as one self-contained WebGL HTML view, named for the graph file's
stem and written beside it by default: out/carddemo.jsonl ->
out/carddemo-webgl.html. Pass --out to write it somewhere else instead.

The sibling of cobble.render_graph, for a different job: render_graph's
vis-network page is for navigating a graph, this one is for showing a whole
corpus-sized graph to somebody without it crawling. Neither replaces the other
and both read the same graph file -- see knowledge_graph/render_webgl.py for
what the WebGL page does differently and why.

The layout is computed here rather than in the browser, by graphviz's sfdp, so
graphviz has to be installed for this target (and only for this target). It is
the slow part: about a minute for a graph of tens of thousands of nodes.

Invoke as: uv run python -m cobble.render_graph_webgl --graph <file> [--out <file>]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.merge import merge_graph
from cobble.knowledge_graph.render_webgl import render_webgl_html
from cobble.path_utils import ensure_parent

logger = logging.getLogger(__name__)


def _beside(graph_path: Path) -> Path:
    return graph_path.with_name(f"{graph_path.stem}-webgl.html")


def _given(text: str) -> Callable[[Path], Path]:
    return partial(_as_given, Path(text))


def _as_given(output_path: Path, graph_path: Path) -> Path:
    return output_path


def _render(graph_path: Path, output_path: Path) -> Path:
    graph = merge_graph(*read_graph(graph_path))
    logger.info(
        "Laying out %d nodes / %d edges with sfdp — this is the slow part",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    positions = sfdp_positions(graph)
    render_webgl_html(
        graph,
        positions,
        ensure_parent(output_path),
        title=f"{graph_path.stem} Knowledge Graph",
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
    parser.add_argument(
        "--out",
        type=_given,
        default=_beside,
        help="Output .html file, its directory made if missing "
        "(default: <graph stem>-webgl.html beside --graph)",
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    if not args.graph.is_file():
        logger.error(
            "error: %s not found — run `cobble-build --output` first", args.graph
        )
        return 1
    _render(args.graph, args.out(args.graph))
    return 0


def main() -> int:
    configure_cli_logging()
    return _run(_parse_args(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
