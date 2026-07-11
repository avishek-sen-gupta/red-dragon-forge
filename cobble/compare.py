"""compare.py — identity diff of out/ vs reference/ node & edge sets.

Node identity   = (kind, id)
Edge identity   = (source, source_kind, target, target_kind, kind)

Prints missing (in reference, not in out) and extra (in out, not in reference)
for both nodes and edges. Exits nonzero if any diff. Goal: EMPTY diff.

Invoke as: uv run python -m cobble.compare
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, keyer):
    return {keyer(json.loads(l)) for l in path.read_text().splitlines() if l.strip()}


def _node_key(d):
    return (d["kind"], d["id"])


def _edge_key(d):
    return (d["source"], d["source_kind"], d["target"], d["target_kind"], d["kind"])


def _report(label, ref, out):
    missing = ref - out
    extra = out - ref
    print(f"=== {label}: {len(out)} out / {len(ref)} reference ===")
    if not missing and not extra:
        print(f"  OK — identical ({len(ref)})")
    if missing:
        print(f"  MISSING ({len(missing)}) — in reference, not in out:")
        for k in sorted(map(str, missing)):
            print(f"    - {k}")
    if extra:
        print(f"  EXTRA ({len(extra)}) — in out, not in reference:")
        for k in sorted(map(str, extra)):
            print(f"    + {k}")
    return len(missing) + len(extra)


def main() -> int:
    out_dir = _REPO_ROOT / "out"
    ref_dir = _REPO_ROOT / "reference"
    diff = 0
    diff += _report(
        "NODES",
        _load(ref_dir / "nodes.jsonl", _node_key),
        _load(out_dir / "nodes.jsonl", _node_key),
    )
    diff += _report(
        "EDGES",
        _load(ref_dir / "edges.jsonl", _edge_key),
        _load(out_dir / "edges.jsonl", _edge_key),
    )
    print()
    if diff == 0:
        print("RESULT: EMPTY DIFF — out matches reference exactly.")
        return 0
    print(f"RESULT: {diff} difference(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
