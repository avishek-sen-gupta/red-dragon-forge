#!/usr/bin/env python3
"""Stage-0: GENERATE a synthetic CSD for a corpus that arrived without one.

A CSD is an export of a running CICS region. When a corpus is handed over
without it, build_graph skips the CICS flow stage outright (`csd_files` is
empty), so every CICS member goes unparsed and every literal LINK/XCTL edge is
missing from the graph -- the extractor for those edges exists, it just never
gets a worklist.

This reconstructs the transaction definitions from the members themselves:
literal transaction ids in the source, placed on members by the corpus's own
naming convention, which the config supplies as `transid_rules`. Everything it
cannot establish comes out marked synthetic or reported, never guessed -- see
cobble/cics/synth_csd.py for what each tier of evidence means.

Writes <out_dir>/synthetic.csd. Point the config's `csd_files` at it to use it,
which keeps the generated file an explicit input to the next run rather than
something build_graph silently picks up.

Invoke as: uv run python -m cobble.generate_csd --config <path>
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Mapping
from pathlib import Path

from cobble.cics.synth_csd import (
    SynthesisedCsd,
    render_csd,
    report_lines,
    synthesise_csd,
)
from cobble.cli_logging import configure_cli_logging
from cobble.corpus_config import CorpusConfig, load_corpus_config
from cobble.matching_files import matching_files

logger = logging.getLogger(__name__)

CSD_NAME = "synthetic.csd"


def _members(config: CorpusConfig) -> Mapping[str, bytes]:
    """Every COBOL member the corpus config selects, keyed by file stem.

    The stem is what build_graph resolves a CICS program by; synthesise_csd
    upper-cases it, which is the form the rest of the run compares against.
    """
    return {
        path.stem: path.read_bytes()
        for path in matching_files(config.cobol_dir, config.cobol_globs)
    }


def synthesise_from_corpus(config: CorpusConfig) -> SynthesisedCsd:
    return synthesise_csd(_members(config), config.transid_rules)


def csd_target(config: CorpusConfig) -> Path:
    return config.out_dir / CSD_NAME


def write_csd(csd: SynthesisedCsd, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_csd(csd), encoding="utf-8")
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a corpus TOML config (see cobble/corpus_config.py / config/carddemo.toml)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=f"Where to write the CSD (default: <out_dir>/{CSD_NAME})",
    )
    return parser.parse_args()


def _warn_if_no_convention(config: CorpusConfig) -> None:
    """No convention is workable, but it is worth saying out loud.

    Every CICS member still reaches the flow stage's worklist under a synthetic
    transid, so the LINK/XCTL edges are recovered either way -- what is lost is
    every TRANSACTION node and every STARTS edge.
    """
    if not config.transid_rules:
        logger.warning(
            "no transid_rules configured: every CICS member gets a synthetic "
            "transid, so the graph will hold no TRANSACTION nodes"
        )


def main() -> int:
    configure_cli_logging()
    args = _parse_args()
    config = load_corpus_config(args.config)
    _warn_if_no_convention(config)
    csd = synthesise_from_corpus(config)
    target = write_csd(csd, args.out or csd_target(config))
    logger.info("%s", "\n".join(report_lines(csd)))
    logger.info("wrote %s -- add it to the config's csd_files to use it", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
