from dataclasses import dataclass, field


@dataclass
class BmsField:
    label: str
    length: int
    attrb: list[str] = field(default_factory=list)
    picin: str | None = None
    picout: str | None = None
    grpname: str | None = None
    occurs: int | None = None


@dataclass
class BmsMap:
    label: str
    extatt: bool = False
    fields: list[BmsField] = field(default_factory=list)


@dataclass
class BmsMapSet:
    label: str
    lang: str
    mode: str
    tioapfx: bool
    extatt: bool = False
    maps: list[BmsMap] = field(default_factory=list)
