# scripts/check_red_dragon_pin.py
"""Fail loudly if this repo's vendored RedDragon commit doesn't match the one
vendored inside vendor/cicada or vendor/squall (their own nested submodule
checkouts). This does NOT modify cicada or squall — it only reports drift; a
human decides whether/how to re-pin those repos (see the plan's Task 2 for why
this repo doesn't reach into siblings and bump their pins itself).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_CHECKOUTS = {
    "red-dragon-forge (this repo)": _ROOT / "vendor" / "red-dragon",
    "cicada": _ROOT / "vendor" / "cicada" / "vendor" / "red-dragon",
    "squall": _ROOT / "vendor" / "squall" / "vendor" / "red-dragon",
}


def _head_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    shas = {name: _head_sha(path) for name, path in _CHECKOUTS.items()}
    unique = set(shas.values())
    for name, sha in shas.items():
        print(f"{name}: {sha}")
    if len(unique) == 1:
        print("OK: all three RedDragon pins match.")
        return 0
    print(
        "DRIFT: RedDragon pins disagree across repos. Re-pin the stale ones "
        "(in their own repos, with their own commits) to the newest SHA above.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
