"""Shared I/O helpers for the aggregate-discovery pipeline."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

_EXTENT_RE = re.compile(r"^(.+)@(\w+)\[(\d+):(\d+)]~?$")


def parse_extent(extent_str: str) -> tuple[str, str, int, int] | None:
    """Parse ``FIELD@region[start:end]`` into *(field, region, start, end)*.

    Returns *None* if *extent_str* does not match the expected format.
    """
    m = _EXTENT_RE.match(extent_str)
    if m is None:
        return None
    return m.group(1), m.group(2), int(m.group(3)), int(m.group(4))


def read_jsonl(path: Path) -> Iterator[dict]:
    """Yield one parsed dict per line of a JSONL file."""
    with open(path) as fh:
        for line in fh:
            yield json.loads(line)


def write_jsonl(path: Path, rows: Iterator[dict] | list[dict]) -> int:
    """Write dicts as JSONL.  Returns the number of rows written."""
    n = 0
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    return n


def extract_paragraph(node: str) -> str:
    """``'1000-INIT/0.then.1'`` → ``'1000-INIT'``."""
    return node.split("/")[0]
