"""Forward and backward provenance queries over a fixpoint out-dir's provenance.

Each row is one write and one source, with the writes that reach that source
(its definers). Backward walks from a field through the writes that reach each
read; forward walks from a field into the reads each write reaches. Each
program's rows stay in that program; combine's link windows, when given, carry the
walk across calls, and since a window holds no definers, every write to its bytes
on the far side is followed. The answer is a tree, each branch shown once.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from itertools import groupby
from operator import itemgetter
from pathlib import Path

from cobble.cli_logging import configure_cli_logging
from cobble.dataflow.combine.link_row import LinkRow
from cobble.dataflow.fields.crossing import Crossing
from cobble.dataflow.fields.dep_row import DepRow
from cobble.dataflow.fields.extent_text import ByteRange, byte_range
from cobble.dataflow.fields.link_crossings import crossing_rows
from cobble.dataflow.fixpoint.build_corpus import MEMBERS_DIR
from cobble.dataflow.fixpoint.provenance import provenance

logger = logging.getLogger(__name__)

_RangeId = tuple[str, str, int, int]


def _links(path: Path) -> tuple[LinkRow, ...]:
    if path == Path():
        return ()
    return tuple(
        LinkRow.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def provenance_rows(fixpoint_dir: Path, links_path: Path) -> tuple[DepRow, ...]:
    """The fixpoint's flow and sink rows, then each combine link window's fields."""
    return tuple(
        dict.fromkeys(
            (
                *provenance(fixpoint_dir),
                *(
                    row
                    for link in _links(links_path)
                    for row in crossing_rows(fixpoint_dir, link)
                ),
            )
        )
    )


def _range_id(extent: ByteRange) -> _RangeId:
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
    """Distinct byte ranges matching a field name, deduplicated by extent."""
    program_filter, field = _parsed_name(name)
    candidates = tuple(
        extent
        for dep in deps
        for extent in (dep.target, dep.source)
        if _matches(extent, field, program_filter)
    )
    return reduce(
        lambda pair, c: (
            ((*pair[0], c), pair[1] | {_range_id(c)})
            if _range_id(c) not in pair[1]
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


_Grouped = Mapping[str, tuple[DepRow, ...]]
_Calls = tuple[str, ...]
_Branch = tuple[DepRow, ByteRange, _Calls]
_Children = Callable[[_Branch], tuple[_Branch, ...]]
_Seen = frozenset[tuple[DepRow, _RangeId, _Calls]]


def _grouped(pairs: Iterable[tuple[str, DepRow]]) -> _Grouped:
    ordered = sorted((name, n, row) for n, (name, row) in enumerate(pairs))
    return {
        name: tuple(row for _name, _n, row in group)
        for name, group in groupby(ordered, itemgetter(0))
    }


@dataclass(frozen=True)
class _Index:
    """The rows by what each step of a walk looks them up by."""

    at_site: _Grouped
    reached_by: _Grouped
    written_in: _Grouped
    read_in: _Grouped
    entered: _Grouped


def _index(deps: Sequence[DepRow]) -> _Index:
    return _Index(
        at_site=_grouped((dep.site, dep) for dep in deps if dep.target.known),
        reached_by=_grouped((definer, dep) for dep in deps for definer in dep.definers),
        written_in=_grouped(
            (dep.target.program, dep) for dep in deps if dep.target.known
        ),
        read_in=_grouped((dep.source.program, dep) for dep in deps if dep.source.known),
        entered=_grouped(
            (dep.program, dep) for dep in deps if dep.crossing is Crossing.ENTERED
        ),
    )


def _narrowed(source: ByteRange, target: ByteRange, wanted: ByteRange) -> ByteRange:
    """The slice of ``source`` that corresponds to the ``wanted`` sub-range of
    ``target``. When target and source are the same length (group move, commarea
    binding), the offset relationship is 1:1. When they differ, the source is
    returned as-is — narrowing a many-to-one conversion is not sound.

    It is the overlap of ``wanted`` and ``target`` that is 1:1, not ``wanted``
    itself: a range wider than the target is the ordinary case once a group and
    one of its members are both being traced, and offsetting by its start would
    slide the slice off the front of the source.
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


