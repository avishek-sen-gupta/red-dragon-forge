"""What driving the program map in a headless browser found."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapReport:
    """Script errors, the nodes and edges drawn, the pages programs link to, the node a search selected, and where clicking a program went."""

    errors: tuple[str, ...]
    nodes: int
    edges: int
    hrefs: tuple[str, ...]
    searched: str
    clicked: str
