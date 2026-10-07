"""Which bytes of a handed-over area matter: what callees read on entry, and callers read back."""

from __future__ import annotations

from dataclasses import dataclass

from cobble.dataflow.fields.spans import Spans, merged, pairs_of
from cobol_memory.field_extent import FieldExtent

Bounds = tuple[int, ...]


@dataclass(frozen=True)
class AreaNeed:
    """Area-relative bytes per parameter position that some callee needs on entry,
    and that some caller reads back after a LINK or CALL. ``whole`` keeps every byte
    of every area, which is what a run that did not work this out has to assume."""

    entry: tuple[tuple[int, Bounds], ...] = ()
    back: tuple[tuple[int, Bounds], ...] = ()
    whole: bool = False

    def at_entry(self, position: int, area: FieldExtent) -> tuple[FieldExtent, ...]:
        return self._within(self.entry, position, area)

    def read_back(self, position: int, area: FieldExtent) -> tuple[FieldExtent, ...]:
        return self._within(self.back, position, area)

    def _within(
        self,
        table: tuple[tuple[int, Bounds], ...],
        position: int,
        area: FieldExtent,
    ) -> tuple[FieldExtent, ...]:
        if self.whole:
            return (area,)
        return tuple(
            FieldExtent(
                region=area.region,
                start=area.start + low,
                length=min(high, area.length) - low,
                precision=area.precision,
                field_name=area.field_name,
            )
            for low, high in pairs_of(dict(table).get(position, ()))
            if low < area.length
        )


WHOLE_AREAS = AreaNeed(whole=True)


def relative(spans: Spans, area: FieldExtent) -> Bounds:
    """The bytes of ``area`` that ``spans`` holds, as offsets from its start."""
    end = area.start + area.length
    return merged(
        (max(low, area.start) - area.start, min(high, end) - area.start)
        for low, high in pairs_of(spans.get(area.region, ()))
        if low < end and area.start < high
    )


def _union(
    left: tuple[tuple[int, Bounds], ...], right: tuple[tuple[int, Bounds], ...]
) -> tuple[tuple[int, Bounds], ...]:
    """Pairs, not a mapping, so the need pickles into the worker processes."""
    lefts, rights = dict(left), dict(right)
    return tuple(
        (
            position,
            merged(
                (
                    *pairs_of(lefts.get(position, ())),
                    *pairs_of(rights.get(position, ())),
                )
            ),
        )
        for position in sorted({*lefts, *rights})
    )


def joined(left: AreaNeed, right: AreaNeed) -> AreaNeed:
    return AreaNeed(
        entry=_union(left.entry, right.entry),
        back=_union(left.back, right.back),
        whole=left.whole or right.whole,
    )
