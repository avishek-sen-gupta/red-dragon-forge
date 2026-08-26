"""render_graph.py — render <out_dir>/nodes.jsonl + <out_dir>/edges.jsonl
(produced by cobble.build_graph) as one self-contained interactive HTML
visualization at <out_dir>/graph.html. No server, no CDN: vis-network is
vendored under cobble/knowledge_graph/vendor/ and inlined into the
generated file.

out_dir comes from the same --config YAML build_graph.py/generate_sym.py
use (its `corpus.out_dir` field) -- nothing about a specific corpus is
hardcoded here.

Invoke as: uv run python -m cobble.render_graph --config <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cobble.corpus_config import load_corpus_config
from cobble.knowledge_graph.export import read_ndjson
from cobble.knowledge_graph.merge import merge_graph
from cobble.knowledge_graph.render import render_html


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
    args = _parse_args()
    config = load_corpus_config(args.config)

    nodes_jsonl = config.out_dir / "nodes.jsonl"
    edges_jsonl = config.out_dir / "edges.jsonl"
    if not nodes_jsonl.is_file() or not edges_jsonl.is_file():
        print(
            f"error: {nodes_jsonl} / {edges_jsonl} not found — run `make build` first",
            file=sys.stderr,
        )
        return 1

    nodes, edges = read_ndjson(nodes_jsonl, edges_jsonl)
    graph = merge_graph(nodes, edges)
    output_path = config.out_dir / "graph.html"
    render_html(graph, output_path, title=f"{args.config.stem} Knowledge Graph")
    print(
        f"Rendered {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
