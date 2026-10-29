"""CLI: write one cobble run directory as Souffle facts and the schema declaring them."""

import argparse
import logging
import sys
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.experimental.datalog.facts_writer import write_facts
from cobble.experimental.datalog.missing_artifact import MissingArtifactError
from cobble.experimental.datalog.run_facts import run_facts

logger = logging.getLogger(__name__)

MISSING_ARTIFACT = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a run as Souffle facts.")
    parser.add_argument("--run", required=True, type=Path, help="a cobble run dir")
    parser.add_argument("--out", required=True, type=Path, help="the facts dir")
    return parser


def cli(argv: tuple[str, ...] = ()) -> int:
    configure_cli_logging()
    args = _parser().parse_args(argv if argv else None)
    try:
        facts = run_facts(args.run)
    except MissingArtifactError as error:
        logger.error("datalog: !! %s", error)
        return MISSING_ARTIFACT
    write_facts(args.out, facts)
    logger.info("datalog: %d relations -> %s", len(facts), args.out)
    return 0


def main() -> int:
    sys.exit(cli())