def _stacked(dep: DepRow, calls: _Calls, inward: Crossing) -> tuple[_Calls, ...]:
    """The calls the walk is inside after taking ``dep``: a window going into a
    callee pushes its call; one coming out may only be the call on top, which it
    pops, or any call when the walk started inside the callee."""
    if dep.crossing is Crossing.NONE:
        return (calls,)
    if dep.crossing is inward:
        return ((*calls, dep.site),)
    return _left(dep, calls)


def _left(dep: DepRow, calls: _Calls) -> tuple[_Calls, ...]:
    if not calls:
        return (calls,)
    return (calls[:-1],) if calls[-1] == dep.site else ()


def _writers(index: _Index, dep: DepRow) -> tuple[DepRow, ...]:
    """The writes that can have put a read's bytes there: its definers, and, when
    the bytes may still be the ones the program was entered with, the windows that
    carried them in."""
    entered = index.entered.get(dep.source.program, ()) if dep.entry else ()
    return (
        *(row for site in dep.definers for row in index.at_site.get(site, ())),
        *entered,
    )


def _backward_children(index: _Index, branch: _Branch) -> tuple[_Branch, ...]:
    dep, wanted, calls = branch
    if not dep.source.known:
        return ()
    read = _narrowed(dep.source, dep.target, wanted)
    return tuple(
        (row, read, inside)
        for row in _writers(index, dep)
        if row.target.overlaps(read)
        for inside in _stacked(row, calls, Crossing.RETURNED)
    )


def _readers(index: _Index, dep: DepRow) -> tuple[DepRow, ...]:
    """The reads a write's bytes can reach: those it is a definer of, and, past a
    window into a program, the reads that may still see the bytes it was entered
    with."""
    entry = (
        tuple(row for row in index.read_in.get(dep.target.program, ()) if row.entry)
        if dep.crossing is Crossing.ENTERED
        else ()
    )
    return (*index.reached_by.get(dep.site, ()), *entry)


def _written(row: DepRow, wanted: ByteRange) -> ByteRange:
    return _narrowed(row.target, row.source, wanted) if row.target.known else wanted


def _forward_children(index: _Index, branch: _Branch) -> tuple[_Branch, ...]:
    dep, wanted, calls = branch
    if not dep.sink.is_none or not dep.target.known:
        return ()
    return tuple(
        (row, _written(row, wanted), inside)
        for row in _readers(index, dep)
        if row.source.overlaps(wanted)
        for inside in _stacked(row, calls, Crossing.ENTERED)
    )


def _initial(
    index: _Index, roots: Sequence[ByteRange], direction: str
) -> tuple[_Branch, ...]:
    if direction == FORWARD:
        return tuple(
            (row, _written(row, root), inside)
            for root in roots
            for row in index.read_in.get(root.program, ())
            if row.source.overlaps(root)
            for inside in _stacked(row, (), Crossing.ENTERED)
        )
    return tuple(
        (row, root, inside)
        for root in roots
        for row in index.written_in.get(root.program, ())
        if row.target.overlaps(root)
        for inside in _stacked(row, (), Crossing.RETURNED)
    )


def _arrived(dep: DepRow) -> str:
    return str(dep.target) if dep.sink.is_none else dep.sink.text()


def _came_from(dep: DepRow) -> str:
    return str(dep.source) if dep.origin.is_storage else dep.origin.text()


def _line(direction: str, dep: DepRow, depth: int) -> str:
    forward = direction == FORWARD
    arrow = "->" if forward else "<-"
    text = _arrived(dep) if forward else _came_from(dep)
    return f"{'  ' * depth}{arrow} {text}  at {dep.site}"


