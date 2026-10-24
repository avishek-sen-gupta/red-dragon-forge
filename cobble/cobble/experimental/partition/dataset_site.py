"""A file site resolved to the dataset it touches."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.experimental.partition.certainty import Certainty
from cobble.experimental.partition.file_site import FileSite


@dataclass(frozen=True)
class DatasetSite:
    """A file site, the dataset identity it resolved to, how sure that is, and whether it resolved at all (an unresolved site links nothing)."""

    use: FileSite
    identity: str
    certainty: Certainty
    reasons: tuple[str, ...]
    resolved: bool
