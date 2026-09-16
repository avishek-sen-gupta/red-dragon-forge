"""CLI: emit field-access rows from a multi-program CFG + ASG directory."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.access import AccessRow, accesses
from cobble.path_utils import ensure_parent
from cobol_memory.field_extent import FieldExtent, Precision

logger = logging.getLogger(__name__)


def _extent_dict(extent: FieldExtent) -> dict[str, str | int | bool]:
    return {
        "field": extent.field_name,
        "region": extent.region.value,
        "start": extent.start,
        "end": extent.start + extent.length,
        "clamped": extent.precision is Precision.CLAMPED,
    }


def _row(access: AccessRow) -> str:
    return json.dumps(
        {
            "kind": "access",
            "program": access.program,
            "site": access.site,
            "paragraph": access.paragraph,
            "extent": _extent_dict(access.extent),
        },
        separators=(",", ":"),
    )


def cli(argv: tuple[str, ...] = ()) -> int:
    configure_cli_logging()
    parser = argparse.ArgumentParser(description="Emit field-access rows.")
    parser.add_argument("--cfg", required=True, type=Path)
    parser.add_argument("--asg-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv if argv else None)
    rows = accesses(args.cfg, args.asg_dir)
    logger.info("access: %d rows from %s", len(rows), args.cfg)
    ensure_parent(args.out).write_text(
        "\n".join(_row(r) for r in rows) + "\n", encoding="utf-8"
    )
    return 0


def main() -> int:
    sys.exit(cli())
