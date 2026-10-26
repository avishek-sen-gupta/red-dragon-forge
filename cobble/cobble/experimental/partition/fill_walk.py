"""The walk tracing each read back through the copies that filled it, on an explicit stack: each lookup is a generator that asks for the lookups it needs, so no chain of copies can exhaust Python's recursion limit."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence

from cobble.dataflow.fields.dep_row import DepRow
from cobble.experimental.partition.fill_query import FillQuery
from cobble.experimental.partition.fill_trace import (
    Fields,
    Rows,
    child,
    feeds,
    finer,
    presented,
    written_rows,
)
from cobble.experimental.partition.leaf_index import LeafIndex

_Ask = tuple[FillQuery, frozenset[str]]
_Lookup = Generator[_Ask, Fields, Fields]


def _lookup(
    index: LeafIndex, rows: Rows, query: FillQuery, excluded: frozenset[str]
) -> _Lookup:
    pieces: list[Fields] = []
    for row, leaf in feeds(index, rows, query, excluded):
        if not row.source.known:
            pieces.append((leaf,))
            continue
        inner = yield child(row, leaf), excluded | {row.site}
        pieces.append(finer(row, leaf, inner))
    return presented(index, query, (piece for found in pieces for piece in found))


def _answered(
    index: LeafIndex,
    rows: Rows,
    answers: dict[FillQuery, Fields],
    query: FillQuery,
) -> Fields:
    if query in answers:
        return answers[query]
    stack: list[tuple[FillQuery, _Lookup]] = [
        (query, _lookup(index, rows, query, frozenset()))
    ]
    sent: Fields | None = None
    while True:
        asked, walk = stack[-1]
        try:
            needed, excluded = walk.send(sent) if sent is not None else next(walk)
        except StopIteration as done:
            answer: Fields = done.value
            answers[asked] = answer
            stack.pop()
            if not stack:
                return answer
            sent = answer
            continue
        if needed in answers:
            sent = answers[needed]
            continue
        stack.append((needed, _lookup(index, rows, needed, excluded)))
        sent = None


def fill_tracer(
    index: LeafIndex, deps: Sequence[DepRow]
) -> Callable[[FillQuery], Fields]:
    rows = written_rows(deps)
    answers: dict[FillQuery, Fields] = {}
    return lambda query: _answered(index, rows, answers, query)
