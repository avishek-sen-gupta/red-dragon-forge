"""canonical_export — render <out_dir>/nodes.jsonl + <out_dir>/edges.jsonl
(produced by cobble.build_graph) as CodeConcise's canonical ingestion
manifest at <out_dir>/manifest.json.

out_dir comes from the same --config YAML build_graph.py/render_graph.py
use (its `corpus.out_dir` field) -- nothing about a specific corpus is
hardcoded here.

Invoke as: uv run python -m cobble.canonical_export --config <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cobble.corpus_config import load_corpus_config
from cobble.knowledge_graph.canonical_export import write_manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, type=Path,
        help="Path to a corpus YAML config (see cobble/corpus_config.py / config/carddemo.yaml)",
    )
    parser.add_argument(
        "--project-name", default=None,
        help="Defaults to the --config file's stem, e.g. 'carddemo' for config/carddemo.yaml",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_corpus_config(args.config)
    project_name = args.project_name or args.config.stem

    nodes_jsonl = config.out_dir / "nodes.jsonl"
    edges_jsonl = config.out_dir / "edges.jsonl"
    output_path = config.out_dir / "manifest.json"

    if not nodes_jsonl.is_file() or not edges_jsonl.is_file():
        print(
            f"error: {nodes_jsonl} / {edges_jsonl} not found — run `make build` first",
            file=sys.stderr,
        )
        return 1

    write_manifest(nodes_jsonl, edges_jsonl, output_path, project_name)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
