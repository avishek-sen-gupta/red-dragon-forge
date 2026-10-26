"""What driving the program map in a headless browser found."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MapReport:
    """Script errors, the nodes and edges drawn, the pages programs link to, the node a search selected, whether dragging a program moved it and whether it moved the camera, whether the drag stayed on the map, and where clicking a program went."""

    errors: tuple[str, ...]
    nodes: int
    edges: int
    hrefs: tuple[str, ...]
    searched: str
    dragged: tuple[bool, bool]
    stayed: bool
    clicked: str
