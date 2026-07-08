"""Typed AST for IDCAMS DEFINE PATH (comprehensive grammar).

DEFINE PATH creates a path entry over a base cluster or alternate index.
Like DEFINE GENERATIONDATAGROUP/NONVSAM, no DATA(...)/INDEX(...) trailers
and no mutually-exclusive-choice groups.

Field list transcribed verbatim from the design spec's `DefinePath`
section (2026-07-08-idcams-comprehensive-grammar-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from jackal.idcams.ast_values import Name, Retention

__all__ = ["DefinePath"]


@dataclass(frozen=True)
class DefinePath:
    name: Name
    path_entry: Name
    catalog: str | None = None
    model: tuple[Name, Name | None] | None = None
    owner: str | None = None
    recatalog: bool | None = None
    retention: Retention | None = None
    update: bool | None = None  # UPDATE | NOUPDATE
