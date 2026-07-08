"""Typed AST for IDCAMS LISTCAT (comprehensive grammar).

Field list transcribed verbatim from the design spec's `Listcat` section
(2026-07-08-idcams-comprehensive-grammar-design.md), with one deliberate
deviation: the design spec's `detail` field defaults to `"NAME"`, but --
for consistency with `Print.format` (ast_print.py), which leaves its
optional CHARACTER/DUMP/HEX choice `None` when unspecified rather than
applying the manual's documented default in this parsing-only layer --
`detail` is left `None` here too when no detail-level keyword is present.
A future execution layer should apply the manual's documented default
("NAME") itself.

`entry_types` is NOT a mutual-exclusivity choice group: per the manual,
multiple entry-type filters may be combined in one LISTCAT (e.g.
"LISTCAT ALIAS CLUSTER" lists both alias and cluster entries), so every
occurrence collected by the grammar is appended to the tuple, with no
single-occurrence enforcement in the transformer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name

__all__ = ["Listcat"]

_EntryType = Literal[
    "ALIAS",
    "ALTERNATEINDEX",
    "CLUSTER",
    "DATA",
    "GENERATIONDATAGROUP",
    "INDEX",
    "NONVSAM",
    "PAGESPACE",
    "PATH",
    "USERCATALOG",
]


@dataclass(frozen=True)
class Listcat:
    entry_types: tuple[_EntryType, ...] = ()
    library_entries: str | None = None
    volume_entries: str | None = None
    catalog: str | None = None
    creation_days: int | None = None
    expiration_days: int | None = None
    entries: tuple[Name, ...] = ()  # mutually exclusive with level
    level: str | None = None
    cdilvl: bool | None = None
    prefix: bool | None = None
    detail: Literal["NAME", "HISTORY", "VOLUME", "ALLOCATION", "ALL"] | None = None
    file: str | None = None
    library: str | None = None
    outfile: str | None = None
