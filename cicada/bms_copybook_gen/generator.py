from __future__ import annotations

from collections.abc import Callable

from .models import BmsField, BmsMap, BmsMapSet

# Column widths for COBOL alignment
_NAME_COL = 47  # column at which PIC clause starts
_PIC_LABEL = "PIC "
_INDENT = 11
_GROUP_INDENT = _INDENT + 4

# Extended-attribute subfields emitted per field when EXTATT is active, in the
# IBM symbolic-map order: Color, programmed-Symbol (PS), Highlight, Validation.
_EXTATT_SUFFIXES = ("C", "P", "H", "V")

FieldLines = Callable[[BmsField, int, bool], tuple[str, ...]]


def _line(indent: int, name: str, pic: str) -> str:
    """Format a single COBOL data item line, aligning PIC clauses."""
    prefix = " " * indent + name
    padding = max(1, _NAME_COL - len(prefix))
    return prefix + " " * padding + _PIC_LABEL + pic + "."


def _data_pic(pic: str, f: BmsField) -> str:
    return pic if pic else f"X({f.length})"


def _extended_lines(indent: int, label: str, extatt: bool) -> tuple[str, ...]:
    return (
        tuple(_line(indent, f"02  {label}{s}", "X") for s in _EXTATT_SUFFIXES)
        if extatt
        else ()
    )


def _field_lines_output_only(f: BmsField, indent: int, extatt: bool) -> tuple[str, ...]:
    return (
        _line(indent, f"02  {f.label}L", "S9(4) COMP"),
        _line(indent, f"02  {f.label}A", "X"),
        " " * indent + f"02  FILLER REDEFINES {f.label}A.",
        _line(indent + 4, f"03  {f.label}F", "X"),
        *_extended_lines(indent, f.label, extatt),
        _line(indent, f"02  {f.label}O", _data_pic(f.picout, f)),
    )


def _field_lines_input(f: BmsField, indent: int, extatt: bool) -> tuple[str, ...]:
    extended = (
        (_line(indent, "02  FILLER", f"X({len(_EXTATT_SUFFIXES)})"),) if extatt else ()
    )
    return (
        _line(indent, f"02  {f.label}L", "S9(4) COMP"),
        _line(indent, f"02  {f.label}F", "X"),
        " " * indent + f"02  FILLER REDEFINES {f.label}F.",
        _line(indent + 4, f"03  {f.label}A", "X"),
        *extended,
        _line(indent, f"02  {f.label}I", _data_pic(f.picin, f)),
    )


def _field_lines_output(f: BmsField, indent: int, extatt: bool) -> tuple[str, ...]:
    return (
        _line(indent, "02  FILLER", "X(3)"),
        *_extended_lines(indent, f.label, extatt),
        _line(indent, f"02  {f.label}O", _data_pic(f.picout, f)),
    )


def _grouped(f: BmsField) -> bool:
    return bool(f.grpname) and f.occurs > 0


def _group_header(fields: tuple[BmsField, ...], index: int) -> tuple[str, ...]:
    f = fields[index]
    first = _grouped(f) and all(p.grpname != f.grpname for p in fields[:index])
    header = " " * _INDENT + f"02  {f.grpname} OCCURS {f.occurs} TIMES."
    return (header,) if first else ()


def _map_lines(
    bmsmap: BmsMap, header: str, tioapfx: bool, field_lines: FieldLines
) -> tuple[str, ...]:
    fields = bmsmap.fields
    prefix = (_line(_INDENT, "02  FILLER", "X(12)"),) if tioapfx else ()
    body = tuple(
        line
        for index, f in enumerate(fields)
        for line in (
            *_group_header(fields, index),
            *field_lines(f, _GROUP_INDENT if _grouped(f) else _INDENT, bmsmap.extatt),
        )
    )
    return (header, *prefix, *body)


def _output_only_lines(mapset: BmsMapSet, bmsmap: BmsMap) -> tuple[str, ...]:
    header = f"       01  {bmsmap.label}O."
    return _map_lines(bmsmap, header, mapset.tioapfx, _field_lines_output_only)


def _input_lines(mapset: BmsMapSet, bmsmap: BmsMap) -> tuple[str, ...]:
    header = f"       01  {bmsmap.label}I."
    return _map_lines(bmsmap, header, mapset.tioapfx, _field_lines_input)


def _output_lines(mapset: BmsMapSet, bmsmap: BmsMap) -> tuple[str, ...]:
    header = f"       01  {bmsmap.label}O REDEFINES {bmsmap.label}I."
    return _map_lines(bmsmap, header, mapset.tioapfx, _field_lines_output)


def _copybook_lines(mapset: BmsMapSet, bmsmap: BmsMap) -> tuple[str, ...]:
    if mapset.mode == "OUT":
        return _output_only_lines(mapset, bmsmap)
    inputs = _input_lines(mapset, bmsmap)
    output = _output_lines(mapset, bmsmap) if mapset.mode == "INOUT" else ()
    return (*inputs, *output)


def generate_copybook(mapset: BmsMapSet) -> tuple[str, ...]:
    return tuple(line for m in mapset.maps for line in _copybook_lines(mapset, m))
