"""cobble-experimental-codeql-facts: a parsed corpus written as TRAP for a CodeQL database, one file per member."""

import argparse
import logging
import shutil
import sys
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.experimental.codeql.program_rows import program_rows
from cobble.experimental.codeql.trap_row import TrapRow, trap_text
from cobble.matching_files import matching_files
from cobble.parsing.asg_cache import cached_first_program, failure_path

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental: write each parsed member as TRAP in cobol.dbscheme, "
            "and copy its source into the database's source archive."
        )
    )
    parser.add_argument("--config", required=True, type=Path, help="a corpus config")
    parser.add_argument("--trap-dir", required=True, type=Path)
    parser.add_argument("--archive-dir", required=True, type=Path)
    return parser


def _member(config: CorpusConfig, source: Path, trap_dir: Path, archive: Path) -> None:
    if failure_path(config.asg_dir, source).exists():
        logger.info("codeql: skipped %s, which did not parse", source.name)
        return
    path = source.resolve()
    rows = program_rows(cached_first_program(config.asg_dir, source), str(path))
    (trap_dir / f"{source.stem}.trap").write_text(trap_text(rows), encoding="utf-8")
    copy = archive / str(path).lstrip("/")
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, copy)
    logger.info("codeql: %s, %d rows", source.name, len(rows))


def cli(argv: tuple[str, ...] = ()) -> int:
    configure_cli_logging()
    args = _parser().parse_args(argv if argv else None)
    config = load_corpus_config(args.config)
    args.trap_dir.mkdir(parents=True, exist_ok=True)
    sources = matching_files(config.cobol_dir, config.cobol_globs)
    tuple(_member(config, s, args.trap_dir, args.archive_dir) for s in sources)
    prefix = TrapRow("sourceLocationPrefix", (str(config.cobol_dir.resolve()),))
    (args.trap_dir / "prefix.trap").write_text(trap_text((prefix,)), encoding="utf-8")
    return 0


def main() -> int:
    sys.exit(cli())
