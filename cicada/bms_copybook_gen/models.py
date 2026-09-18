"""The BMS source model: mapsets, maps, and every DFHMDF in declaration order.

Unlabelled DFHMDFs are screen captions. They have no symbolic-map storage, so
``BmsMap.fields`` -- what the copybook generator and flow analysis read -- leaves
them out, while ``BmsMap.elements`` keeps them for anything that draws the screen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BmsField:
    label: str
    length: int
    row: int = 1
    col: int = 1
    initial: str = ""
    attrb: tuple[str, ...] = ()
    color: str = ""
    hilight: str = ""
    picin: str = ""
    picout: str = ""
    grpname: str = ""
    occurs: int = 0


@dataclass(frozen=True)
class BmsMap:
    label: str
    extatt: bool = False
    size: tuple[int, int] = (24, 80)
    ctrl: tuple[str, ...] = ()
    elements: tuple[BmsField, ...] = ()

    @property
    def fields(self) -> tuple[BmsField, ...]:
        return tuple(element for element in self.elements if element.label)


@dataclass(frozen=True)
class BmsMapSet:
    label: str
    lang: str
    mode: str
    tioapfx: bool
    extatt: bool = False
    maps: tuple[BmsMap, ...] = ()
