"""Typed AST for IDCAMS DELETE (comprehensive grammar).

Distinct from the existing, execution-wired `jackal.idcams.commands.Delete`
(the older, minimal IDCAMS grammar's own dataclass) -- this module's
`Delete` is a new, separate, much richer shape built for the comprehensive
grammar. Name collision across the two modules is fine; they are never
imported into the same namespace.

Field list and the 13-member EntryType literal transcribed verbatim from
the design spec's `Delete` section
(2026-07-08-idcams-comprehensive-grammar-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jackal.idcams.ast_values import Name

__all__ = ["EntryType", "Delete"]

EntryType = Literal[
    "ALIAS",
    "ALTERNATEINDEX",
    "CLUSTER",
    "GENERATIONDATAGROUP",
    "LIBRARYENTRY",
    "NONVSAM",
    "NVR",
    "PAGESPACE",
    "PATH",
    "TRUENAME",
    "USERCATALOG",
    "VOLUMEENTRY",
    "VVR",
]


@dataclass(frozen=True)
class Delete:
    entries: tuple[Name, ...]  # 1..100 entries
    entry_type: EntryType | None = None
    catalog: str | None = None
    erase: bool | None = None
    file: str | None = None
    force: bool | None = None
    mask: bool | None = None
    no_disconnect: bool = False
    purge: bool | None = None
    recovery: bool | None = None
    scratch: bool | None = None
