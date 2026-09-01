"""render_graph_webgl.py — render <out_dir>/nodes.jsonl + <out_dir>/edges.jsonl
(produced by cobble.build_graph) as one self-contained WebGL HTML view at
<out_dir>/graph-webgl.html.

The sibling of cobble.render_graph, for a different job: render_graph's
vis-network page is for navigating a graph, this one is for showing a whole
corpus-sized graph to somebody without it crawling. Neither replaces the other
and both read the same NDJSON pair -- see knowledge_graph/render_webgl.py for
what the WebGL page does differently and why.

The layout is computed here rather than in the browser, by graphviz's sfdp, so
graphviz has to be installed for this target (and only for this target). It is
the slow part: about a minute for a graph of tens of thousands of nodes.

out_dir comes from the same --config YAML build_graph.py/generate_sym.py use
(its `corpus.out_dir` field) -- nothing about a specific corpus is hardcoded
here.

Invoke as: uv run python -m cobble.render_graph_webgl --config <path>
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import load_corpus_config
from cobble.knowledge_graph.export import read_ndjson
from cobble.knowledge_graph.layout import sfdp_positions
from cobble.knowledge_graph.merge import merge_graph
from cobble.knowledge_graph.render_webgl import render_webgl_html

logger = logging.getLogger(__name__)


def _render(nodes_jsonl: Path, edges_jsonl: Path, out_dir: Path, stem: str) -> None:
    """Read the NDJSON pair, lay it out, and write the self-contained HTML."""
    graph = merge_graph(*read_ndjson(nodes_jsonl, edges_jsonl))
    logger.info(
        "Laying out %d nodes / %d edges with sfdp — this is the slow part",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    positions = sfdp_positions(graph)
    output_path = out_dir / "graph-webgl.html"
    render_webgl_html(graph, positions, output_path, title=f"{stem} Knowledge Graph")
    logger.info(
        "Rendered %d nodes, %d edges -> %s",
        graph.number_of_nodes(),
        graph.number_of_edges(),
        output_path,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus YAML config (see cobble/corpus_config.py / config/carddemo.yaml)",
    )
    return parser.parse_args()


def main() -> int:
    configure_cli_logging()
    args = _parse_args()
    config = load_corpus_config(args.config)

    nodes_jsonl = config.out_dir / "nodes.jsonl"
    edges_jsonl = config.out_dir / "edges.jsonl"
    if not nodes_jsonl.is_file() or not edges_jsonl.is_file():
        logger.error(
            "error: %s / %s not found — run `make build` first",
            nodes_jsonl,
            edges_jsonl,
        )
        return 1

    _render(nodes_jsonl, edges_jsonl, config.out_dir, args.config.stem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
