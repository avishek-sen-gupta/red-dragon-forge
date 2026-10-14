"""catnip's command line: install a data declaration into a system directory."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from catnip.declaration import load_declaration
from catnip.declaration_error import DeclarationError
from catnip.install import install
from catnip.system_catalog import SystemCatalog

logger = logging.getLogger(__name__)


def run(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="catnip")
    sub = parser.add_subparsers(dest="cmd", required=True)
    installing = sub.add_parser("install", help="install a data declaration")
    installing.add_argument("declaration", type=Path)
    installing.add_argument("--system", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        install(load_declaration(args.declaration), SystemCatalog(args.system))
    except DeclarationError as error:
        logger.error("%s", error)
        return 1
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return run(sys.argv[1:])
