"""canonical_export — render a nodes.jsonl + edges.jsonl pair (produced by
cobble.build_graph) as CodeConcise's canonical ingestion manifest.

Every path is explicit -- nothing is derived from a corpus config's out_dir,
so this can run against any nodes/edges pair regardless of which config (if
any) produced them.

Invoke as:
    uv run python -m cobble.canonical_export \\
        --nodes <path/to/nodes.jsonl> --edges <path/to/edges.jsonl> \\
        --output <path/to/manifest.json> --project-name <name>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cobble.knowledge_graph.canonical_export import write_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--nodes",
        required=True,
        type=Path,
        help="Path to a nodes.jsonl file (produced by cobble.build_graph)",
    )
    parser.add_argument(
        "--edges",
        required=True,
        type=Path,
        help="Path to an edges.jsonl file (produced by cobble.build_graph)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the canonical manifest.json to",
    )
    parser.add_argument(
        "--project-name",
        required=True,
        help="Project name recorded in each node's additional_properties",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not args.nodes.is_file() or not args.edges.is_file():
        print(
            f"error: {args.nodes} / {args.edges} not found — run `make build` first",
            file=sys.stderr,
        )
        return 1

    write_manifest(args.nodes, args.edges, args.output, args.project_name)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
