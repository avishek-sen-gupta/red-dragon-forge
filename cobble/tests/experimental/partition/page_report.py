"""What driving the partition page in a headless browser found."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageReport:
    """Script errors, dataset edges drawn before following a dataset, with every dataset's links toggled on, and after following one, the datasets list, what following showed, the followed record layout table row by row, how the nodes and edges outside the followed chain are drawn, the view, headline, labelled nodes and highlighted component size after clicking a field no dataset touches, and a field in no component."""

    errors: tuple[str, ...]
    dataset_edges: int
    visible_before: int
    visible_toggled: int
    rows: tuple[str, ...]
    followed: str
    chain_datasets: tuple[str, ...]
    visible_after: int
    layout: tuple[tuple[str, ...], ...]
    others_shown: int
    other_colours: tuple[str, ...]
    other_edges_shown: int
    field_click: tuple[str, str]
    click_labels: tuple[str, ...]
    highlighted: int
    isolated_click: tuple[str, str]
    searched: str
