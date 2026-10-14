"""A path: the name a program opens to read a cluster through one of its alternate indexes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogPath:
    dsn: str
    aix: str
