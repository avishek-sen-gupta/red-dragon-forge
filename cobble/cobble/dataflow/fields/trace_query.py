"""Forward and backward provenance queries over a JSONL trace report.

The trace is flat -- one row per dep, each self-contained -- and the query is a
BFS over byte-extent containment. Forward walks from a field to everything its
bytes eventually reach; backward walks from a field to every origin that fed it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.extent_text import ByteRange, byte_range_from_dict

logger = logging.getLogger(__name__)

_RangeKey = tuple[str, str, int, int]
_Step = Callable[[Sequence["DepRow"], "_State", int], "_State"]


@dataclass(frozen=True)
class DepRow:
    """One dep from the JSONL, with extents parsed into comparable ranges."""

    program: str
    via: str
    target: ByteRange
    origin: str
    source: ByteRange
    site: str
    definers: tuple[str, ...]


def _extent_or_empty(
    raw: str | int | bool | Mapping[str, str | int | bool],
) -> Mapping[str, str | int | bool]:
    return raw if isinstance(raw, Mapping) else {}


def _dep_of(
    row: Mapping[str, str | int | bool | Mapping[str, str | int | bool]],
) -> DepRow:
    program = str(row.get("program", ""))
    return DepRow(
        program=program,
        via=str(row.get("via", "")),
        target=byte_range_from_dict(_extent_or_empty(row.get("target", "")), program),
        origin=str(row.get("origin", "")),
        source=byte_range_from_dict(_extent_or_empty(row.get("source", "")), program),
        site=str(row.get("site", "")),
        definers=tuple(str(d) for d in row.get("definers", ())),
    )


def load(path: Path) -> tuple[DepRow, ...]:
    """Every dep row from a JSONL trace, ignoring footer rows."""
    return tuple(
        _dep_of(parsed)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for parsed in (json.loads(line),)
        if parsed.get("kind") == "dep"
    )


def _range_key(extent: ByteRange) -> _RangeKey:
    return (extent.program, extent.region, extent.start, extent.end)


def _matches(extent: ByteRange, field: str, program_filter: str) -> bool:
    return (
        extent.known
        and extent.name == field
        and (not program_filter or extent.program == program_filter)
    )


def _parsed_name(name: str) -> tuple[str, str]:
    parts = name.split(".", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0])


def _resolve(name: str, deps: Sequence[DepRow]) -> tuple[ByteRange, ...]:
    """Distinct byte ranges matching a field name, deduplicated by key."""
    program_filter, field = _parsed_name(name)
    candidates = tuple(
        extent
        for dep in deps
        for extent in (dep.target, dep.source)
        if _matches(extent, field, program_filter)
    )
    return reduce(
        lambda pair, c: (
            ((*pair[0], c), pair[1] | {_range_key(c)})
            if _range_key(c) not in pair[1]
            else pair
        ),
        candidates,
        ((), frozenset()),
    )[0]


def _overlaps_any(extent: ByteRange, frontier: Sequence[ByteRange]) -> bool:
    return any(extent.overlaps(f) or f.covers(extent) for f in frontier)


def _covers_any(extent: ByteRange, frontier: Sequence[ByteRange]) -> bool:
    return any(extent.covers(f) or f.covers(extent) for f in frontier)


@dataclass(frozen=True)
class _Hit:
    """One provenance edge found during the walk."""

    depth: int
    source_text: str
    target_text: str
    site: str
    origin: str
    definers: tuple[str, ...]


@dataclass(frozen=True)
class _State:
    """BFS accumulator: hits so far, current frontier, visited keys."""

    hits: tuple[_Hit, ...]
    frontier: tuple[ByteRange, ...]
    seen: frozenset[_RangeKey]


def _hit_of(dep: DepRow, depth: int) -> _Hit:
    return _Hit(
        depth=depth,
        source_text=str(dep.source) if dep.source.known else dep.origin,
        target_text=str(dep.target),
        site=dep.site,
        origin=dep.origin,
        definers=dep.definers,
    )


def _forward_step(deps: Sequence[DepRow], state: _State, depth: int) -> _State:
    matched = tuple(dep for dep in deps if _overlaps_any(dep.source, state.frontier))
    new_hits = tuple(_hit_of(dep, depth) for dep in matched)
    new_targets = tuple(
        dep.target
        for dep in matched
        if dep.target.known and _range_key(dep.target) not in state.seen
    )
    new_keys = frozenset(_range_key(t) for t in new_targets)
    deduped = tuple(dict((_range_key(t), t) for t in new_targets).values())
    return _State(
        hits=(*state.hits, *new_hits),
        frontier=deduped,
        seen=state.seen | new_keys,
    )


def _backward_step(deps: Sequence[DepRow], state: _State, depth: int) -> _State:
    matched = tuple(dep for dep in deps if _covers_any(dep.target, state.frontier))
    new_hits = tuple(_hit_of(dep, depth) for dep in matched)
    new_sources = tuple(
        dep.source
        for dep in matched
        if dep.source.known and _range_key(dep.source) not in state.seen
    )
    new_keys = frozenset(_range_key(s) for s in new_sources)
    deduped = tuple(dict((_range_key(s), s) for s in new_sources).values())
    return _State(
        hits=(*state.hits, *new_hits),
        frontier=deduped,
        seen=state.seen | new_keys,
    )


def _bfs(
    deps: Sequence[DepRow],
    roots: Sequence[ByteRange],
    max_depth: int,
    step: _Step,
) -> tuple[_Hit, ...]:
    initial = _State(
        hits=(),
        frontier=tuple(roots),
        seen=frozenset(_range_key(r) for r in roots),
    )
    final = reduce(
        lambda state, depth: state if not state.frontier else step(deps, state, depth),
        range(1, max_depth + 1),
        initial,
    )
    return final.hits


def _forward(
    deps: Sequence[DepRow], roots: Sequence[ByteRange], max_depth: int
) -> tuple[_Hit, ...]:
    return _bfs(deps, roots, max_depth, _forward_step)


def _backward(
    deps: Sequence[DepRow], roots: Sequence[ByteRange], max_depth: int
) -> tuple[_Hit, ...]:
    return _bfs(deps, roots, max_depth, _backward_step)


FORWARD = "forward"
BACKWARD = "backward"


def _hit_sort_key(hit: _Hit) -> tuple[int, str]:
    return (hit.depth, hit.target_text)


def _format_hit(direction: str, hit: _Hit) -> str:
    arrow = "->" if direction == FORWARD else "<-"
    text = hit.target_text if direction == FORWARD else hit.source_text
    suffix = f"  [{hit.origin}]" if hit.origin else ""
    return f"{'  ' * hit.depth}{arrow} {text}  at {hit.site}{suffix}"


def _format_hits(
    direction: str, roots: Sequence[ByteRange], hits: Sequence[_Hit]
) -> tuple[str, ...]:
    return (
        *(str(r) for r in roots),
        *(_format_hit(direction, hit) for hit in sorted(hits, key=_hit_sort_key)),
    )


def query(
    path: Path, direction: str, field: str, max_depth: int = 5
) -> tuple[str, ...]:
    deps = load(path)
    roots = _resolve(field, deps)
    if not roots:
        return (f"field {field!r} not found in trace",)
    walk = _forward if direction == FORWARD else _backward
    hits = walk(deps, roots, max_depth)
    if not hits:
        return (*(str(r) for r in roots), "  (no further provenance)")
    return _format_hits(direction, roots, hits)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward or backward provenance walk over a JSONL trace."
    )
    parser.add_argument(
        "direction",
        choices=(FORWARD, BACKWARD),
        help="forward = what does FIELD affect; backward = what feeds FIELD",
    )
    parser.add_argument(
        "field",
        help="a field name (FIELD-X) or PROGRAM.FIELD to qualify it",
    )
    parser.add_argument(
        "--trace", required=True, type=Path, help="path to the JSONL trace file"
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=5,
        help="max hops to follow (default 5)",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    if not arguments.trace.is_file():
        logger.error("trace-query: no trace file at %s", arguments.trace)
        return 2
    output = query(
        arguments.trace, arguments.direction, arguments.field, arguments.depth
    )
    sys.stdout.write("\n".join(output) + "\n")
    return 0


def main() -> int:
    sys.exit(cli())
