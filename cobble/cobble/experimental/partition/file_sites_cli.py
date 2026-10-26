"""cobble-experimental-partition-file-sites: how the partition graph's file sites resolve to datasets, and why the rest do not."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fixpoint.provenance import provenance
from cobble.dataflow.fixpoint.target_site import TargetSite
from cobble.experimental.partition.dataset_resolution import file_sites
from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.file_site_census import file_site_census
from cobble.experimental.partition.knowledge_graph_view import knowledge_graph

logger = logging.getLogger(__name__)

STAGE = "partition file sites"
EXAMPLES = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobble-experimental-partition-file-sites",
        description=(
            "Experimental: the file sites the partition graph resolves to datasets, "
            "by route, and the unresolved ones by the first gap that explains each."
        ),
    )
    parser.add_argument(
        "--fixpoint",
        type=Path,
        required=True,
        help="the out-dir cobble-dataflow-fixpoint wrote",
    )
    parser.add_argument(
        "--knowledge-graph",
        type=Path,
        required=True,
        help="the graph cobble-build wrote",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        required=True,
        help="targets.jsonl from cobble-dataflow-combine",
    )
    return parser


def _targets(path: Path) -> tuple[TargetSite, ...]:
    with path.open(encoding="utf-8") as lines:
        return tuple(
            TargetSite.model_validate_json(line) for line in lines if line.strip()
        )


def _named(site: FileSite) -> str:
    return f"{site.site} {site.file}"


def main(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    logger.info("%s: reading provenance from %s", STAGE, arguments.fixpoint)
    sites = file_sites(tuple(provenance(arguments.fixpoint)))
    found = file_site_census(
        sites, knowledge_graph(arguments.knowledge_graph), _targets(arguments.targets)
    )
    logger.info(
        "%s: %d file sites: %d resolved by a CICS file target, %d by a SELECT, "
        "%d unresolved-file",
        STAGE,
        found.sites,
        found.cics,
        found.batch,
        found.sites - found.cics - found.batch,
    )
    for gap, gapped in found.gaps:
        logger.info(
            "%s: %d unresolved-file sites: %s, e.g. %s",
            STAGE,
            len(gapped),
            gap,
            ", ".join(_named(site) for site in gapped[:EXAMPLES]),
        )
    return 0
