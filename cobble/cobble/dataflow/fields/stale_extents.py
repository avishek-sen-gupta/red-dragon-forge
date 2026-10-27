"""An extents table written before a column the reader now needs."""

from __future__ import annotations


class StaleExtents(ValueError):
    """A row has cells but lacks a column this version writes; rerun cobble-extents."""
