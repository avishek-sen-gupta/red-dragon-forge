"""AttrValue -- what a node or edge attribute may hold: whatever the graph file can carry."""

from collections.abc import Mapping, Sequence

from typing_extensions import TypeAliasType

AttrValue = TypeAliasType(
    "AttrValue",
    str | int | float | bool | Sequence["AttrValue"] | Mapping[str, "AttrValue"],
)
