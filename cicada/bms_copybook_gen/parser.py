"""hlasm_export macro invocations -> the BMS source model."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from .models import BmsField, BmsMap, BmsMapSet

RawInvocation = Mapping[str, "str | Mapping[str, str] | None"]
Segment = tuple[RawInvocation, Sequence[RawInvocation]]

_PAIR = re.compile(r"\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_DEFAULT_SIZE = (24, 80)


def parse_attrb(raw: str) -> tuple[str, ...]:
    """'(UNPROT,IC)' -> ('UNPROT', 'IC'); 'PROT' -> ('PROT',); '' -> ()."""
    parts = raw.strip().strip("()").split(",")
    return tuple(part.strip() for part in parts if part.strip())


def strip_quotes(value: str) -> str:
    stripped = value.strip()
    quoted = len(stripped) >= 2 and stripped[0] == stripped[-1] == "'"
    return stripped[1:-1] if quoted else stripped


def _text(inv: RawInvocation, key: str) -> str:
    value = inv.get(key)
    return value if isinstance(value, str) else ""


def _args(inv: RawInvocation) -> Mapping[str, str]:
    value = inv.get("args")
    return value if isinstance(value, Mapping) else {}


def _pair(raw: str) -> tuple[int, int] | tuple[()]:
    match = _PAIR.match(raw)
    return (int(match.group(1)), int(match.group(2))) if match else ()


def _size(raw: str) -> tuple[int, int]:
    pair = _pair(raw)
    return pair if pair else _DEFAULT_SIZE


def _position(raw: str, cols: int) -> tuple[int, int]:
    """POS is (line,column), or a zero-based offset into the screen buffer."""
    pair = _pair(raw)
    offset = int(raw) if raw.strip().isdigit() else 0
    return pair if pair else (offset // cols + 1, offset % cols + 1)


def _initial(args: Mapping[str, str]) -> str:
    return strip_quotes(args.get("INITIAL", "")).replace("''", "'")


def _field(inv: RawInvocation, cols: int) -> BmsField:
    args = _args(inv)
    row, col = _position(args.get("POS", ""), cols)
    return BmsField(
        label=_text(inv, "label"),
        length=int(args.get("LENGTH", "0")),
        row=row,
        col=col,
        initial=_initial(args),
        attrb=parse_attrb(args.get("ATTRB", "")),
        color=args.get("COLOR", ""),
        hilight=args.get("HILIGHT", ""),
        picin=strip_quotes(args.get("PICIN", "")),
        picout=strip_quotes(args.get("PICOUT", "")),
        grpname=args.get("GRPNAME", ""),
        occurs=int(args.get("OCCURS", "0")),
    )


def _ends(indices: tuple[int, ...], total: int) -> tuple[int, ...]:
    return (*indices[1:], total) if indices else ()


def _segments(
    invocations: Sequence[RawInvocation], starts: Callable[[RawInvocation], bool]
) -> tuple[Segment, ...]:
    """Each invocation ``starts`` accepts, with everything up to the next one."""
    indices = tuple(i for i, inv in enumerate(invocations) if starts(inv))
    ends = _ends(indices, len(invocations))
    return tuple(
        (invocations[s], invocations[s + 1 : e])
        for s, e in zip(indices, ends, strict=True)
    )


def _is_mapset(inv: RawInvocation) -> bool:
    return _text(inv, "name") == "DFHMSD" and _args(inv).get("TYPE") != "FINAL"


def _is_map(inv: RawInvocation) -> bool:
    return _text(inv, "name") == "DFHMDI"


def _map(segment: Segment, mapset_args: Mapping[str, str], extatt: bool) -> BmsMap:
    mdi, body = segment
    args = _args(mdi)
    size = _size(args.get("SIZE", ""))
    return BmsMap(
        label=_text(mdi, "label"),
        # Extended attributes come from the mapset (EXTATT=YES) or per map via
        # DSATTS/MAPATTS=(COLOR,HILIGHT,PS,VALIDN).
        extatt=extatt or "DSATTS" in args or "MAPATTS" in args,
        size=size,
        ctrl=parse_attrb(args.get("CTRL", mapset_args.get("CTRL", ""))),
        elements=tuple(
            _field(inv, size[1]) for inv in body if _text(inv, "name") == "DFHMDF"
        ),
    )


def _mapset(segment: Segment) -> BmsMapSet:
    msd, body = segment
    args = _args(msd)
    extatt = args.get("EXTATT", "NO").upper() in ("YES", "MAPONLY")
    return BmsMapSet(
        label=_text(msd, "label"),
        lang=args.get("LANG", "COBOL"),
        mode=args.get("MODE", "INOUT"),
        tioapfx=args.get("TIOAPFX", "NO").upper() == "YES",
        extatt=extatt,
        maps=tuple(_map(s, args, extatt) for s in _segments(body, _is_map)),
    )


def parse_mapsets(invocations: Sequence[RawInvocation]) -> tuple[BmsMapSet, ...]:
    return tuple(_mapset(s) for s in _segments(invocations, _is_mapset))
