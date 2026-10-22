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
from functools import partial, reduce
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.fields.extent_text import (
    NO_RANGE,
    ByteRange,
    byte_range,
    byte_range_from_dict,
)
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)

_RangeKey = tuple[str, str, int, int]
_DEFINERS = TypeAdapter(tuple[str, ...])


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
    sink: str
    literal: str = ""


def _range_of(
    raw: str | int | bool | Mapping[str, str | int | bool], program: str
) -> ByteRange:
    """A null end -- an origin row's source, a sink row's target -- is no range."""
    return byte_range_from_dict(raw, program) if isinstance(raw, Mapping) else NO_RANGE


def _dep_of(
    row: Mapping[str, str | int | bool | Mapping[str, str | int | bool]],
) -> DepRow:
    program = str(row.get("program", ""))
    source_program = str(row.get("source_program", "")) or program
    return DepRow(
        program=program,
        via=str(row.get("via", "")),
        target=_range_of(row.get("target", ""), program),
        origin=str(row.get("origin", "")),
        source=_range_of(row.get("source", ""), source_program),
        site=str(row.get("site", "")),
        definers=_DEFINERS.validate_python(row.get("definers", ())),
        sink=str(row.get("sink", "")),
        literal=str(row.get("literal", "")),
    )


def load(path: Path) -> tuple[DepRow, ...]:
    """Every dep row from a JSONL trace, deduplicated, ignoring footer rows."""
    return tuple(
        dict.fromkeys(
            _dep_of(parsed)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            for parsed in (json.loads(line),)
            if parsed.get("kind") == "dep"
        )
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


def _resolve_from_extents(name: str, extents_path: Path) -> tuple[ByteRange, ...]:
    """Resolve a field name to byte ranges via the declared extents table."""
    program_filter, field = _parsed_name(name)
    rows = tuple(
        json.loads(line)
        for line in extents_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    matches = tuple(
        row for row in rows if _extents_field_matches(row, field, program_filter)
    )
    return tuple(
        br
        for row in matches
        for extent_text in row.get("extents", ())
        for br in (byte_range(extent_text, _extents_program(row)),)
        if br.known
    )


def _extents_field_matches(
    row: Mapping[str, str | int | bool | Sequence[str]],
    field: str,
    program_filter: str,
) -> bool:
    row_id = str(row.get("id", ""))
    parts = row_id.rsplit(".", 1)
    row_program = parts[0] if len(parts) == 2 else ""
    row_field = parts[1] if len(parts) == 2 else row_id
    return row_field == field and (not program_filter or row_program == program_filter)


def _extents_program(
    row: Mapping[str, str | int | bool | Sequence[str]],
) -> str:
    row_id = str(row.get("id", ""))
    parts = row_id.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else ""


def _overlaps_any(extent: ByteRange, frontier: Sequence[ByteRange]) -> bool:
    return any(extent.overlaps(f) for f in frontier)


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


_Step = Callable[[Sequence[DepRow], _State, int], _State]


def _hit_of(dep: DepRow, depth: int) -> _Hit:
    return _Hit(
        depth=depth,
        source_text=str(dep.source) if dep.source.known else dep.origin,
        target_text=dep.sink or str(dep.target),
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


def _narrowed(source: ByteRange, target: ByteRange, wanted: ByteRange) -> ByteRange:
    """The slice of ``source`` that corresponds to the ``wanted`` sub-range of
    ``target``. When target and source are the same length (group move, commarea
    binding), the offset relationship is 1:1. When they differ, the source is
    returned as-is — narrowing a many-to-one conversion is not sound.

    It is the overlap of ``wanted`` and ``target`` that is 1:1, not ``wanted``
    itself: a frontier range wider than the target is the ordinary case once a
    group and one of its members are both being traced, and offsetting by its
    start would slide the slice off the front of the source.
    """
    if target.length != source.length:
        return source
    start = max(wanted.start, target.start)
    length = min(wanted.end, target.end) - start
    return ByteRange(
        program=source.program,
        region=source.region,
        start=source.start + start - target.start,
        end=source.start + start - target.start + length,
        name=source.name,
        exact=source.exact,
        known=True,
    )


def _narrow_sources(
    dep: DepRow, frontier: Sequence[ByteRange]
) -> tuple[ByteRange, ...]:
    """The source narrowed to each frontier range the target overlaps.

    One slice per overlap rather than one for the first of them: the frontier is a
    set, so "the first" is whatever order it was built in, and picking from it both
    drops the other overlaps and makes the answer depend on iteration order.
    """
    matched = tuple(f for f in frontier if dep.target.overlaps(f))
    if not matched:
        return (dep.source,)
    return tuple(_narrowed(dep.source, dep.target, one) for one in matched)


def _backward_step(deps: Sequence[DepRow], state: _State, depth: int) -> _State:
    matched = tuple(dep for dep in deps if _overlaps_any(dep.target, state.frontier))
    new_hits = tuple(_hit_of(dep, depth) for dep in matched)
    narrowed = tuple(
        one
        for dep in matched
        if dep.source.known and _range_key(dep.source) not in state.seen
        for one in _narrow_sources(dep, state.frontier)
    )
    new_keys = frozenset(_range_key(s) for s in narrowed)
    deduped = tuple(dict((_range_key(s), s) for s in narrowed).values())
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
        partial(_deepened, deps=deps, step=step), range(1, max_depth + 1), initial
    )
    return final.hits


def _deepened(state: _State, depth: int, deps: Sequence[DepRow], step: _Step) -> _State:
    return state if not state.frontier else step(deps, state, depth)


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


def _display_text(hit: _Hit, direction: str) -> str:
    """The extent or origin to show for the far end of this edge."""
    if direction == FORWARD:
        return hit.target_text
    return hit.origin if hit.origin else hit.source_text


def _format_hit(direction: str, hit: _Hit) -> str:
    arrow = "->" if direction == FORWARD else "<-"
    text = _display_text(hit, direction)
    suffix = f"  [{hit.origin}]" if hit.origin and direction == FORWARD else ""
    return f"{'  ' * hit.depth}{arrow} {text}  at {hit.site}{suffix}"


def _format_hits(
    direction: str, roots: Sequence[ByteRange], hits: Sequence[_Hit]
) -> tuple[str, ...]:
    formatted = tuple(
        _format_hit(direction, hit) for hit in sorted(hits, key=_hit_sort_key)
    )
    deduped = tuple(dict.fromkeys(formatted))
    return (*(str(r) for r in roots), *deduped)


def _roots_of(
    field: str, deps: Sequence[DepRow], extents_path: Path
) -> tuple[ByteRange, ...]:
    found = _resolve(field, deps)
    if found:
        return found
    return _resolve_from_extents(field, extents_path) if extents_path.is_file() else ()


def query(
    path: Path,
    direction: str,
    field: str,
    max_depth: int = 5,
    extents_path: Path = Path(),
) -> tuple[str, ...]:
    deps = load(path)
    roots = _roots_of(field, deps, extents_path)
    if not roots:
        return (f"field {field!r} not found in trace or extents",)
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
    parser.add_argument(
        "--extents",
        type=Path,
        default=Path(),
        help="extents.jsonl for resolving fields not named in any dep row",
    )
    return parser


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    if not arguments.trace.is_file():
        logger.error("trace-query: no trace file at %s", arguments.trace)
        return 2
    output = query(
        arguments.trace,
        arguments.direction,
        arguments.field,
        arguments.depth,
        arguments.extents,
    )
    sys.stdout.write("\n".join(output) + "\n")
    return 0


def main() -> int:
    sys.exit(cli())
