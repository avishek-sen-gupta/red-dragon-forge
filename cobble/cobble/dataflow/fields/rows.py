"""The JSONL boundary: one artefact line, and typed reads out of it.

``json.loads`` returns whatever the file held, so ``object`` is the only honest
annotation for a row's values -- a recursive ``str | int | Sequence[Json] | ...``
alias names the same ignorance in more words and buys no check a reader can rely
on. That annotation is confined here, to a module whose whole job is to turn it
into the ``str``, ``int`` and ``tuple[str, ...]`` the queries work in. Nothing
above this line ever holds a value of unknown type.

Every read has a default rather than raising. A malformed row is one field the
artefact cannot answer for; refusing the directory would cost the corpus's whole
worth of query for it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

Row = Mapping[str, object]


def read(path: Path) -> tuple[Row, ...]:
    """Every line of a table, or nothing if the build did not write it."""
    if not path.is_file():
        return ()
    return tuple(
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    )


def text(row: Row, key: str, default: str = "") -> str:
    value = row.get(key)
    return default if value is None else str(value)


def number(row: Row, key: str, default: int = 0) -> int:
    value = row.get(key)
    return default if value is None else int(str(value))


def nested(row: Row, key: str) -> Row:
    """A row inside a row -- ``attrs``. Something else written there reads as an
    empty row, so a caller asking for its keys gets the defaults."""
    value = row.get(key)
    return value if isinstance(value, Mapping) else {}


def strings(row: Row, key: str) -> tuple[str, ...]:
    """A row's list of strings. ``str`` is rejected deliberately: it is itself a
    Sequence, so a scalar written where a list belongs would otherwise read back as
    one entry per character."""
    value = row.get(key)
    if isinstance(value, str) or not isinstance(value, Sequence):
        return ()
    return tuple(str(one) for one in value)
