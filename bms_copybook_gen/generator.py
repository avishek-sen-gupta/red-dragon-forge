from .models import BmsField, BmsMap, BmsMapSet

# Column widths for COBOL alignment
_NAME_COL = 47  # column at which PIC clause starts
_PIC_LABEL = "PIC "


def _line(indent: int, name: str, pic: str) -> str:
    """Format a single COBOL data item line, aligning PIC clauses."""
    prefix = " " * indent + name
    padding = max(1, _NAME_COL - len(prefix))
    return prefix + " " * padding + _PIC_LABEL + pic + "."


# Extended-attribute subfields emitted per field when EXTATT is active, in the
# IBM symbolic-map order: Color, programmed-Symbol (PS), Highlight, Validation.
_EXTATT_SUFFIXES = ("C", "P", "H", "V")


def _field_lines_output(f: BmsField, indent: int, extatt: bool = False) -> list[str]:
    data_pic = f.picout if f.picout else f"X({f.length})"
    lines = [
        _line(indent, f"02  {f.label}L", "S9(4) COMP"),
        _line(indent, f"02  {f.label}A", "X"),
        " " * indent + f"02  FILLER REDEFINES {f.label}A.",
        _line(indent + 4, f"03  {f.label}F", "X"),
    ]
    if extatt:
        # One named byte per extended attribute (EXTATT=YES): <f>C/<f>P/<f>H/<f>V.
        lines.extend(_line(indent, f"02  {f.label}{s}", "X") for s in _EXTATT_SUFFIXES)
    lines.append(_line(indent, f"02  {f.label}O", data_pic))
    return lines


def _field_lines_input(f: BmsField, indent: int, extatt: bool = False) -> list[str]:
    data_pic = f.picin if f.picin else f"X({f.length})"
    # Mirror the output field's byte layout (length halfword + attribute byte +
    # [extended-attribute bytes when EXTATT] + data) with anonymous FILLER. The
    # output map's "FILLER REDEFINES <f>A / 03 <f>F" adds no bytes, so a single
    # FILLER X for the attribute byte keeps the input redefinition byte-aligned.
    # (The previous "FILLER REDEFINES FILLER" was invalid COBOL — REDEFINES
    # requires a data-name, not FILLER.)
    lines = [
        _line(indent, "02  FILLER", "S9(4) COMP"),
        _line(indent, "02  FILLER", "X"),
    ]
    if extatt:
        lines.append(_line(indent, "02  FILLER", f"X({len(_EXTATT_SUFFIXES)})"))
    lines.append(_line(indent, f"02  {f.label}I", data_pic))
    return lines


def _map_output_lines(bmsmap: BmsMap, tioapfx: bool) -> list[str]:
    lines = [f"       01  {bmsmap.label}O."]
    indent = 11
    if tioapfx:
        lines.append(_line(indent, "02  FILLER", "X(12)"))

    seen_groups: set[str] = set()
    for f in bmsmap.fields:
        if f.grpname and f.occurs:
            if f.grpname not in seen_groups:
                seen_groups.add(f.grpname)
                grp_prefix = " " * indent + f"02  {f.grpname} OCCURS {f.occurs} TIMES."
                lines.append(grp_prefix)
            lines.extend(_field_lines_output(f, indent + 4, bmsmap.extatt))
        else:
            lines.extend(_field_lines_output(f, indent, bmsmap.extatt))
    return lines


def _map_input_lines(bmsmap: BmsMap, output_name: str, tioapfx: bool) -> list[str]:
    lines = [f"       01  {bmsmap.label}I REDEFINES {output_name}."]
    indent = 11
    if tioapfx:
        lines.append(_line(indent, "02  FILLER", "X(12)"))

    seen_groups: set[str] = set()
    for f in bmsmap.fields:
        if f.grpname and f.occurs:
            if f.grpname not in seen_groups:
                seen_groups.add(f.grpname)
                lines.append(" " * indent + f"02  {f.grpname} OCCURS {f.occurs} TIMES.")
            lines.extend(_field_lines_input(f, indent + 4, bmsmap.extatt))
        else:
            lines.extend(_field_lines_input(f, indent, bmsmap.extatt))
    return lines


def generate_copybook(mapset: BmsMapSet) -> list[str]:
    lines: list[str] = []
    for bmsmap in mapset.maps:
        if mapset.mode in ("OUT", "INOUT"):
            lines.extend(_map_output_lines(bmsmap, mapset.tioapfx))
        if mapset.mode in ("IN", "INOUT"):
            output_name = f"{bmsmap.label}O"
            lines.extend(_map_input_lines(bmsmap, output_name, mapset.tioapfx))
    return lines
