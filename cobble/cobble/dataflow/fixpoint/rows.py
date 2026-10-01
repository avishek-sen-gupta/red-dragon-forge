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


def flag(row: Row, field: str) -> bool:
    """A row's boolean. Only JSON ``true`` reads as true, so a missing or
    misspelled value is the conservative answer instead of a crash."""
    return row.get(field) is True


def strings(row: Row, key: str) -> tuple[str, ...]:
    """A row's list of strings. ``str`` is rejected deliberately: it is itself a
    Sequence, so a scalar written where a list belongs would otherwise read back as
    one entry per character."""
    return tuple(str(one) for one in _sequence(row.get(key)))


def numbers(row: Row, field: str) -> tuple[int, ...]:
    """A row's list of integers -- a column of one, where a table is written as
    arrays parallel to each other rather than as an object per entry."""
    return tuple(int(str(one)) for one in _sequence(row.get(field)))


def flags(row: Row, field: str) -> tuple[bool, ...]:
    """The same for booleans, on the same terms as ``flag``: only JSON ``true``
    reads as true, so a column written with anything else is conservative."""
    return tuple(one is True for one in _sequence(row.get(field)))


def string_lists(row: Row, field: str) -> tuple[tuple[str, ...], ...]:
    """A column whose entries are themselves lists of strings -- a qualification
    path, which has a name per level and is a list for that reason alone."""
    return tuple(
        tuple(str(one) for one in _sequence(entry))
        for entry in _sequence(row.get(field))
    )


def number_lists(row: Row, field: str) -> tuple[tuple[int, ...], ...]:
    """The same for integers -- a subscript per enclosing table."""
    return tuple(
        tuple(int(str(one)) for one in _sequence(entry))
        for entry in _sequence(row.get(field))
    )


def _sequence(value: object) -> Sequence[object]:
    """A JSON array, or nothing where something else was written.

    ``str`` is excluded for the reason ``strings`` gives: it is a Sequence of its
    own characters, and one written where an array belongs would read as a list of
    them rather than as the malformed row it is.
    """
    if isinstance(value, str) or not isinstance(value, Sequence):
        return ()
    return value