def _ordered(branches: Iterable[_Branch]) -> tuple[_Branch, ...]:
    unique = dict.fromkeys(branches)
    ranked = sorted(
        (branch[0].site, str(branch[0].target), str(branch[0].source), n, branch)
        for n, branch in enumerate(unique)
    )
    return tuple(branch for *_rank, branch in ranked)


@dataclass(frozen=True)
class _Walk:
    """The lines written so far, and every branch already shown."""

    lines: tuple[str, ...] = ()
    seen: _Seen = frozenset()


@dataclass(frozen=True)
class _Tree:
    """How to grow one tree: its direction, how a branch splits, and how deep."""

    direction: str
    children: _Children
    max_depth: int


def _grown(tree: _Tree, walk: _Walk, branch: _Branch, depth: int) -> _Walk:
    dep, wanted, calls = branch
    shown_as = (dep, _range_id(wanted), calls)
    line = _line(tree.direction, dep, depth)
    if shown_as in walk.seen:
        return _Walk((*walk.lines, f"{line}  (see above)"), walk.seen)
    shown = _Walk((*walk.lines, line), walk.seen | {shown_as})
    if depth >= tree.max_depth:
        return shown
    return _branches(tree, shown, tree.children(branch), depth + 1)


def _branches(
    tree: _Tree, walk: _Walk, branches: Iterable[_Branch], depth: int
) -> _Walk:
    return reduce(
        lambda grown, branch: _grown(tree, grown, branch, depth),
        _ordered(branches),
        walk,
    )


FORWARD = "forward"
BACKWARD = "backward"


def _roots_of(
    field: str, deps: Sequence[DepRow], extents_path: Path
) -> tuple[ByteRange, ...]:
    found = _resolve(field, deps)
    if found:
        return found
    return _resolve_from_extents(field, extents_path) if extents_path.is_file() else ()


def query(
    deps: Sequence[DepRow],
    direction: str,
    field: str,
    max_depth: int = 5,
    extents_path: Path = Path(),
) -> tuple[str, ...]:
    roots = _roots_of(field, deps, extents_path)
    if not roots:
        return (f"field {field!r} not found in the provenance or extents",)
    index = _index(deps)
    step = _forward_children if direction == FORWARD else _backward_children
    tree = _Tree(direction, lambda branch: step(index, branch), max_depth)
    walk = _branches(tree, _Walk(), _initial(index, roots, direction), 1)
    if not walk.lines:
        return (*(str(r) for r in roots), "  (no further provenance)")
    return (*(str(r) for r in roots), *walk.lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward or backward provenance walk over a fixpoint out-dir."
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
        "--fixpoint",
        required=True,
        type=Path,
        help="the out-dir cobble-dataflow-fixpoint wrote",
    )
    parser.add_argument(
        "--links",
        type=Path,
        default=Path(),
        help="links.jsonl from cobble-dataflow-combine; without it the walk stays in each program",
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


def _refusal(fixpoint_dir: Path, field: str) -> str:
    members = fixpoint_dir / MEMBERS_DIR
    if not members.is_dir():
        return f"no fixpoint out-dir at {fixpoint_dir}"
    program, _ = _parsed_name(field)
    if program and not (members / program).is_dir():
        return f"no member {program} under {fixpoint_dir}"
    return ""


def cli(argv: Sequence[str] = ()) -> int:
    configure_cli_logging()
    arguments = _parser().parse_args(tuple(argv) if argv else None)
    refused = _refusal(arguments.fixpoint, arguments.field)
    if refused:
        logger.error("trace-query: %s", refused)
        return 2
    output = query(
        provenance_rows(arguments.fixpoint, arguments.links),
        arguments.direction,
        arguments.field,
        arguments.depth,
        arguments.extents,
    )
    sys.stdout.write("\n".join(output) + "\n")
    return 0


def main() -> int:
    sys.exit(cli())
