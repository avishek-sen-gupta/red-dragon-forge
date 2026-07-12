"""Fitness compare for the CardDemo knowledge graph — identity only.

Node identity = (kind, id); edge identity = (source, source_kind, target,
target_kind, kind). attrs and file_path are excluded (matching the original
compare semantics). write_golden() emits sorted JSONL for clean git diffs.
"""

from __future__ import annotations

import json
from pathlib import Path


def _node_keys(path: Path) -> set[tuple[str, str]]:
    return {
        (r["kind"], r["id"]) for r in map(json.loads, path.read_text().splitlines())
    }


def _edge_keys(path: Path) -> set[tuple]:
    return {
        (r["source"], r["source_kind"], r["target"], r["target_kind"], r["kind"])
        for r in map(json.loads, path.read_text().splitlines())
    }


def identity_diff(nodes_jsonl, edges_jsonl, golden_nodes, golden_edges):
    ours_n, gold_n = _node_keys(nodes_jsonl), _node_keys(golden_nodes)
    ours_e, gold_e = _edge_keys(edges_jsonl), _edge_keys(golden_edges)
    return (
        {"nodes_missing": gold_n - ours_n, "nodes_extra": ours_n - gold_n},
        {"edges_missing": gold_e - ours_e, "edges_extra": ours_e - gold_e},
    )


def write_golden(src_nodes_jsonl, src_edges_jsonl, golden_nodes, golden_edges) -> None:
    """Copy build output into the golden, sorted for stable diffs."""
    for src, dst, keyf in (
        (src_nodes_jsonl, golden_nodes, lambda r: (r["kind"], r["id"])),
        (
            src_edges_jsonl,
            golden_edges,
            lambda r: (
                r["source"],
                r["source_kind"],
                r["target"],
                r["target_kind"],
                r["kind"],
            ),
        ),
    ):
        rows = [json.loads(line) for line in Path(src).read_text().splitlines()]
        rows.sort(key=keyf)
        Path(dst).write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n"
        )
