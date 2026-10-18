"""One-off diagnostic: how large is each program's largest control-flow cycle, as the fixpoint walks it."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import networkx as nx
from cobble.dataflow.fixpoint.fallthrough import fallthroughs_pruned
from cobble.dataflow.fixpoint.fixpoint import _entry_node, with_unmodelled
from cobble.dataflow.srccfg.build import paragraph_order
from cobble.dataflow.srccfg.conditions import condition_index
from cobble.dataflow.srccfg.program import program_cfg
from cobble.dataflow.srccfg.statements import statement_index
from cobble.parsing.asg_cache import cached_first_program

logger = logging.getLogger("cycle_sizes")

USAGE = """\
Run from the forge checkout's cobble/ directory:

    uv run --no-sync python scripts/cycle_sizes.py --asg-dir <the ASG cache>

Builds each member's pruned CFG as cobble-dataflow-fixpoint does, keeps what is
reachable from the entry, and splits it into strongly connected components. No
fixpoint runs. Programs are numbered, never named, in the log and in --out; the
number-to-member map goes to --names, which stays on the machine.
"""


@dataclass(frozen=True)
class CycleRow:
    """One program's reachable size and the sizes of its cycles."""

    program: str
    nodes: int
    reachable: int
    cycles: int
    in_cycles: int
    largest_cycle: int
    largest_share: float
    next_largest: tuple[int, ...]


def _reached(path: Path) -> tuple[int, nx.DiGraph]:
    asg = cached_first_program(path.parent, path)
    unpruned = program_cfg(asg)
    statements = with_unmodelled(statement_index(asg), unpruned, condition_index(asg))
    cfg = fallthroughs_pruned(unpruned, paragraph_order(asg), statements)
    graph = nx.DiGraph()
    graph.add_nodes_from(node.id for node in cfg.nodes)
    graph.add_edges_from((edge.source, edge.target) for edge in cfg.edges)
    entry = _entry_node(asg)
    keep = {entry} | nx.descendants(graph, entry) if entry in graph else set()
    return len(cfg.nodes), graph.subgraph(keep)


def _cycle_sizes(reached: nx.DiGraph) -> tuple[int, ...]:
    return tuple(
        sorted(
            (
                len(component)
                for component in nx.strongly_connected_components(reached)
                if len(component) > 1
                or any(reached.has_edge(node, node) for node in component)
            ),
            reverse=True,
        )
    )


def measured(tag: str, path: Path) -> CycleRow:
    nodes, reached = _reached(path)
    sizes = _cycle_sizes(reached)
    largest = sizes[0] if sizes else 0
    reachable = reached.number_of_nodes()
    row = CycleRow(
        program=tag,
        nodes=nodes,
        reachable=reachable,
        cycles=len(sizes),
        in_cycles=sum(sizes),
        largest_cycle=largest,
        largest_share=round(largest / reachable, 3) if reachable else 0.0,
        next_largest=sizes[1:4],
    )
    logger.info("%s %s", tag, asdict(row))
    return row


def _line(row: CycleRow) -> str:
    return (
        f"{row.program:8} {row.nodes:6} {row.reachable:6} {row.cycles:6} "
        f"{row.largest_cycle:7} {row.largest_share:6}  {list(row.next_largest)}"
    )


def summary(rows: Sequence[CycleRow]) -> str:
    shares = sorted(row.largest_share for row in rows)
    if not shares:
        return "no programs measured\n"
    largest = tuple(
        row
        for _reach, _tag, row in sorted(
            (-one.reachable, one.program, one) for one in rows
        )
    )[:20]
    return "\n".join(
        (
            f"{len(rows)} programs measured",
            "largest-cycle share of reachable nodes: "
            f"median {shares[len(shares) // 2]}, "
            f"90th pct {shares[int(len(shares) * 0.9)]}, max {shares[-1]}",
            "",
            "20 largest programs by reachable nodes:",
            f"{'program':8} {'nodes':>6} {'reach':>6} {'cycles':>6} "
            f"{'largest':>7} {'share':>6}  next",
            *(_line(row) for row in largest),
            "",
        )
    )


def _parsed() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--asg-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("cycles.jsonl"))
    parser.add_argument("--names", type=Path, default=Path("cycle-names.txt"))
    return parser.parse_args()


def _members(asg_dir: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in asg_dir.glob("*.json")
            if not path.name.endswith(".failed.json")
        )
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arguments = _parsed()
    paths = _members(arguments.asg_dir)
    tags = tuple(f"P{number:04d}" for number in range(1, len(paths) + 1))
    arguments.names.write_text(
        "".join(f"{tag}\t{path.stem}\n" for tag, path in zip(tags, paths, strict=True)),
        encoding="utf-8",
    )
    rows = tuple(measured(tag, path) for tag, path in zip(tags, paths, strict=True))
    arguments.out.write_text(
        "".join(json.dumps(asdict(row)) + "\n" for row in rows), encoding="utf-8"
    )
    sys.stdout.write(summary(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
