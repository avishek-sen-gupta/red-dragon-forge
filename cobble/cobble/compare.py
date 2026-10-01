"""compare.py — identity diff of a graph file (--graph) against reference/graph.jsonl.

Node identity   = (kind, id)
Edge identity   = (source, source_kind, target, target_kind, kind)

Reports missing (in reference, not in out) and extra (in out, not in reference)
for both nodes and edges. Exits nonzero if any diff. Goal: EMPTY diff.

The report is logged rather than printed: the exit code is what a caller acts on,
the text is for whoever is reading, and one stream means the per-set blocks cannot
interleave with a trailing verdict.

Invoke as: uv run python -m cobble.compare --graph <file>
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.knowledge_graph.graph_file import read_graph
from cobble.knowledge_graph.graph_types import GraphEdge, GraphNode

logger = logging.getLogger(__name__)

REFERENCE = Path(__file__).resolve().parent.parent / "reference" / "graph.jsonl"


def _node_identity(node: GraphNode) -> tuple[str, str]:
    return (node.kind.value, node.id)


def _edge_identity(edge: GraphEdge) -> tuple[str, str, str, str, str]:
    return (
        edge.source,
        edge.source_kind.value,
        edge.target,
        edge.target_kind.value,
        edge.kind.value,
    )


def _lines(missing, extra, label, ref, out):
    header = f"=== {label}: {len(out)} out / {len(ref)} reference ==="
    if not missing and not extra:
        return (header, f"  OK — identical ({len(ref)})")
    return (
        header,
        *_side_lines(
            missing, f"MISSING ({len(missing)}) — in reference, not in out", "-"
        ),
        *_side_lines(extra, f"EXTRA ({len(extra)}) — in out, not in reference", "+"),
    )


def _side_lines(keys, heading, marker):
    if not keys:
        return ()
    return (f"  {heading}:", *(f"    {marker} {k}" for k in sorted(map(str, keys))))


def _report(label, ref, out):
    """Log one set's diff and return how many differences it had."""
    missing = ref - out
    extra = out - ref
    logger.info("%s", "\n".join(_lines(missing, extra, label, ref, out)))
    return len(missing) + len(extra)


def _absent_inputs(reference: Path, graph: Path) -> tuple[Path, ...]:
    return tuple(path for path in (reference, graph) if not path.is_file())


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        required=True,
        type=Path,
        help="The graph file cobble-build wrote",
    )
    return parser.parse_args(argv)


def _diff(reference: Path, graph: Path) -> int:
    ref_nodes, ref_edges = read_graph(reference)
    out_nodes, out_edges = read_graph(graph)
    return _report(
        "NODES",
        set(map(_node_identity, ref_nodes)),
        set(map(_node_identity, out_nodes)),
    ) + _report(
        "EDGES",
        set(map(_edge_identity, ref_edges)),
        set(map(_edge_identity, out_edges)),
    )


def _run(args: argparse.Namespace, reference: Path) -> int:
    absent = _absent_inputs(reference, args.graph)
    if absent:
        logger.error(
            "nothing to compare — absent: %s\n"
            "  the graph is produced by:  cobble-build --config config/carddemo.toml --output <file>\n"
            "  the reference is committed — if it is absent, the checkout is incomplete.",
            ", ".join(map(str, absent)),
        )
        return 1
    diff = _diff(reference, args.graph)
    if diff == 0:
        logger.info("\nRESULT: EMPTY DIFF — the graph matches the reference exactly.")
        return 0
    # ERROR, not INFO: a nonzero diff is the failure this script exists to catch.
    logger.error("\nRESULT: %d difference(s).", diff)
    return 1


def main() -> int:
    configure_cli_logging()
    return _run(_parse_args(sys.argv[1:]), REFERENCE)


if __name__ == "__main__":
    sys.exit(main())
