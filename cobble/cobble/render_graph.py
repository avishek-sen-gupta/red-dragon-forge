"""render_graph.py — render the graph file cobble.build_graph wrote (--graph)
as one self-contained interactive HTML visualization beside it, named for the
graph file's stem: out/carddemo.jsonl -> out/carddemo.html. No server, no CDN:
vis-network is vendored under cobble/knowledge_graph/vendor/ and inlined into
the generated file.

Invoke as: uv run python -m cobble.render_graph --graph <file>
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.merge import merge_graph
from cobble.knowledge_graph.render import render_html

logger = logging.getLogger(__name__)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        required=True,
        type=Path,
        help="The graph file cobble-build wrote",
    )
    return parser.parse_args(argv)


def _render(graph_path: Path) -> Path:
    graph = merge_graph(*read_graph(graph_path))
    output_path = graph_path.with_suffix(".html")
    render_html(graph, output_path, title=f"{graph_path.stem} Knowledge Graph")
    logger.info(
        "Rendered %d nodes, %d edges -> %s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        output_path,
    )
    return output_path


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
