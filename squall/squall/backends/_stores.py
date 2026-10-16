"""A SqlBackend implementation's writes into state it alone owns.

``SqliteBackend``/``Db2Backend`` each hold one mutable ``_cursors`` dict —
cursor name -> the live driver cursor/statement — for their own instance's
lifetime. A later ``fetch``/``close`` call reads that same dict back by
name, so a rebuilt copy assigned over it would go unseen by those calls.
This is a leaf module because ``.importlinter``'s
``parser-backends-independence`` contract forbids ``squall.backends`` from
importing anything under ``squall.parser`` — even transitively.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


def set_cursor(cursors: MutableMapping[K, V], name: K, value: V) -> None:
    """Set ``cursors[name] = value`` in place — see the module docstring."""
    cursors[name] = value
