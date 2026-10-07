"""A walk's seeds closed over the program's writes: every byte the seeds can depend on."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import accumulate, pairwise, repeat

from cobble.dataflow.fields.relevant import Relevant
from cobble.dataflow.fields.transfer import Write
from cobol_memory.field_extent import FieldExtent


def _grown(relevant: Relevant, writes: Sequence[Write]) -> Relevant:
    return Relevant(
        extents=relevant.extents
        | frozenset(
            source.extent
            for write in writes
            if relevant.touches(write.target)
            for source in write.sources
            if not source.origin
        )
    )


def closed(seeds: Iterable[FieldExtent], writes: Sequence[Write]) -> Relevant:
    steps = accumulate(
        repeat(None),
        lambda held, _: _grown(held, writes),
        initial=Relevant(extents=frozenset(seeds)),
    )
    return next(before for before, after in pairwise(steps) if before == after)
