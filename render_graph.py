"""render_graph.py — render out/nodes.jsonl + out/edges.jsonl (produced by
build_port.py) as one self-contained interactive HTML visualization at
out/graph.html. No server, no CDN: vis-network is vendored under
cobble/knowledge_graph/vendor/ and inlined into the generated file.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cobble.knowledge_graph.export import read_ndjson
from cobble.knowledge_graph.merge import merge_graph
from cobble.knowledge_graph.render import render_html

_HERE = Path(__file__).resolve().parent
_OUT_DIR = _HERE / "out"


def main() -> int:
    nodes_jsonl = _OUT_DIR / "nodes.jsonl"
    edges_jsonl = _OUT_DIR / "edges.jsonl"
    if not nodes_jsonl.is_file() or not edges_jsonl.is_file():
        print(
            f"error: {nodes_jsonl} / {edges_jsonl} not found — run `make build` first",
            file=sys.stderr,
        )
        return 1

    nodes, edges = read_ndjson(nodes_jsonl, edges_jsonl)
    graph = merge_graph(nodes, edges)
    output_path = _OUT_DIR / "graph.html"
    render_html(graph, output_path, title="CardDemo Knowledge Graph")
    print(
        f"Rendered {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
