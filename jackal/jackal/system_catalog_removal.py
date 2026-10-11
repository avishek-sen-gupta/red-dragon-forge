"""Removing a dataset from the system catalog: a shell call the list.remove rule cannot tell from a list mutation."""

from __future__ import annotations

from jackal.system_catalog import SystemCatalog


def remove_cataloged(system: SystemCatalog, dsn: str) -> None:
    system.remove(dsn)
