from .models import BmsField, BmsMap, BmsMapSet


def _parse_attrb(raw: str) -> list[str]:
    """Parse ATTRB value: '(UNPROT,IC)' -> ['UNPROT','IC'], 'PROT' -> ['PROT']"""
    raw = raw.strip()
    if raw.startswith("(") and raw.endswith(")"):
        return [s.strip() for s in raw[1:-1].split(",")]
    return [raw]


def _strip_quotes(value: str) -> str:
    """Remove surrounding single quotes from PICIN/PICOUT values."""
    value = value.strip()
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def parse_mapsets(invocations: list[dict]) -> list[BmsMapSet]:
    mapsets: list[BmsMapSet] = []
    current_mapset: BmsMapSet | None = None
    current_map: BmsMap | None = None

    for inv in invocations:
        name = inv.get("name", "")
        args = inv.get("args", {})
        label = inv.get("label", "")

        if name == "DFHMSD":
            if args.get("TYPE") == "FINAL":
                if current_mapset is not None:
                    mapsets.append(current_mapset)
                current_mapset = None
                current_map = None
            else:
                current_mapset = BmsMapSet(
                    label=label,
                    lang=args.get("LANG", "COBOL"),
                    mode=args.get("MODE", "INOUT"),
                    tioapfx=args.get("TIOAPFX", "NO").upper() == "YES",
                    extatt=args.get("EXTATT", "NO").upper() in ("YES", "MAPONLY"),
                )

        elif name == "DFHMDI" and current_mapset is not None:
            # Extended attributes are enabled by the mapset (DFHMSD EXTATT=YES) or
            # per-map on the DFHMDI via DSATTS/MAPATTS=(COLOR,HILIGHT,PS,VALIDN).
            extatt = (
                current_mapset.extatt or "DSATTS" in args or "MAPATTS" in args
            )
            current_map = BmsMap(label=label, extatt=extatt)
            current_mapset.maps.append(current_map)

        elif name == "DFHMDF" and current_map is not None:
            if not label:
                continue
            current_map.fields.append(
                BmsField(
                    label=label,
                    length=int(args.get("LENGTH", 0)),
                    attrb=_parse_attrb(args["ATTRB"]) if "ATTRB" in args else [],
                    picin=_strip_quotes(args["PICIN"]) if "PICIN" in args else None,
                    picout=_strip_quotes(args["PICOUT"]) if "PICOUT" in args else None,
                    grpname=args.get("GRPNAME"),
                    occurs=int(args["OCCURS"]) if "OCCURS" in args else None,
                )
            )

    return mapsets
