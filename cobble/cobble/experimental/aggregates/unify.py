"""unified.jsonl: the exact classes, written one per line and read back as each member's class name."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from cobble.experimental.aggregates.unified_line import UnifiedLine


def write_unified(path: Path, classes: Sequence[Sequence[str]]) -> None:
    path.write_text(
        "".join(
            f"{UnifiedLine(members=tuple(members)).model_dump_json()}\n"
            for members in classes
        ),
        encoding="utf-8",
    )


def read_unified(path: Path) -> Mapping[str, str]:
    lines = tuple(
        UnifiedLine.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return {member: line.members[0] for line in lines for member in line.members}
