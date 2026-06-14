"""
squall.parser._grammar
~~~~~~~~~~~~~~~~~~~~~~
Loads the EXEC SQL Lark grammar and exposes a single ``parse`` function.

Design constraints
------------------
* No mutable globals except the Lark singleton (created once at import time).
* Parser: Earley with dynamic lexer and ambiguity=resolve so every keyword can
  also appear as a plain word inside opaque ``_run`` / ``_run_i`` bodies.
"""

from __future__ import annotations

from importlib.resources import files
from typing import Final

from lark import Lark, Tree

# ── Grammar source ────────────────────────────────────────────────────────────

_GRAMMAR_TEXT: Final[str] = (
    files("squall.parser").joinpath("grammar.lark").read_text(encoding="utf-8")
)

# ── Parser singleton (immutable after creation) ───────────────────────────────

_PARSER: Final[Lark] = Lark(
    _GRAMMAR_TEXT,
    parser="earley",
    lexer="dynamic",
    ambiguity="resolve",
)


# ── Public API ────────────────────────────────────────────────────────────────


def parse(text: str) -> Tree:
    """Parse a single EXEC SQL body (everything between EXEC SQL … END-EXEC).

    Parameters
    ----------
    text:
        The SQL body text, *without* the ``EXEC SQL`` / ``END-EXEC`` delimiters.

    Returns
    -------
    lark.Tree
        The parse tree rooted at ``start``.  The first child is the matched
        directive node (e.g. ``select_into``, ``insert``, …).
    """
    return _PARSER.parse(text.strip())
