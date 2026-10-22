"""Field unification through COMMAREA byte-offset matching.

For each inter-program call that passes data through a shared buffer,
resolve the leaf fields in both the caller's and callee's windows and
merge (union-find) fields that sit at the same relative byte offset.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from cobble.experimental.aggregates.io import parse_extent, read_jsonl
from cobble.experimental.aggregates.union_find import UnionFind

logger = logging.getLogger(__name__)


def unify_fields(
    aliases_path: Path,
    extents_path: Path,
) -> UnionFind:
    """Build equivalence classes of field names from alias byte offsets."""

    # --- Load aliases ---
    aliases: list[dict] = []
    needed_programs: set[str] = set()

    for row in read_jsonl(aliases_path):
        ce = row.get("caller_extent", "")
        ee = row.get("callee_extent", "")
        if not ce or not ee:
            continue
        cp = parse_extent(ce)
        ep = parse_extent(ee)
        if cp is None or ep is None:
            continue
        aliases.append(
            {
                "caller": row["caller"],
                "callee": row["callee"],
                "c_region": cp[1],
                "c_start": cp[2],
                "c_end": cp[3],
                "e_region": ep[1],
                "e_start": ep[2],
                "e_end": ep[3],
            }
        )
        needed_programs.add(row["caller"])
        needed_programs.add(row["callee"])

    logger.info(
        "unify: %d aliases with both extents, %d programs",
        len(aliases),
        len(needed_programs),
    )

    # --- Index leaf fields from extents ---
    field_index: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    seen: set[tuple[str, str, int, int, str]] = set()

    for row in read_jsonl(extents_path):
        prog = row["program"]
        if prog not in needed_programs:
            continue
        pics = row.get("pics", [])
        if not pics or not pics[0]:
            continue
        for ext_str in row.get("extents", []):
            parsed = parse_extent(ext_str)
            if parsed is None:
                continue
            field, region, start, end = parsed
            key = (prog, region, start, end, field)
            if key not in seen:
                seen.add(key)
                field_index[(prog, region)].append((start, end, field))

    for k in field_index:
        field_index[k].sort()

    logger.info(
        "unify: indexed %d leaf fields across %d (program, region) pairs",
        sum(len(v) for v in field_index.values()),
        len(field_index),
    )

    # --- Match fields across alias boundaries ---
    uf = UnionFind()
    merge_count = 0

    for a in aliases:
        c_fields = [
            (s - a["c_start"], e - a["c_start"], f)
            for s, e, f in field_index.get((a["caller"], a["c_region"]), [])
            if s >= a["c_start"] and e <= a["c_end"]
        ]
        e_by_offset: dict[tuple[int, int], list[str]] = defaultdict(list)
        for s, e, f in (
            (s - a["e_start"], e - a["e_start"], f)
            for s, e, f in field_index.get((a["callee"], a["e_region"]), [])
            if s >= a["e_start"] and e <= a["e_end"]
        ):
            e_by_offset[(s, e)].append(f)

        for rel_start, rel_end, c_field in c_fields:
            for e_field in e_by_offset.get((rel_start, rel_end), []):
                if c_field != e_field:
                    if uf.union(c_field, e_field):
                        merge_count += 1
                else:
                    uf.find(c_field)

    logger.info("unify: %d new merges", merge_count)
    return uf


def write_unified(path: Path, uf: UnionFind) -> int:
    """Write equivalence classes (2+ members) as JSONL."""
    classes = uf.classes()
    n = 0
    with open(path, "w") as fh:
        for rep, members in sorted(classes.items(), key=lambda kv: -len(kv[1])):
            if len(members) < 2:
                continue
            fh.write(
                json.dumps({"canonical": rep, "members": members}, sort_keys=True)
                + "\n"
            )
            n += 1
    logger.info("unify: wrote %d equivalence classes to %s", n, path)
    return n


def read_unified(path: Path) -> dict[str, str]:
    """Read unified JSONL back into a field → canonical mapping."""
    mapping: dict[str, str] = {}
    for row in read_jsonl(path):
        canonical = row["canonical"]
        for member in row["members"]:
            mapping[member] = canonical
    return mapping
