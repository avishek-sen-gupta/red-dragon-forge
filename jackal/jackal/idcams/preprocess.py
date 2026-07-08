"""Preprocessing pass for the + (mid-token) continuation character.

IDCAMS's "+" continuation force-joins a value across a record boundary
with zero inserted characters -- this happens before the text ever
reaches the Lark parser, since it collapses two physical lines into one
logical token. "-" continuation (whitespace-equivalent) is handled
separately, at the grammar level, via %ignore.
"""

from __future__ import annotations

import re

_PLUS_CONTINUATION = re.compile(r"\+[ \t]*\r?\n[ \t]*")


def join_plus_continuations(text: str) -> str:
    return _PLUS_CONTINUATION.sub("", text)
