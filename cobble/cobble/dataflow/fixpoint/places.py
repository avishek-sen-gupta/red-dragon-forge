"""Where each node of a prepared program sits in its source, kept from the load for reports."""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from dataclasses import dataclass

from cobble.dataflow.srccfg.cfg import Cfg


@dataclass(frozen=True)
class Places:
    """Per node in graph order, its paragraph (an index into ``paragraphs``) and its
    first source line; and the transfer of each call site. Arrays of ints, so a
    worker holding thousands of programs holds a few bytes a node for this."""

    paragraphs: tuple[str, ...]
    paragraph_at: array[int]
    line_at: array[int]
    transfers: tuple[tuple[str, str], ...]

    def at(self, position: int) -> str:
        return (
            f"{self.paragraphs[self.paragraph_at[position]]}"
            f" line {self.line_at[position]}"
        )

    def transfer(self, node: str) -> str:
        return dict(self.transfers)[node]


def places_of(cfg: Cfg, sites: tuple[str, ...]) -> Places:
    """The source place of every node, in ``cfg.nodes`` order, and the transfer at each site."""
    paragraphs = tuple(sorted({node.paragraph for node in cfg.nodes}))
    rank: Mapping[str, int] = {name: at for at, name in enumerate(paragraphs)}
    return Places(
        paragraphs=paragraphs,
        paragraph_at=array("I", (rank[node.paragraph] for node in cfg.nodes)),
        line_at=array("I", (node.span.line_start for node in cfg.nodes)),
        transfers=tuple(
            (node, cfg.node(node).transfer.removeprefix("CICS_")) for node in sites
        ),
    )
