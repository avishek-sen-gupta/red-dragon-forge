"""CLI: find field-access sites by field name and extent overlap."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.trace_query import ByteRange, _resolve_from_extents

_JsonRow = Mapping[str, str | int | bool]


def _load_accesses(path: Path) -> tuple[_JsonRow, ...]:
    return tuple(
        parsed
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for parsed in (json.loads(line),)
        if parsed.get("kind") == "access"
    )


def _overlaps(row: _JsonRow, root: ByteRange) -> bool:
    e = row.get("extent") or {}
    return (
        e.get("region") == root.region  # type: ignore[union-attr]
        and (not root.program or root.program == row.get("program", ""))
        and e.get("start", 0) < root.end  # type: ignore[union-attr]
        and root.start < e.get("end", 0)  # type: ignore[union-attr]
    )


def _format(row: _JsonRow) -> str:
    para = row.get("paragraph", "")
    return f"  {row['site']}" + (f"  ({para})" if para else "")


def query(field: str, accesses_path: Path, extents_path: Path) -> tuple[str, ...]:
    roots = _resolve_from_extents(field, extents_path)
    if not roots:
        return (f"field {field!r} not found in extents",)
    rows = _load_accesses(accesses_path)
    hits = tuple(
        dict.fromkeys(
            _format(row) for root in roots for row in rows if _overlaps(row, root)
        )
    )
    header = tuple(str(r) for r in roots)
    return (*header, *hits) if hits else (*header, "  (no accesses found)")


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    parser = argparse.ArgumentParser(description="Find field access sites.")
    parser.add_argument("field")
    parser.add_argument("--accesses", required=True, type=Path)
    parser.add_argument("--extents", required=True, type=Path)
    args = parser.parse_args(tuple(argv) if argv else None)
    output = query(args.field, args.accesses, args.extents)
    sys.stdout.write("\n".join(output) + "\n")
    return 0


def main() -> int:
    sys.exit(cli())
