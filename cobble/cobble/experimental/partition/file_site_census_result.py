"""File sites counted by how each resolved to a dataset, or why it did not."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.partition.file_site import FileSite
from cobble.experimental.partition.file_site_gap import FileSiteGap


@dataclass(frozen=True)
class FileSiteCensus:
    """Every file site, those a CICS file target or a SELECT resolved, and the unresolved ones under the first gap that explains each."""

    sites: int
    cics: int
    batch: int
    gaps: tuple[tuple[FileSiteGap, tuple[FileSite, ...]], ...]
