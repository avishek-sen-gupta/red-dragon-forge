"""cobble-experimental-partition-render: a program map of a field graph and one WebGL page per program's neighbourhood."""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import cobble.knowledge_graph
from cobble.cli_logging import configure_cli_logging
from cobble.experimental.partition.graph_file import read_graph
from cobble.experimental.partition.graph_index import GraphIndex, graph_index
from cobble.experimental.partition.neighbourhood import neighbourhood
from cobble.experimental.partition.page import page
from cobble.experimental.partition.program_map import map_page, program_map
from cobble.experimental.partition.tally import RENDER

logger = logging.getLogger(__name__)

VENDOR = Path(cobble.knowledge_graph.__file__).parent / "vendor"
SCRIPTS = (
    VENDOR / "graphology.umd.min.js",
    VENDOR / "sigma.min.js",
    VENDOR / "graphology-library.min.js",
)
SOURCES = tuple(f"scripts/{script.name}" for script in SCRIPTS)
PAGE_SOURCES = tuple(f"../{source}" for source in SOURCES)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-partition-render",
        description="Experimental: a program map of a partition graph and one self-contained WebGL page per program's neighbourhood.",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        required=True,
        help="the graph cobble-experimental-partition-graph wrote",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="the directory to write index.html, programs/ and scripts/ into",
    )
    return parser


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _program_page(out: Path, index: GraphIndex, name: str) -> tuple[int, str]:
    drawn = neighbourhood(index, name)
    _write(out / "programs" / f"{name}.html", page(drawn, PAGE_SOURCES))
    return len(drawn.nodes), name


def _clock_text(seconds: float) -> str:
    hours, within = divmod(int(seconds), 3600)
    minutes, left = divmod(within, 60)
    return f"{hours}h{minutes:02d}m{left:02d}s"


def _noted(
    written: tuple[int, str], number: int, total: int, spent: float
) -> tuple[int, str]:
    logger.info(
        "%s: pages written %d/%d: %s, %d nodes, about %s left",
        RENDER,
        number,
        total,
        written[1],
        written[0],
        _clock_text(spent / number * (total - number)),
    )
    return written


def write_pages(out: Path, index: GraphIndex, clock: Callable[[], float]) -> None:
    names = tuple(index.programs)
    started = clock()
    sizes = tuple(
        _noted(_program_page(out, index, name), number, len(names), clock() - started)
        for number, name in enumerate(names, 1)
    )
    largest = max(sizes, default=(0, ""))
    logger.info(
        "%s: largest neighbourhood %s, %d nodes", RENDER, largest[1], largest[0]
    )


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    out: Path = arguments.out
    logger.info("partition render: reading %s", arguments.graph)
    index = graph_index(read_graph(arguments.graph))
    logger.info(
        "partition render: %d nodes, %d edges, %d programs",
        len(index.nodes),
        len(index.edges),
        len(index.programs),
    )
    _write(out / SOURCES[0], SCRIPTS[0].read_text(encoding="utf-8"))
    _write(out / SOURCES[1], SCRIPTS[1].read_text(encoding="utf-8"))
    _write(out / SOURCES[2], SCRIPTS[2].read_text(encoding="utf-8"))
    _write(out / "index.html", map_page(program_map(index), SOURCES))
    logger.info("partition render: program map -> %s", out / "index.html")
    write_pages(out, index, time.monotonic)
    logger.info("partition render: %d pages -> %s", len(index.programs), out)
    return 0
