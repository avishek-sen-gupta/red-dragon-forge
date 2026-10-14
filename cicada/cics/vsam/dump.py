"""Copybook-driven decoder/dumper for cataloged VSAM datasets.

Reads a cataloged dataset's fixed-length-record file (see cics/vsam/format.py)
and decodes each record field-by-field using a COBOL record layout parsed from a
copybook, emitting JSON-lines (default) or a human-readable block format.

Pure orchestration over existing primitives: build_data_layout (copybook ->
DataLayout) and the COBOL pure decoders. No new decode logic, no new format.

CLI entrypoint::

    python -m cics.vsam.dump \\
        --system <system-dir> --dsn <dsn> --copybook <copybook> \\
        [--record NAME] [--format jsonl|block] [--jar PATH]

``--jar`` defaults to ``$PROLEAP_BRIDGE_JAR`` when the env var is set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from catnip.dataset import Dataset
from catnip.system_catalog import NotCataloged, SystemCatalog
from cics.vsam.decoded_record import Decoded, DecodedRecord, Leaf
from cics.vsam.format import read_flat_file
from interpreter.cobol.binary import decode_binary
from interpreter.cobol.comp3 import decode_comp3
from cobol_asg.cobol_parser import ProLeapCobolParser
from cobol_asg.cobol_types import CobolDataCategory
from interpreter.cobol.data_layout import DataLayout, FieldLayout, build_data_layout
from interpreter.cobol.ebcdic_table import EbcdicTable
from cobol_asg.subprocess_runner import RealSubprocessRunner
from interpreter.cobol.zoned_decimal import decode_zoned


def _decode_leaf(field: FieldLayout, data: bytes) -> Leaf:
    """Decode the bytes of one elementary field to a Python value.

    ``data`` must be exactly the field's bytes. Numeric fields with no implied
    decimals decode to int (matching the engine, red-dragon-4q25.42); fields with
    decimals decode to float. Alphanumeric fields decode EBCDIC -> ASCII text with
    trailing spaces trimmed.
    """
    td = field.type_descriptor
    cat = td.category
    if cat == CobolDataCategory.ALPHANUMERIC:
        return (
            EbcdicTable.ebcdic_to_ascii(data)
            .decode("ascii", errors="replace")
            .rstrip(" ")
        )
    if cat == CobolDataCategory.ZONED_DECIMAL:
        return _as_number(decode_zoned(data, td.decimal_digits), td.decimal_digits)
    if cat == CobolDataCategory.COMP3:
        return _as_number(decode_comp3(data, td.decimal_digits), td.decimal_digits)
    if cat == CobolDataCategory.BINARY:
        return _as_number(
            decode_binary(data, td.decimal_digits, td.signed), td.decimal_digits
        )
    raise NotImplementedError(
        f"VSAM dump does not support category {cat.value} (field {field.name!r})"
    )


def _as_number(value: float, decimal_digits: int) -> int | float:
    return int(round(value)) if decimal_digits == 0 else value


def decode_record(layout: DataLayout, record: bytes) -> DecodedRecord:
    """Decode one record's bytes field by field, per the DataLayout.

    Groups nest; OCCURS items become tuples, OCCURS DEPENDING ON honouring its
    counter clamped to [occurs_min or 1, occurs_count]. Offsets are rebased to
    the layout's own offset, so a sub-01 selected from a multi-01 copybook
    slices from the record's start.
    """
    return _decoded(layout, record, layout.offset, layout)


def _decoded(
    layout: DataLayout, record: bytes, base: int, root: DataLayout
) -> DecodedRecord:
    return DecodedRecord(
        (
            *(
                (name, _decode_field(fl, record, base, root))
                for name, fl in layout.fields.items()
            ),
            *(
                (name, _decode_group(sub, record, base, root))
                for name, sub in layout.groups.items()
            ),
        )
    )


def _occurs_floor(field: FieldLayout) -> int:
    return max(field.occurs_min, 1)


def _counted(field: FieldLayout, record: bytes, base: int, root: DataLayout) -> int:
    match root.lookup(field.occurs_depending_on):
        case FieldLayout() as counter:
            start = counter.offset - base
            live = int(
                _decode_leaf(counter, record[start : start + counter.byte_length])
            )
            return max(_occurs_floor(field), min(live, field.occurs_count))
        case _:
            return field.occurs_count


def _live_count(field: FieldLayout, record: bytes, base: int, root: DataLayout) -> int:
    if not field.occurs_depending_on:
        return field.occurs_count
    return _counted(field, record, base, root)


def _element(fl: FieldLayout, record: bytes, base: int, index: int) -> Leaf:
    start = fl.offset - base + index * fl.element_size
    return _decode_leaf(fl, record[start : start + fl.byte_length])


def _decode_field(
    fl: FieldLayout, record: bytes, base: int, root: DataLayout
) -> Leaf | tuple[Leaf, ...]:
    if fl.occurs_count > 0:
        count = _live_count(fl, record, base, root)
        return tuple(_element(fl, record, base, i) for i in range(count))
    return _element(fl, record, base, 0)


def _decode_group(
    sub: DataLayout, record: bytes, base: int, root: DataLayout
) -> DecodedRecord | tuple[DecodedRecord, ...]:
    if sub.occurs_count > 0:
        return tuple(
            _decoded(sub, record, base - i * sub.element_size, root)
            for i in range(sub.occurs_count)
        )
    return _decoded(sub, record, base, root)


def select_record_layout(root: DataLayout, record_name: str | None) -> DataLayout:
    """Pick the 01-level record layout to decode.

    - Root has group children: select by ``record_name``; if exactly one group and
      no name given, use it; if multiple and no name, raise listing the names.
    - Root has no group children (the 01 is elementary): decode the root itself.
    """
    groups = root.groups
    if not groups:
        return root
    if record_name is not None:
        for name, sub in groups.items():
            if name.upper() == record_name.upper():
                return sub
        raise ValueError(
            f"record {record_name!r} not found; available: {sorted(groups)}"
        )
    if len(groups) == 1:
        return next(iter(groups.values()))
    raise ValueError(
        f"copybook declares multiple records; pass --record (one of {sorted(groups)})"
    )


_SKELETON_HEAD = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. VSAMDUMP.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
)


def load_record_layout(
    copybook: Path,
    record_name: str | None,
    jar: str,
    extra_dirs: list[Path],
) -> DataLayout:
    """Parse a copybook (wrapped in a minimal program) into the selected layout."""
    member = copybook.stem
    source = (_SKELETON_HEAD + f"       COPY {member}.\n").encode("utf-8")
    copybook_dirs = [copybook.parent, *extra_dirs]
    parser = ProLeapCobolParser(
        RealSubprocessRunner(), jar, copybook_dirs=copybook_dirs
    )
    asg = parser.parse(source)
    root = build_data_layout(asg.data_fields)
    return select_record_layout(root, record_name)


def _plain(record: DecodedRecord) -> dict[str, Decoded]:
    return record.plain()


def render_jsonl(layout: DataLayout, records: list[bytes]) -> str:
    """One compact JSON object per record, each newline-terminated; empty input yields an empty string."""
    lines = [json.dumps(decode_record(layout, rec), default=_plain) for rec in records]
    return "\n".join(lines) + ("\n" if lines else "")


def render_block(layout: DataLayout, records: list[bytes]) -> str:
    """Human-readable per-field block: @offset NAME value 0xRAW, for each record.

    Note: OCCURS fields show the first element's raw bytes with a ``<occurs>``
    value placeholder; block format does not expand arrays. Use jsonl to see
    decoded arrays.
    """
    chunks: list[str] = []
    for idx, rec in enumerate(records, start=1):
        chunks.append(f"=== record {idx} ===")
        chunks.extend(_block_lines(layout, rec, layout.offset, prefix=""))
    return "\n".join(chunks) + ("\n" if chunks else "")


def _block_lines(
    layout: DataLayout, record: bytes, base: int, prefix: str
) -> list[str]:
    lines: list[str] = []
    for name, fl in layout.fields.items():
        start = fl.offset - base
        raw = record[start : start + fl.byte_length]
        value = _decode_leaf(fl, raw) if fl.occurs_count == 0 else "<occurs>"
        lines.append(
            f"  @{fl.offset:<5} {prefix}{name:<28} {value!r:<24} 0x{raw.hex()}"
        )
    for name, sub in layout.groups.items():
        lines.append(f"  @{sub.offset:<5} {prefix}{name}:")
        lines.extend(_block_lines(sub, record, base, prefix + "  "))
    return lines


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, decode the cataloged dataset via the copybook, write to stdout. Returns an exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m cics.vsam.dump",
        description="Decode a cataloged VSAM dataset via a COBOL copybook.",
    )
    parser.add_argument("--system", required=True, type=Path, help="system directory")
    parser.add_argument("--dsn", required=True, help="cataloged dataset name")
    parser.add_argument("--copybook", required=True, type=Path, help="record copybook")
    parser.add_argument(
        "--record", default=None, help="01-level record name (if multiple)"
    )
    parser.add_argument("--format", choices=["jsonl", "block"], default="jsonl")
    parser.add_argument("--copybook-dir", action="append", default=[], type=Path)
    parser.add_argument(
        "--jar",
        default=os.environ.get("PROLEAP_BRIDGE_JAR"),
        help="ProLeap bridge JAR (defaults to $PROLEAP_BRIDGE_JAR)",
    )
    args = parser.parse_args(argv)
    if not args.jar:
        parser.error("no JAR: pass --jar or set PROLEAP_BRIDGE_JAR")

    layout = load_record_layout(args.copybook, args.record, args.jar, args.copybook_dir)
    record_length = layout.total_bytes
    match SystemCatalog(args.system).lookup(args.dsn):
        case Dataset(path=path):
            records = read_flat_file(path, record_length)
        case NotCataloged():
            parser.error(f"{args.dsn} is not cataloged in {args.system}")
    renderer = render_jsonl if args.format == "jsonl" else render_block
    sys.stdout.write(renderer(layout, records))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
