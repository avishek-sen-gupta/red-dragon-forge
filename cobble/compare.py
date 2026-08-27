"""compare.py — identity diff of out/ vs reference/ node & edge sets.

Node identity   = (kind, id)
Edge identity   = (source, source_kind, target, target_kind, kind)

Reports missing (in reference, not in out) and extra (in out, not in reference)
for both nodes and edges. Exits nonzero if any diff. Goal: EMPTY diff.

The report is logged rather than printed: the exit code is what a caller acts on,
the text is for whoever is reading, and one stream means the per-set blocks cannot
interleave with a trailing verdict.

Invoke as: uv run python -m cobble.compare
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from cobble.cli_logging import configure_cli_logging

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, keyer):
    return {
        keyer(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    }


def _node_key(d):
    return (d["kind"], d["id"])


def _edge_key(d):
    return (d["source"], d["source_kind"], d["target"], d["target_kind"], d["kind"])


def _lines(missing, extra, label, ref, out):
    header = f"=== {label}: {len(out)} out / {len(ref)} reference ==="
    if not missing and not extra:
        return (header, f"  OK — identical ({len(ref)})")
    return (
        header,
        *_side_lines(
            missing, f"MISSING ({len(missing)}) — in reference, not in out", "-"
        ),
        *_side_lines(extra, f"EXTRA ({len(extra)}) — in out, not in reference", "+"),
    )


def _side_lines(keys, heading, marker):
    if not keys:
        return ()
    return (f"  {heading}:", *(f"    {marker} {k}" for k in sorted(map(str, keys))))


def _report(label, ref, out):
    """Log one set's diff and return how many differences it had."""
    missing = ref - out
    extra = out - ref
    logger.info("%s", "\n".join(_lines(missing, extra, label, ref, out)))
    return len(missing) + len(extra)


# (label, filename, identity function) -- one row per set the diff covers.
_SETS = (
    ("NODES", "nodes.jsonl", _node_key),
    ("EDGES", "edges.jsonl", _edge_key),
)


def main() -> int:
    configure_cli_logging()
    out_dir = _REPO_ROOT / "out"
    ref_dir = _REPO_ROOT / "reference"
    # sum over a generator rather than a running total: the reports still come out
    # in _SETS order because a generator is consumed in order.
    diff = sum(
        _report(label, _load(ref_dir / name, keyer), _load(out_dir / name, keyer))
        for label, name, keyer in _SETS
    )
    if diff == 0:
        logger.info("\nRESULT: EMPTY DIFF — out matches reference exactly.")
        return 0
    # ERROR, not INFO: a nonzero diff is the failure this script exists to catch.
    logger.error("\nRESULT: %d difference(s).", diff)
    return 1


if __name__ == "__main__":
    sys.exit(main())
