"""CSD parsing — parse_csd (transid -> program) and parse_csd_files
(logical file -> physical DSNAME) plus their Lark grammar/transformer.

Extracted from cics.dispatcher: the CSD parser is a self-contained text/Lark
side-utility of that VM-dispatcher file, sharing nothing with run_cics /
CicsRegion. Lifting it here lets static-analysis consumers (the knowledge-graph
CICS flow builder) use CSD parsing without importing the VM. cics.dispatcher
re-exports both functions for backward compatibility.
"""

from __future__ import annotations

import logging
from pathlib import Path

from lark import Lark, Transformer

logger = logging.getLogger(__name__)


# CSD grammar: a file is a sequence of DEFINE statements, each a kind followed by
# attribute(value) pairs (TRANSACTION(CC00) PROGRAM(COSGN00C) GROUP(CARDDEMO) ...).
# Attributes are order-independent and may span continuation lines (whitespace is
# ignored), so TRANSACTION and PROGRAM need not be adjacent — unlike the old regex.
# An attribute value is anything up to the closing paren (it may contain spaces,
# slashes, dots — e.g. DSNAME(AWS.M2...) or DEFINETIME(22/05/13 12:56:44)).
_CSD_GRAMMAR = r"""
    start: define*
    define: DEFINE_KW attr+
    attr: NAME "(" VALUE? ")"

    DEFINE_KW.2: "DEFINE"i
    NAME: /[A-Za-z][A-Za-z0-9-]*/
    VALUE: /[^()]+/

    %ignore /\s+/
"""

_csd_parser = Lark(_CSD_GRAMMAR, parser="lalr")


class _CsdTransformer(Transformer):
    """Turn the CSD parse tree into a list of {ATTR_NAME: value} dicts, one per DEFINE."""

    def attr(self, items: list) -> tuple[str, str]:
        name = str(items[0]).upper()
        value = str(items[1]).strip() if len(items) > 1 else ""
        return (name, value)

    def define(self, items: list) -> dict[str, str]:
        # items[0] is the DEFINE keyword token; the rest are (name, value) pairs.
        return dict(items[1:])

    def start(self, items: list) -> list[dict[str, str]]:
        return list(items)


def parse_csd(csd_path: Path) -> dict[str, str]:
    """Parse a CSD file to produce a {transid: program_name} mapping.

    Each ``DEFINE`` is parsed structurally into its attribute(value) pairs; a
    ``DEFINE TRANSACTION(t) ... PROGRAM(p)`` (attributes in any order) contributes
    ``{t: p}``. DEFINEs without both TRANSACTION and PROGRAM (e.g. FILE/PROGRAM
    definitions, or a TRANSACTION whose program is defined elsewhere) are skipped.
    """
    content = csd_path.read_text(encoding="utf-8", errors="replace")
    defines = _CsdTransformer().transform(_csd_parser.parse(content))
    result = {}
    for attrs in defines:
        if "TRANSACTION" in attrs and "PROGRAM" in attrs:
            result[attrs["TRANSACTION"].upper()] = attrs["PROGRAM"].upper()
    logger.info("CSD parsed: %d transid→program mappings", len(result))
    return result


def parse_csd_files(csd_path: Path) -> dict[str, str]:
    """Parse a CSD file to produce a {logical file name: physical DSNAME}
    mapping, for the knowledge graph's CICS_FILE -> DATASET edges.

    Each ``DEFINE FILE(name) ... DSNAME(dataset)`` (attributes in any
    order) contributes ``{name: dataset}``. A DEFINE FILE without a
    DSNAME attribute is skipped (no physical dataset to resolve to).
    """
    content = csd_path.read_text(encoding="utf-8", errors="replace")
    defines = _CsdTransformer().transform(_csd_parser.parse(content))
    result = {}
    for attrs in defines:
        if "FILE" in attrs and "DSNAME" in attrs:
            result[attrs["FILE"].upper()] = attrs["DSNAME"].upper()
    logger.info("CSD parsed: %d file→dataset mappings", len(result))
    return result
