"""cobble-experimental-codeql-schema: cobol.dbscheme and the QL classes over it, generated from the parser's types."""

import argparse
import sys
from pathlib import Path

from cobble.experimental.codeql.schema.cobol_schema import cobol_schema
from cobble.experimental.codeql.schema.dbscheme import dbscheme_text
from cobble.experimental.codeql.schema.preamble import PREAMBLE
from cobble.experimental.codeql.schema.ql import ql_text


def generated() -> tuple[str, str]:
    """The dbscheme and the QL classes, as the committed files should hold them."""
    schema = cobol_schema()
    return dbscheme_text(schema, PREAMBLE), ql_text(schema)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Experimental: write cobol.dbscheme and the QL classes over its tables, "
            "both generated from the parser's types."
        )
    )
    parser.add_argument("--dbscheme", required=True, type=Path)
    parser.add_argument("--ql", required=True, type=Path)
    return parser


def cli(argv: tuple[str, ...] = ()) -> int:
    args = _parser().parse_args(argv if argv else None)
    dbscheme, ql = generated()
    args.dbscheme.write_text(dbscheme, encoding="utf-8")
    args.ql.write_text(ql, encoding="utf-8")
    return 0


def main() -> int:
    sys.exit(cli())
